#!/usr/bin/env python3
"""Download only immutable, allow-listed model files and record their hashes."""

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_for(root):
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".cache" in path.parts:
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    lock_path = Path(args.lock).resolve()
    model_root = Path(args.model_root).resolve()
    report_path = Path(args.report).resolve()
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    models = lock["models"]
    model_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    hf_home = model_root / "hf-cache"
    hf_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

    from huggingface_hub import hf_hub_download, snapshot_download

    destinations = {}

    def fetch(key, destination, patterns, repo_id=None):
        definition = models[key]
        target = model_root / destination
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        for attempt in range(1, 6):
            try:
                snapshot_download(
                    repo_id=repo_id or definition["repository"],
                    revision=definition["revision"],
                    local_dir=str(target),
                    local_dir_use_symlinks=False,
                    allow_patterns=patterns,
                    max_workers=1,
                    resume_download=True,
                )
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(attempt * 2)
        destinations[key] = {
            "repository": definition["repository"],
            "revision": definition["revision"],
            "root": str(target),
            "files": files_for(target),
        }

    fetch(
        "openvoice_v2",
        "checkpoints_v2",
        ["base_speakers/ses/*.pth", "converter/config.json", "converter/checkpoint.pth"],
    )
    fetch(
        "melotts_english",
        "melotts-english",
        ["config.json", "checkpoint.pth"],
    )
    fetch(
        "faster_whisper_tiny_en",
        "faster-whisper-tiny-en",
        ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
    )
    wavmark = models["wavmark"]
    wavmark_filename = (
        "step59000_snr39.99_pesq4.35_BERP_none0.30_mean1.81_std1.81.model.pkl"
    )
    for attempt in range(1, 6):
        try:
            wavmark_cached = Path(
                hf_hub_download(
                    repo_id=wavmark["repository"],
                    filename=wavmark_filename,
                    revision=wavmark["revision"],
                    resume_download=True,
                )
            )
            break
        except Exception:
            if attempt == 5:
                raise
            time.sleep(attempt * 2)
    wavmark_target = model_root / "wavmark"
    wavmark_target.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(wavmark_cached, wavmark_target / wavmark_filename)
    destinations["wavmark"] = {
        "repository": wavmark["repository"],
        "revision": wavmark["revision"],
        "root": str(wavmark_target),
        "files": files_for(wavmark_target),
    }
    wavmark_ref = (
        hf_home / "hub" / "models--M4869--WavMark" / "refs" / "main"
    )
    wavmark_ref.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    wavmark_ref.write_text(models["wavmark"]["revision"], encoding="utf-8")

    bert = models["bert_base_uncased"]
    bert_patterns = [
        "config.json",
        "model.safetensors",
        "pytorch_model.bin",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.txt",
    ]
    for attempt in range(1, 6):
        try:
            bert_snapshot = Path(
                snapshot_download(
                    repo_id="bert-base-uncased",
                    revision=bert["revision"],
                    allow_patterns=bert_patterns,
                    max_workers=1,
                    resume_download=True,
                )
            )
            break
        except Exception:
            if attempt == 5:
                raise
            time.sleep(attempt * 2)
    cache_repo = bert_snapshot.parent.parent
    refs = cache_repo / "refs"
    refs.mkdir(parents=True, exist_ok=True, mode=0o700)
    (refs / "main").write_text(bert["revision"], encoding="utf-8")
    destinations["bert_base_uncased"] = {
        "repository": bert["repository"],
        "revision": bert["revision"],
        "root": str(bert_snapshot),
        "files": files_for(bert_snapshot),
    }

    report = {
        "schema": "openvoice-v2.model-download/v1",
        "ok": all(item["files"] for item in destinations.values()),
        "hf_home": str(hf_home),
        "models": destinations,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(report_path)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
