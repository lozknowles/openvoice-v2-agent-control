#!/usr/bin/env python3
"""Fail closed before changing this repository from private to public."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


FORBIDDEN_SUFFIXES = {
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
    ".ogg",
    ".pth",
    ".pt",
    ".ckpt",
    ".safetensors",
    ".npy",
    ".npz",
    ".pem",
    ".key",
}
FORBIDDEN_NAMES = {
    ".env",
    ".htpasswd",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
}
SECRET_PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "github-token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "openai-key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "aws-access-key": re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    "bcrypt-password-hash": re.compile(rb"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"),
    "embedded-basic-auth": re.compile(rb"https?://[^\s/:]{2,}:[^\s/@]{4,}@"),
    "elevenlabs-key-assignment": re.compile(
        rb"(?:ELEVENLABS_API_KEY|XI_API_KEY)\s*[:=]\s*['\"]?[A-Za-z0-9_-]{24,}"
    ),
}


def git(root: Path, *args: str, text: bool = True):
    completed = subprocess.run(
        ["git", "-C", str(root)] + list(args),
        text=text,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr if text else completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(stderr.strip() or "git command failed")
    return completed.stdout


def forbidden_path(path: str) -> Optional[str]:
    candidate = Path(path)
    if candidate.name.lower() in FORBIDDEN_NAMES:
        return "forbidden filename"
    if candidate.suffix.lower() in FORBIDDEN_SUFFIXES:
        return "forbidden media, model, embedding or key suffix"
    return None


def history_blobs(root: Path) -> List[Tuple[str, str]]:
    records = []
    seen = set()
    for line in git(root, "rev-list", "--objects", "--all").splitlines():
        fields = line.split(" ", 1)
        if len(fields) != 2:
            continue
        object_id, path = fields
        if object_id in seen:
            continue
        if git(root, "cat-file", "-t", object_id).strip() != "blob":
            continue
        seen.add(object_id)
        records.append((object_id, path))
    return records


def scan_history(root: Path) -> Dict[str, object]:
    path_findings = []
    secret_findings = []
    oversized_blobs = []
    blobs = history_blobs(root)
    for object_id, path in blobs:
        path_reason = forbidden_path(path)
        if path_reason:
            path_findings.append(
                {"object": object_id, "path": path, "reason": path_reason}
            )
        size_text = git(root, "cat-file", "-s", object_id).strip()
        size = int(size_text)
        if size > 10 * 1024 * 1024:
            oversized_blobs.append({"object": object_id, "path": path, "bytes": size})
        if size > 2 * 1024 * 1024:
            continue
        content = git(root, "cat-file", "blob", object_id, text=False)
        if b"\x00" in content[:8192]:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                secret_findings.append(
                    {"object": object_id, "path": path, "pattern": name}
                )
    checks = {
        "no_audio_models_embeddings_keys_or_env_in_history": not path_findings,
        "no_secret_patterns_in_history": not secret_findings,
        "no_oversized_history_blobs": not oversized_blobs,
    }
    return {
        "checks": checks,
        "ok": all(checks.values()),
        "history_blob_count": len(blobs),
        "path_findings": path_findings,
        "secret_findings": secret_findings,
        "oversized_blobs": oversized_blobs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    report = {
        "schema": "speech-synthesis.public-history-audit/v1",
        **scan_history(root),
    }
    output = Path(args.report).resolve()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass
    print(json.dumps({"ok": report["ok"], "report": str(output)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
