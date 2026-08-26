#!/usr/bin/env python3
"""ASR intelligibility proxy for generated samples; not a listening score."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path


def normalise_words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def word_error_rate(reference, hypothesis):
    expected = normalise_words(reference)
    actual = normalise_words(hypothesis)
    previous = list(range(len(actual) + 1))
    for row, expected_word in enumerate(expected, start=1):
        current = [row]
        for column, actual_word in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected_word != actual_word),
                )
            )
        previous = current
    errors = previous[-1]
    return errors / max(1, len(expected)), errors, len(expected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-report", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--model-root", default="/fast/models/openvoice-v2")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-samples", type=int)
    args = parser.parse_args()
    benchmark = json.loads(Path(args.benchmark_report).read_text(encoding="utf-8"))
    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    text_by_case = {case["id"]: case["text"] for case in corpus["cases"]}

    from faster_whisper import WhisperModel

    started = time.perf_counter()
    model = WhisperModel(
        str(Path(args.model_root) / "faster-whisper-tiny-en"),
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
    )
    model_load_seconds = time.perf_counter() - started
    samples = []
    for provider in benchmark.get("providers", []):
        for sample in provider.get("samples", []):
            if args.max_samples is not None and len(samples) >= args.max_samples:
                break
            case_id = sample["case_id"]
            path = Path(sample["output_path"])
            generated_started = time.perf_counter()
            segments, _ = model.transcribe(
                str(path), language="en", beam_size=5, vad_filter=False
            )
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
            elapsed = time.perf_counter() - generated_started
            wer, errors, words = word_error_rate(text_by_case[case_id], transcript)
            samples.append(
                {
                    "provider": provider["provider"],
                    "case_id": case_id,
                    "output_sha256": sample["output_sha256"],
                    "transcript": transcript,
                    "word_error_rate": wer,
                    "word_errors": errors,
                    "reference_words": words,
                    "transcription_seconds": elapsed,
                }
            )
    report = {
        "schema": "speech-synthesis.asr-intelligibility-proxy/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_report": str(Path(args.benchmark_report).resolve()),
        "model": "Systran/faster-whisper-tiny.en",
        "model_revision": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
        "model_load_seconds": model_load_seconds,
        "samples": samples,
        "claim_boundary": "ASR word error rate is an objective proxy, not proof of human intelligibility or pronunciation quality.",
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    output.chmod(0o600)
    print(json.dumps({"ok": True, "samples": len(samples), "report": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
