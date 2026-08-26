#!/usr/bin/env python3
"""Run one bounded child while observing protected hpubuntu workloads."""

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


PROTECTED_PATTERN = (
    "llama|oasis|ocr|chandra|imageid|bioclip|kokoro|tts"
)
PROTECTED_ENDPOINTS = {
    "llama-default": "http://127.0.0.1:8080/health",
    "llama-coder": "http://127.0.0.1:8081/health",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def run_command(argv, timeout=10):
    try:
        completed = subprocess.run(
            argv, text=True, capture_output=True, timeout=timeout, check=False
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except Exception as exc:
        return 255, "", "%s: %s" % (type(exc).__name__, exc)


def gpu_snapshot():
    rc, out, err = run_command(
        [
            "nvidia-smi",
            "--query-gpu=index,name,driver_version,compute_cap,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    gpu = {"available": rc == 0, "error": err}
    if rc == 0 and out:
        values = [value.strip() for value in out.splitlines()[0].split(",")]
        gpu.update(
            {
                "index": int(values[0]),
                "name": values[1],
                "driver": values[2],
                "compute_capability": values[3],
                "memory_total_mib": int(values[4]),
                "memory_used_mib": int(values[5]),
                "memory_free_mib": int(values[6]),
                "utilization_percent": int(values[7]),
            }
        )
    rc, out, err = run_command(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    processes = []
    if rc == 0:
        for line in out.splitlines():
            values = [value.strip() for value in line.split(",", 2)]
            if len(values) == 3 and values[0].isdigit():
                processes.append(
                    {
                        "pid": int(values[0]),
                        "name": values[1],
                        "used_mib": int(values[2]),
                    }
                )
    gpu["processes"] = processes
    return gpu


def protected_units():
    units = []
    import re

    matcher = re.compile(PROTECTED_PATTERN, re.IGNORECASE)
    for scope, option in (("system", []), ("user", ["--user"])):
        rc, out, _ = run_command(
            [
                "systemctl",
                *option,
                "list-units",
                "--type=service",
                "--state=running",
                "--no-legend",
                "--no-pager",
            ]
        )
        if rc != 0:
            continue
        for line in out.splitlines():
            fields = line.split()
            if fields and matcher.search(line):
                units.append("%s:%s" % (scope, fields[0]))
    return sorted(set(units))


def endpoint_health():
    result = {}
    for name, url in PROTECTED_ENDPOINTS.items():
        rc, out, err = run_command(
            ["curl", "-fsS", "--max-time", "3", url], timeout=5
        )
        result[name] = {"ok": rc == 0, "body": out[:240], "error": err[:240]}
    return result


def snapshot():
    rc, load, _ = run_command(["cat", "/proc/loadavg"])
    rc_mem, mem, _ = run_command(["free", "-b"])
    return {
        "at": now(),
        "loadavg": load if rc == 0 else None,
        "memory": mem if rc_mem == 0 else None,
        "gpu": gpu_snapshot(),
        "protected_units": protected_units(),
        "endpoints": endpoint_health(),
    }


def health_failures(baseline, current):
    failures = []
    for name, value in current["endpoints"].items():
        if not value["ok"]:
            failures.append("endpoint_unhealthy:%s" % name)
    current_units = set(current["protected_units"])
    for unit in baseline["protected_units"]:
        if unit not in current_units:
            failures.append("protected_unit_not_running:%s" % unit)
    current_pids = {item["pid"] for item in current["gpu"].get("processes", [])}
    for process in baseline["gpu"].get("processes", []):
        if (
            "llama-server" in process["name"]
            or "kokoro" in process["name"].lower()
        ) and process["pid"] not in current_pids:
            failures.append("protected_gpu_pid_missing:%s" % process["pid"])
    return failures


def terminate_group(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def guarded_run(args):
    baseline = snapshot()
    initial_failures = health_failures(baseline, baseline)
    gpu = baseline["gpu"]
    if args.mode == "gpu":
        if not gpu.get("available"):
            initial_failures.append("gpu_unavailable")
        elif gpu.get("compute_capability") != "6.1":
            initial_failures.append("unexpected_compute_capability")
        elif gpu.get("memory_free_mib", 0) < args.min_free_before_mib:
            initial_failures.append("insufficient_vram_before")
    report = {
        "schema": "openvoice-v2.resource-guard/v1",
        "mode": args.mode,
        "started_at": now(),
        "baseline": baseline,
        "thresholds": {
            "min_free_before_mib": args.min_free_before_mib,
            "min_free_during_mib": args.min_free_during_mib,
        },
        "command_name": Path(args.command[0]).name if args.command else None,
        "initial_failures": initial_failures,
        "aborted": False,
        "abort_reasons": [],
        "peak_new_vram_mib": 0,
        "peak_total_vram_used_mib": gpu.get("memory_used_mib"),
    }
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if initial_failures:
        report["ended_at"] = now()
        report["returncode"] = 70
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "report": str(report_path), "failures": initial_failures}))
        return 70

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("guarded command required after --")
    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", "2")
    env.setdefault("MKL_NUM_THREADS", "2")
    env.setdefault("OPENBLAS_NUM_THREADS", "2")
    env.setdefault("NUMEXPR_NUM_THREADS", "2")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    if args.mode == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""
    baseline_pids = {item["pid"] for item in gpu.get("processes", [])}
    wrapped = ["nice", "-n", "15", "ionice", "-c", "3"] + command
    process = subprocess.Popen(wrapped, env=env, start_new_session=True)
    consecutive_failures = 0
    while process.poll() is None:
        time.sleep(args.poll_seconds)
        current = snapshot()
        failures = health_failures(baseline, current)
        current_gpu = current["gpu"]
        new_vram = sum(
            item["used_mib"]
            for item in current_gpu.get("processes", [])
            if item["pid"] not in baseline_pids
        )
        report["peak_new_vram_mib"] = max(report["peak_new_vram_mib"], new_vram)
        if current_gpu.get("memory_used_mib") is not None:
            prior = report["peak_total_vram_used_mib"] or 0
            report["peak_total_vram_used_mib"] = max(
                prior, current_gpu["memory_used_mib"]
            )
        if args.mode == "gpu" and current_gpu.get("memory_free_mib", 0) < args.min_free_during_mib:
            failures.append("vram_safety_margin_breached")
        if failures:
            consecutive_failures += 1
        else:
            consecutive_failures = 0
        if consecutive_failures >= 2:
            report["aborted"] = True
            report["abort_reasons"] = sorted(set(failures))
            terminate_group(process)
            break
    returncode = process.poll()
    final = snapshot()
    report["final"] = final
    report["final_failures"] = health_failures(baseline, final)
    report["ended_at"] = now()
    report["returncode"] = 70 if report["aborted"] else returncode
    report["ok"] = (
        not report["aborted"]
        and returncode == 0
        and not report["final_failures"]
    )
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(report_path)}))
    return 0 if report["ok"] else (returncode or 70)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    snap = subparsers.add_parser("snapshot")
    snap.add_argument("--report", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--mode", choices=["cpu", "gpu"], required=True)
    run.add_argument("--report", required=True)
    run.add_argument("--min-free-before-mib", type=int, default=6144)
    run.add_argument("--min-free-during-mib", type=int, default=2048)
    run.add_argument("--poll-seconds", type=float, default=1.0)
    run.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.subcommand == "snapshot":
        value = snapshot()
        value["schema"] = "openvoice-v2.resource-snapshot/v1"
        value["ok"] = not health_failures(value, value)
        path = Path(args.report).resolve()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": value["ok"], "report": str(path)}))
        return 0 if value["ok"] else 1
    return guarded_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
