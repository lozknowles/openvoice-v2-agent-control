#!/usr/bin/env python3
"""Fixed, allow-listed entry point used by Agent Control Actions."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def run(argv, env=None):
    completed = subprocess.run(argv, env=env, check=False)
    return completed.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=["preflight", "install", "qualify-cpu", "qualify-gpu", "compare", "hygiene"],
    )
    args = parser.parse_args()
    integration_root = Path(
        os.environ.get("OPENVOICE_V2_INTEGRATION_ROOT", "/fast/repos/openvoice-v2-agent-control")
    ).resolve()
    source_root = Path(
        os.environ.get("OPENVOICE_V2_SOURCE_ROOT", "/fast/repos/openvoice-v2-upstream")
    ).resolve()
    env_root = Path(
        os.environ.get("OPENVOICE_V2_ENV_ROOT", "/fast/venvs/openvoice-v2-py39")
    ).resolve()
    model_root = Path(
        os.environ.get("OPENVOICE_V2_MODEL_ROOT", "/fast/models/openvoice-v2")
    ).resolve()
    evidence_root = Path(
        os.environ.get("OPENVOICE_V2_EVIDENCE_ROOT", "/fast/qualification/openvoice-v2-current")
    ).resolve()
    qualification_dir = Path(
        os.environ.get("OPENVOICE_V2_QUALIFICATION_DIR", str(evidence_root))
    ).resolve()
    if not integration_root.is_dir() or not (integration_root / "UPSTREAM.lock.json").is_file():
        raise SystemExit("configured integration repository is invalid")
    if args.action != "preflight" and not source_root.is_dir():
        raise SystemExit("configured OpenVoice source repository is invalid")
    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    qualification_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    guard = integration_root / "scripts/resource_guard.py"
    environment = os.environ.copy()
    environment.update(
        {
            "OPENVOICE_V2_INTEGRATION_ROOT": str(integration_root),
            "OPENVOICE_V2_SOURCE_ROOT": str(source_root),
            "OPENVOICE_V2_ENV_ROOT": str(env_root),
            "OPENVOICE_V2_MODEL_ROOT": str(model_root),
            "OPENVOICE_V2_EVIDENCE_ROOT": str(evidence_root),
            "OPENVOICE_V2_QUALIFICATION_DIR": str(qualification_dir),
        }
    )

    if args.action == "preflight":
        report = evidence_root / "preflight.json"
        rc = run([sys.executable, str(guard), "snapshot", "--report", str(report)], environment)
        value = load_json(report)
        print(json.dumps({"ok": rc == 0 and value.get("ok") is True, "report": str(report)}))
        return 0 if rc == 0 and value.get("ok") is True else 1

    if args.action == "install":
        guard_report = evidence_root / "install-guard.json"
        rc = run(
            [
                sys.executable,
                str(guard),
                "run",
                "--mode",
                "cpu",
                "--report",
                str(guard_report),
                "--",
                "/usr/bin/bash",
                str(integration_root / "scripts/install_openvoice_v2.sh"),
            ],
            environment,
        )
        install_report = evidence_root / "install-report.json"
        value = {
            "schema": "openvoice-v2.agent-control-install-action/v1",
            "ok": rc == 0 and install_report.is_file(),
            "guard": load_json(guard_report) if guard_report.is_file() else None,
            "installation": load_json(install_report) if install_report.is_file() else None,
        }
        report = write_json(evidence_root / "agent-control-install-action.json", value)
        print(json.dumps({"ok": value["ok"], "report": str(report)}))
        return 0 if value["ok"] else 1

    if args.action in {"qualify-cpu", "qualify-gpu"}:
        device = "cpu" if args.action.endswith("cpu") else "cuda"
        guard_report = evidence_root / ("%s-guard.json" % device)
        qualification_report = evidence_root / ("%s-qualification.json" % device)
        qualifier = integration_root / "scripts/qualify_openvoice_v2.py"
        rc = run(
            [
                sys.executable,
                str(guard),
                "run",
                "--mode",
                "gpu" if device == "cuda" else "cpu",
                "--report",
                str(guard_report),
                "--",
                str(env_root / "bin/python"),
                str(qualifier),
                "--device",
                device,
                "--qualification-dir",
                str(qualification_dir),
                "--model-root",
                str(model_root),
                "--report",
                str(qualification_report),
            ],
            environment,
        )
        guard_value = load_json(guard_report) if guard_report.is_file() else None
        if device == "cuda" and rc != 0 and not qualification_report.is_file():
            failures = set((guard_value or {}).get("initial_failures", []))
            safe_skip_failures = {
                "gpu_unavailable",
                "unexpected_compute_capability",
                "insufficient_vram_before",
            }
            if failures and failures.issubset(safe_skip_failures):
                value = {
                    "schema": "openvoice-v2.qualification/v1",
                    "device": "cuda",
                    "ok": True,
                    "attempted": False,
                    "safely_skipped": True,
                    "reasons": sorted(failures),
                    "guard": guard_value,
                    "qualification_verdict": "PARTIAL",
                }
                write_json(qualification_report, value)
                rc = 0
        qualification_value = (
            load_json(qualification_report) if qualification_report.is_file() else None
        )
        value = {
            "schema": "openvoice-v2.agent-control-qualification-action/v1",
            "device": device,
            "ok": rc == 0 and qualification_value is not None and qualification_value.get("ok") is True,
            "guard": guard_value,
            "qualification": qualification_value,
        }
        report = write_json(
            evidence_root / ("agent-control-%s-action.json" % device), value
        )
        print(json.dumps({"ok": value["ok"], "report": str(report)}))
        return 0 if value["ok"] else 1

    if args.action == "compare":
        report = evidence_root / "cpu-gpu-comparison.json"
        rc = run(
            [
                str(env_root / "bin/python"),
                str(integration_root / "scripts/compare_reports.py"),
                "--cpu",
                str(evidence_root / "cpu-qualification.json"),
                "--gpu",
                str(evidence_root / "cuda-qualification.json"),
                "--report",
                str(report),
            ],
            environment,
        )
        value = load_json(report) if report.is_file() else {"ok": False}
        print(json.dumps({"ok": rc == 0 and value.get("ok") is True, "report": str(report)}))
        return 0 if rc == 0 and value.get("ok") is True else 1

    report = evidence_root / "repository-hygiene.json"
    python = str(env_root / "bin/python") if (env_root / "bin/python").is_file() else sys.executable
    rc = run(
        [
            python,
            str(integration_root / "scripts/verify_repo_hygiene.py"),
            "--repo",
            str(integration_root),
            "--report",
            str(report),
        ],
        environment,
    )
    value = load_json(report) if report.is_file() else {"ok": False}
    print(json.dumps({"ok": rc == 0 and value.get("ok") is True, "report": str(report)}))
    return 0 if rc == 0 and value.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
