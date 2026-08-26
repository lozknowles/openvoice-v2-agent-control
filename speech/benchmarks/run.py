#!/usr/bin/env python3
"""Reproducible provider-neutral synthesis qualification runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from speech.benchmarks.resources import ResourceMonitor, gpu_state
from speech.interface import SynthesisRequest, output_path_for, provider_class


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_CATEGORIES = {
    "short conversational sentence",
    "long paragraph",
    "numbers",
    "dates",
    "UK place names",
    "unusual names",
    "abbreviations",
    "technical terminology",
    "questions",
    "emotional/excited speech",
    "neutral informational speech",
}
PROTECTED_USER_UNITS = (
    "cartoon-collingham-kokoro-gpu.service",
    "lincoln-course-match-ocr.service",
    "llama-coder.service",
    "llama-server.service",
    "localwalks-imageid-staging-api.service",
    "localwalks-imageid-staging-worker.service",
    "localwalks-imageid.service",
    "openvoice-v2-public.service",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    os.close(temporary_fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(str(temporary), str(path))
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_corpus(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "speech-synthesis.benchmark-corpus/v1":
        raise ValueError("unsupported benchmark corpus schema")
    ids: Set[str] = set()
    categories: Set[str] = set()
    for case in payload.get("cases", []):
        case_id = case.get("id")
        if not case_id or case_id in ids:
            raise ValueError("corpus case IDs must be non-empty and unique")
        ids.add(case_id)
        text = case.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("corpus case %s has no text" % case_id)
        categories.update(case.get("categories") or [])
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        raise ValueError("corpus is missing required categories: %s" % sorted(missing))
    return payload


def command_output(command: Sequence[str]) -> Optional[str]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def protected_snapshot() -> Dict[str, Any]:
    units = {}
    for unit in PROTECTED_USER_UNITS:
        units[unit] = command_output(["systemctl", "--user", "is-active", unit])
    endpoints = {}
    for port in (8080, 8081):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:%s/health" % port, timeout=3
            ) as response:
                body = response.read(512).decode("utf-8", errors="replace")
                endpoints[str(port)] = {"status": response.status, "body": body}
        except Exception as exc:
            endpoints[str(port)] = {"status": None, "error": type(exc).__name__}
    return {
        "captured_at": utc_now(),
        "units": units,
        "llama_health": endpoints,
        "gpu": gpu_state(),
    }


def protected_snapshot_ok(snapshot: Mapping[str, Any]) -> bool:
    return all(value == "active" for value in snapshot["units"].values()) and all(
        item.get("status") == 200 for item in snapshot["llama_health"].values()
    )


def protected_baseline_preserved(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    if not protected_snapshot_ok(after):
        return False
    before_pids = {
        item["pid"]
        for item in before.get("gpu", {}).get("processes", [])
        if item.get("pid") is not None
    }
    after_pids = {
        item["pid"]
        for item in after.get("gpu", {}).get("processes", [])
        if item.get("pid") is not None
    }
    return before_pids.issubset(after_pids)


def git_commit() -> Optional[str]:
    return command_output(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"])


def output_root_is_outside_git(path: Path) -> bool:
    root = REPOSITORY_ROOT.resolve()
    candidate = path.resolve()
    return candidate != root and root not in candidate.parents


def provider_voice(name: str, args: argparse.Namespace) -> Optional[str]:
    if name == "openvoice":
        return args.openvoice_reference
    if name == "local":
        return args.local_voice
    if name == "melotts":
        return args.melotts_voice
    if name == "elevenlabs":
        return args.elevenlabs_voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
    return None


def unavailable_record(name: str, reason: str) -> Dict[str, Any]:
    return {
        "provider": name,
        "status": "UNAVAILABLE",
        "speech_produced": False,
        "qualified": False,
        "reason": reason,
        "samples": [],
    }


def run_provider(
    name: str,
    corpus: Mapping[str, Any],
    output_root: Path,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    adapter_type = provider_class(name)
    available, reason = adapter_type.availability()
    if not available:
        return unavailable_record(name, reason)
    voice = provider_voice(name, args)
    if not voice:
        return unavailable_record(name, "no voice or authorised reference was configured")
    if name == "openvoice" and not Path(voice).is_file():
        return unavailable_record(name, "authorised OpenVoice reference does not exist")
    if name == "elevenlabs" and not args.allow_cloud:
        return unavailable_record(name, "cloud execution was not explicitly enabled")

    adapter = adapter_type()
    provider_output = output_root / "samples" / name
    provider_output.mkdir(parents=True, exist_ok=True, mode=0o700)
    initialization_resources: Dict[str, Any]
    try:
        with ResourceMonitor(lambda: adapter.process_ids()) as monitor:
            initialization_seconds = adapter.initialization_seconds
            initialization_metadata = dict(adapter.initialization_metadata)
        initialization_resources = monitor.summary()
        record: Dict[str, Any] = {
            "provider": name,
            "engine": adapter.engine,
            "status": "RUNNING",
            "availability": reason,
            "capabilities": adapter.capabilities().as_dict(),
            "initialization_seconds": initialization_seconds,
            "initialization_metadata": initialization_metadata,
            "initialization_resources": initialization_resources,
            "samples": [],
            "failures": [],
            "speech_produced": False,
            "qualified": False,
        }
        selected_cases = list(corpus["cases"])
        if args.case:
            wanted = set(args.case)
            selected_cases = [case for case in selected_cases if case["id"] in wanted]
        if args.max_cases is not None:
            selected_cases = selected_cases[: args.max_cases]
        for case in selected_cases:
            request = SynthesisRequest(
                text=case["text"],
                voice=voice,
                provider=name,
                speed=args.speed,
                style=None,
                output_format=args.output_format,
                language=corpus["language"],
                output_filename=case["id"],
                output_dir=provider_output,
                consent_confirmed=True,
                consent_basis=args.consent_basis,
                allow_cloud=args.allow_cloud,
            )
            output_path = output_path_for(request)
            try:
                with ResourceMonitor(lambda: adapter.process_ids()) as monitor:
                    result = adapter.synthesize(request, output_path)
                resources = monitor.summary()
                result_payload = result.as_dict()
                result_payload.update(
                    {
                        "case_id": case["id"],
                        "categories": case["categories"],
                        "text_sha256": hashlib.sha256(
                            case["text"].encode("utf-8")
                        ).hexdigest(),
                        "output_sha256": sha256_file(result.output_path),
                        "resources": resources,
                        "human_quality_review": "not performed",
                    }
                )
                record["samples"].append(result_payload)
                record["speech_produced"] = True
            except Exception as exc:
                record["failures"].append(
                    {
                        "case_id": case["id"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                if output_path.exists():
                    output_path.unlink()
                if output_path.with_suffix(".json").exists():
                    output_path.with_suffix(".json").unlink()
            if args.enforce_hpubuntu_protections:
                check = protected_snapshot()
                if not protected_snapshot_ok(check):
                    record["failures"].append(
                        {
                            "case_id": case["id"],
                            "error_type": "ProtectedWorkloadHealthFailure",
                            "error": "a protected workload changed health during the run",
                        }
                    )
                    break
        expected = len(selected_cases)
        record["status"] = (
            "PASS"
            if record["speech_produced"]
            and not record["failures"]
            and len(record["samples"]) == expected
            else "PARTIAL"
            if record["speech_produced"]
            else "FAIL"
        )
        record["qualified"] = record["status"] == "PASS"
        return record
    except Exception as exc:
        return {
            "provider": name,
            "status": "FAIL",
            "speech_produced": False,
            "qualified": False,
            "reason": "%s: %s" % (type(exc).__name__, exc),
            "samples": [],
        }
    finally:
        adapter.close()


def listening_manifest(providers: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    template = json.loads(
        (REPOSITORY_ROOT / "speech/benchmarks/listening-template.json").read_text(
            encoding="utf-8"
        )
    )
    for provider in providers:
        for sample in provider.get("samples", []):
            template["samples"].append(
                {
                    "provider": provider["provider"],
                    "engine": provider.get("engine"),
                    "case_id": sample["case_id"],
                    "output_path": sample["output_path"],
                    "output_sha256": sample["output_sha256"],
                    "intelligibility_notes": None,
                    "speaker_similarity_notes": None,
                    "speaker_similarity_applicable": provider["provider"] == "openvoice",
                    "noise_and_artefact_notes": None,
                    "pronunciation_notes": None,
                    "preference_notes": None,
                }
            )
    return template


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--providers",
        default="openvoice,local,melotts,elevenlabs",
        help="comma-separated provider adapters",
    )
    parser.add_argument(
        "--corpus",
        default=str(REPOSITORY_ROOT / "speech/benchmarks/corpus.en-GB.json"),
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--openvoice-reference")
    parser.add_argument("--openvoice-device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--local-device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--melotts-device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--local-voice", default="bm_george")
    parser.add_argument("--melotts-voice", default="EN-BR")
    parser.add_argument("--elevenlabs-voice-id")
    parser.add_argument("--allow-cloud", action="store_true")
    parser.add_argument("--consent-basis", required=True)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--output-format", choices=["wav", "mp3"], default="wav")
    parser.add_argument("--case", action="append")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--enforce-hpubuntu-protections", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).resolve()
    if not output_root_is_outside_git(output_root):
        raise SystemExit("benchmark outputs must remain outside the Git worktree")
    if output_root.exists() and any(output_root.iterdir()):
        raise SystemExit("refusing to reuse a non-empty benchmark output directory")
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_root.chmod(0o700)
    corpus_path = Path(args.corpus).resolve()
    corpus = load_corpus(corpus_path)
    os.environ["SPEECH_OPENVOICE_DEVICE"] = args.openvoice_device
    os.environ["SPEECH_KOKORO_DEVICE"] = args.local_device
    os.environ["SPEECH_MELO_DEVICE"] = args.melotts_device

    requested = [item.strip() for item in args.providers.split(",") if item.strip()]
    unknown = set(requested) - {"openvoice", "local", "melotts", "elevenlabs"}
    if unknown:
        raise SystemExit("unknown providers: %s" % sorted(unknown))
    before = protected_snapshot() if args.enforce_hpubuntu_protections else None
    if before is not None and not protected_snapshot_ok(before):
        raise SystemExit("protected workload preflight failed; no synthesis was started")
    started = time.perf_counter()
    providers = []
    for name in requested:
        print(json.dumps({"event": "provider_start", "provider": name}), flush=True)
        providers.append(run_provider(name, corpus, output_root, args))
        print(
            json.dumps(
                {
                    "event": "provider_end",
                    "provider": name,
                    "status": providers[-1]["status"],
                }
            ),
            flush=True,
        )
    after = protected_snapshot() if args.enforce_hpubuntu_protections else None
    protections_preserved = (
        protected_baseline_preserved(before, after)
        if before is not None and after is not None
        else None
    )
    report = {
        "schema": "speech-synthesis.qualification/v1",
        "generated_at": utc_now(),
        "repository_commit": git_commit(),
        "corpus": {
            "id": corpus["id"],
            "language": corpus["language"],
            "path": str(corpus_path),
            "sha256": sha256_file(corpus_path),
            "case_count": len(corpus["cases"]),
        },
        "host": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "gpu_before": before.get("gpu") if before else gpu_state(),
        },
        "configuration": {
            "openvoice_device": args.openvoice_device,
            "local_device": args.local_device,
            "melotts_device": args.melotts_device,
            "cloud_allowed": args.allow_cloud,
            "output_format": args.output_format,
            "speed": args.speed,
        },
        "providers": providers,
        "protected_workloads": {
            "enforced": args.enforce_hpubuntu_protections,
            "before": before,
            "after": after,
            "preserved": protections_preserved,
        },
        "elapsed_seconds": time.perf_counter() - started,
        "quality_boundary": {
            "human_listening_performed": False,
            "subjective_quality_scores_invented": False,
            "speaker_similarity_proven": False,
        },
    }
    write_private_json(output_root / "benchmark-report.json", report)
    write_private_json(output_root / "listening-manifest.json", listening_manifest(providers))
    success = all(
        provider["status"] in {"PASS", "UNAVAILABLE"} for provider in providers
    ) and protections_preserved is not False
    print(
        json.dumps(
            {
                "ok": success,
                "report": str(output_root / "benchmark-report.json"),
                "listening_manifest": str(output_root / "listening-manifest.json"),
            }
        )
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
