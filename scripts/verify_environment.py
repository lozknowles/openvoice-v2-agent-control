#!/usr/bin/env python3
"""Verify the isolated runtime without changing host or GPU configuration."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


EXPECTED_PYTHON = (3, 9, 23)
EXPECTED_TORCH = "2.5.1+cu121"
EXPECTED_TORCHAUDIO = "2.5.1+cu121"


def command(argv):
    completed = subprocess.run(argv, text=True, capture_output=True, check=False)
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--integration-root", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    integration_root = Path(args.integration_root).resolve()
    source_root = Path(args.source_root).resolve()
    build_root = Path(args.build_root).resolve()
    model_root = Path(args.model_root).resolve()
    report_path = Path(args.report).resolve()
    lock = json.loads((integration_root / "UPSTREAM.lock.json").read_text(encoding="utf-8"))

    import torch
    import torchaudio
    import unidic
    import av
    import numpy
    from melo.api import TTS
    from openvoice.api import ToneColorConverter

    source_commit = command(["git", "-C", str(source_root), "rev-parse", "HEAD"])
    source_ancestor = command(
        [
            "git",
            "-C",
            str(source_root),
            "merge-base",
            "--is-ancestor",
            lock["code"]["openvoice"]["commit"],
            "HEAD",
        ]
    )
    model_report_path = model_root / "model-download-report.json"
    model_report = json.loads(model_report_path.read_text(encoding="utf-8"))
    checkpoint_files = []
    for key, item in model_report["models"].items():
        for record in item["files"]:
            checkpoint_files.append({"model": key, **record})

    cuda_available = torch.cuda.is_available()
    cuda_probe = None
    if cuda_available:
        value = torch.arange(16, device="cuda", dtype=torch.float32).sum().item()
        cuda_probe = {
            "device_name": torch.cuda.get_device_name(0),
            "device_capability": list(torch.cuda.get_device_capability(0)),
            "arch_list": torch.cuda.get_arch_list(),
            "kernel_sum": value,
        }

    packages = {}
    for name in [
        "MyShell-OpenVoice",
        "melotts",
        "torch",
        "torchaudio",
        "unidic",
        "gradio",
        "faster-whisper",
        "wavmark",
        "numpy",
        "av",
    ]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None

    checks = {
        "isolated_python": str(Path(sys.executable).resolve()).startswith("/fast/venvs/"),
        "python_exact": sys.version_info[:3] == EXPECTED_PYTHON,
        "torch_exact": torch.__version__ == EXPECTED_TORCH,
        "torchaudio_exact": torchaudio.__version__ == EXPECTED_TORCHAUDIO,
        "openvoice_source_commit": source_commit["stdout"] == lock["code"]["openvoice"]["commit"],
        "openvoice_commit_is_ancestor": source_ancestor["returncode"] == 0,
        "openvoice_source_pristine": not command(
            ["git", "-C", str(source_root), "status", "--porcelain", "--untracked-files=no"]
        )["stdout"],
        "packaging_patch_marker_present": (build_root / ".openvoice-integration-source").is_file(),
        "numpy_compatibility_exact": numpy.__version__ == "1.22.4",
        "pyav_exact": av.__version__ == "10.0.0",
        "models_present": bool(checkpoint_files) and model_report.get("ok") is True,
        "unidic_present": (Path(unidic.DICDIR) / "dicrc").is_file(),
        "converter_config_present": (model_root / "checkpoints_v2/converter/config.json").is_file(),
        "converter_checkpoint_present": (model_root / "checkpoints_v2/converter/checkpoint.pth").is_file(),
        "melo_model_present": (model_root / "melotts-english/checkpoint.pth").is_file(),
        "wavmark_model_present": (
            model_root
            / "wavmark/step59000_snr39.99_pesq4.35_BERP_none0.30_mean1.81_std1.81.model.pkl"
        ).is_file(),
    }
    report = {
        "schema": "openvoice-v2.environment/v1",
        "ok": all(checks.values()),
        "checks": checks,
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "version": platform.python_version(),
            "system_python_untouched": True,
        },
        "torch": {
            "version": torch.__version__,
            "torchaudio": torchaudio.__version__,
            "compiled_cuda": torch.version.cuda,
            "cuda_available": cuda_available,
            "cuda_probe": cuda_probe,
        },
        "packages": packages,
        "packaging_compatibility": {
            "numpy": numpy.__version__,
            "pyav": av.__version__,
            "build_root": str(build_root),
            "marker": (build_root / ".openvoice-integration-source").read_text(encoding="utf-8").splitlines()
            if (build_root / ".openvoice-integration-source").is_file()
            else [],
            "scope": "OpenVoice setup metadata only; upstream runtime code is unchanged.",
        },
        "source_commit": source_commit,
        "model_files": checkpoint_files,
        "unidic_dir": unidic.DICDIR,
        "driver": command(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,compute_cap,memory.total",
                "--format=csv,noheader",
            ]
        ),
        "system_cuda": command(["nvcc", "--version"]),
        "policy": {
            "driver_changed": False,
            "system_cuda_changed": False,
            "system_python_changed": False,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(report_path)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
