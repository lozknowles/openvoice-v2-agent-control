#!/usr/bin/env python3
"""Compare CPU/GPU measurements without asserting perceptual equivalence."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", required=True)
    parser.add_argument("--gpu", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    cpu = json.loads(Path(args.cpu).read_text(encoding="utf-8"))
    gpu = json.loads(Path(args.gpu).read_text(encoding="utf-8"))
    comparisons = []
    cpu_outputs = cpu.get("synthesis", {}).get("outputs", [])
    gpu_outputs = gpu.get("synthesis", {}).get("outputs", [])
    for cpu_output, gpu_output in zip(cpu_outputs, gpu_outputs):
        comparisons.append(
            {
                "index": cpu_output["index"],
                "text_equal": cpu_output["text"] == gpu_output["text"],
                "binary_hash_equal": cpu_output["sha256"] == gpu_output["sha256"],
                "cpu": {
                    "generation_seconds": cpu_output["generation_seconds"],
                    "real_time_factor": cpu_output["real_time_factor"],
                    "duration_seconds": cpu_output["signal"]["duration_seconds"],
                    "wer": cpu_output["intelligibility"]["wer"],
                    "reference_embedding_cosine": cpu_output["speaker_similarity_proxy"]["cosine"],
                    "watermark_decoded": cpu_output["watermark_decoded"],
                },
                "gpu": {
                    "generation_seconds": gpu_output["generation_seconds"],
                    "real_time_factor": gpu_output["real_time_factor"],
                    "duration_seconds": gpu_output["signal"]["duration_seconds"],
                    "wer": gpu_output["intelligibility"]["wer"],
                    "reference_embedding_cosine": gpu_output["speaker_similarity_proxy"]["cosine"],
                    "watermark_decoded": gpu_output["watermark_decoded"],
                },
                "perceptual_similarity_proven": False,
            }
        )
    gpu_safely_skipped = gpu.get("safely_skipped") is True
    functional_ok = cpu.get("ok") is True and (gpu.get("ok") is True or gpu_safely_skipped)
    report = {
        "schema": "openvoice-v2.cpu-gpu-comparison/v1",
        "ok": functional_ok,
        "cpu_functional": cpu.get("ok") is True,
        "gpu_functional": gpu.get("ok") is True,
        "gpu_safely_skipped": gpu_safely_skipped,
        "comparisons": comparisons,
        "claim_boundary": (
            "Timing, ASR, watermark, signal and model-internal embedding proxies are compared. "
            "No subjective speaker similarity or absence of audible artefacts is claimed as proven."
        ),
        "verdict": "PARTIAL" if functional_ok else "FAIL",
        "remaining": [
            "Independent human listening for intelligibility, similarity, noise and artefacts",
            "A separately authorised real-person reference if that use is desired",
        ],
    }
    path = Path(args.report).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(json.dumps({"ok": report["ok"], "report": str(path)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
