#!/usr/bin/env python3
"""Fail if the integration repository contains forbidden sensitive artifacts."""

import argparse
import json
import re
import subprocess
from pathlib import Path


FORBIDDEN_SUFFIXES = {
    ".wav", ".mp3", ".flac", ".m4a", ".pth", ".pt", ".ckpt",
    ".safetensors", ".bin", ".npy", ".npz", ".pem", ".key",
}
SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[ps]_[A-Za-z0-9]{20,}\b"),
    "openai-key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
}


def git(root, *args):
    completed = subprocess.run(
        ["git", "-C", str(root)] + list(args),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    tracked = [line for line in git(root, "ls-files").splitlines() if line]
    untracked = [
        line
        for line in git(root, "ls-files", "--others", "--exclude-standard").splitlines()
        if line
    ]
    forbidden_tracked = [path for path in tracked if Path(path).suffix.lower() in FORBIDDEN_SUFFIXES]
    forbidden_untracked = [
        path for path in untracked if Path(path).suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    candidates = sorted(set(tracked + untracked))
    secret_hits = []
    unsafe_bind_hits = []
    share_hits = []
    for relative in candidates:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                secret_hits.append({"path": relative, "pattern": name})
        is_runtime_script = relative.startswith("scripts/") and relative.endswith(".py")
        if is_runtime_script and re.search(r"share\s*=\s*True|['\"]--share['\"]", text):
            share_hits.append(relative)
        if is_runtime_script and re.search(r"server_name\s*=\s*['\"](?:0\.0\.0\.0|::)['\"]", text):
            unsafe_bind_hits.append(relative)
    checks = {
        "no_tracked_audio_models_or_keys": not forbidden_tracked,
        "no_untracked_audio_models_or_keys": not forbidden_untracked,
        "no_secret_patterns": not secret_hits,
        "no_gradio_share": not share_hits,
        "no_public_default_bind": not unsafe_bind_hits,
    }
    report = {
        "schema": "openvoice-v2.repository-hygiene/v1",
        "ok": all(checks.values()),
        "checks": checks,
        "forbidden_tracked": forbidden_tracked,
        "forbidden_untracked": forbidden_untracked,
        "secret_hits": secret_hits,
        "share_hits": share_hits,
        "unsafe_bind_hits": unsafe_bind_hits,
        "tracked_file_count": len(tracked),
        "untracked_file_count": len(untracked),
        "scanned_file_count": len(candidates),
    }
    path = Path(args.report).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(path)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
