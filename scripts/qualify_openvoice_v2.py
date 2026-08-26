#!/usr/bin/env python3
"""Generate fixed British-English samples and record objective evidence."""

import argparse
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from openvoice_v2_runtime import OpenVoiceV2Runtime, WATERMARK_MESSAGE


FIXED_SENTENCES = [
    "The quick brown fox jumps over the lazy dog beside the old village bridge.",
    "At half past seven, Eleanor carefully checked the weather before walking to Collingham.",
    "Clear speech should remain intelligible, steady, and free from obvious clicks or harsh distortion.",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def gpu_state():
    command = [
        "nvidia-smi",
        "--query-gpu=name,driver_version,compute_cap,memory.total,memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    result = {"ok": completed.returncode == 0, "error": completed.stderr.strip()}
    if completed.returncode == 0:
        values = [value.strip() for value in completed.stdout.splitlines()[0].split(",")]
        result.update(
            {
                "name": values[0],
                "driver": values[1],
                "compute_capability": values[2],
                "total_mib": int(values[3]),
                "used_mib": int(values[4]),
                "free_mib": int(values[5]),
                "utilization_percent": int(values[6]),
            }
        )
    command = [
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_memory",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    processes = []
    if completed.returncode == 0:
        for line in completed.stdout.splitlines():
            fields = [value.strip() for value in line.split(",", 2)]
            if len(fields) == 3 and fields[0].isdigit():
                processes.append(
                    {"pid": int(fields[0]), "name": fields[1], "used_mib": int(fields[2])}
                )
    result["processes"] = processes
    return result


class GpuMonitor:
    def __init__(self):
        self.stop_event = threading.Event()
        self.samples = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop_event.is_set():
            self.samples.append({"at": time.time(), "state": gpu_state()})
            self.stop_event.wait(0.25)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def summary(self):
        own_pid = os.getpid()
        own_values = []
        total_values = []
        free_values = []
        for sample in self.samples:
            state = sample["state"]
            if state.get("used_mib") is not None:
                total_values.append(state["used_mib"])
                free_values.append(state["free_mib"])
            for process in state.get("processes", []):
                if process["pid"] == own_pid:
                    own_values.append(process["used_mib"])
        return {
            "samples": len(self.samples),
            "peak_process_vram_mib": max(own_values) if own_values else 0,
            "peak_total_vram_used_mib": max(total_values) if total_values else None,
            "minimum_free_vram_mib": min(free_values) if free_values else None,
        }


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


def transcribe_outputs(outputs, output_dir, model_root):
    from faster_whisper import WhisperModel

    started = time.perf_counter()
    model = WhisperModel(
        str(Path(model_root) / "faster-whisper-tiny-en"),
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
    )
    load_seconds = time.perf_counter() - started
    records = []
    for output in outputs:
        path = Path(output_dir) / output["filename"]
        started = time.perf_counter()
        segments, _ = model.transcribe(
            str(path),
            language="en",
            beam_size=5,
            vad_filter=False,
        )
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        elapsed = time.perf_counter() - started
        wer, errors, words = word_error_rate(output["text"], transcript)
        records.append(
            {
                "index": output["index"],
                "transcript": transcript,
                "wer": wer,
                "word_errors": errors,
                "reference_words": words,
                "seconds": elapsed,
                "model": "Systran/faster-whisper-tiny.en",
                "model_revision": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
            }
        )
    return {"model_load_seconds": load_seconds, "outputs": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cpu", "cuda"], required=True)
    parser.add_argument("--qualification-dir", required=True)
    parser.add_argument("--model-root", default="/fast/models/openvoice-v2")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    qualification_dir = Path(args.qualification_dir).resolve()
    output_dir = qualification_dir / ("samples-" + args.device)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    reference_path = qualification_dir / "authorised-synthetic-reference.wav"
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    before_gpu = gpu_state()

    started = time.perf_counter()
    monitor = GpuMonitor() if args.device == "cuda" else None
    try:
        if monitor:
            monitor.__enter__()
        runtime = OpenVoiceV2Runtime(
            device=args.device,
            language="British English",
            model_root=args.model_root,
        )
        if args.device == "cpu":
            reference_metadata = runtime.generate_authorised_fixture(reference_path)
        else:
            if not reference_path.is_file() or not reference_path.with_suffix(".json").is_file():
                raise RuntimeError("CPU-generated authorised reference is required before GPU qualification")
            reference_metadata = json.loads(
                reference_path.with_suffix(".json").read_text(encoding="utf-8")
            )
        synthesis = runtime.synthesise_many(
            reference_path=reference_path,
            texts=FIXED_SENTENCES,
            output_dir=output_dir,
            filename_prefix="comparison-%s" % args.device,
            consent_confirmed=True,
            consent_basis="authorised synthetic MIT-licensed qualification fixture",
        )
        if monitor:
            monitor.__exit__(None, None, None)
        asr = transcribe_outputs(synthesis["outputs"], output_dir, args.model_root)
        asr_by_index = {record["index"]: record for record in asr["outputs"]}
        for output in synthesis["outputs"]:
            output["intelligibility"] = asr_by_index[output["index"]]
        torch = runtime.torch
        cuda_evidence = {
            "torch_version": torch.__version__,
            "compiled_cuda": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "device_capability": list(torch.cuda.get_device_capability(0))
            if torch.cuda.is_available()
            else None,
            "arch_list": torch.cuda.get_arch_list() if torch.cuda.is_available() else [],
            "live_cuda_tensor_sum": float(
                torch.arange(32, device="cuda", dtype=torch.float32).sum().item()
            )
            if args.device == "cuda"
            else None,
        }
        watermarks_ok = all(
            output["watermark_decoded"] == WATERMARK_MESSAGE
            for output in synthesis["outputs"]
        )
        intelligibility_ok = all(
            output["intelligibility"]["wer"] <= 0.35
            for output in synthesis["outputs"]
        )
        clipping_ok = all(
            output["signal"]["clipped_fraction"] <= 0.001
            for output in synthesis["outputs"]
        )
        functional_pass = watermarks_ok and intelligibility_ok and clipping_ok
        report = {
            "schema": "openvoice-v2.qualification/v1",
            "generated_at": utc_now(),
            "device": args.device,
            "ok": functional_pass,
            "functional_verdict": "PASS" if functional_pass else "FAIL",
            "qualification_verdict": "PARTIAL" if functional_pass else "FAIL",
            "partial_reason": (
                "Objective functional evidence passed; independent human listening and real-person voice similarity were deliberately not claimed."
                if functional_pass
                else "One or more functional acceptance checks failed."
            ),
            "reference": reference_metadata,
            "synthesis": synthesis,
            "asr": asr,
            "acceptance": {
                "watermarks_decoded": watermarks_ok,
                "asr_wer_at_most_0_35": intelligibility_ok,
                "clipped_fraction_at_most_0_001": clipping_ok,
            },
            "speaker_similarity": {
                "recorded": True,
                "method": "OpenVoice converter embedding cosine per sample",
                "independent": False,
                "subjective_similarity_proven": False,
                "human_listener_review": "not performed",
            },
            "noise_and_artifacts": {
                "recorded_signal_measures": [
                    "peak_dbfs",
                    "rms_dbfs",
                    "low_energy_floor_dbfs",
                    "dc_offset",
                    "clipped_fraction",
                    "zero_crossing_rate",
                ],
                "human_listener_review": "not performed",
                "claim_boundary": "Signal measures detect gross faults but do not prove absence of audible artefacts.",
            },
            "cuda": cuda_evidence,
            "gpu_before": before_gpu,
            "gpu_monitor": monitor.summary() if monitor else None,
            "gpu_after": gpu_state(),
            "elapsed_seconds": time.perf_counter() - started,
            "output_retention": "Audio remains outside Git under the qualification directory.",
        }
    except Exception as exc:
        if monitor:
            monitor.__exit__(type(exc), exc, exc.__traceback__)
        report = {
            "schema": "openvoice-v2.qualification/v1",
            "generated_at": utc_now(),
            "device": args.device,
            "ok": False,
            "functional_verdict": "FAIL",
            "qualification_verdict": "FAIL",
            "error": "%s: %s" % (type(exc).__name__, exc),
            "gpu_before": before_gpu,
            "gpu_monitor": monitor.summary() if monitor else None,
            "gpu_after": gpu_state(),
            "elapsed_seconds": time.perf_counter() - started,
        }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report_path.chmod(0o600)
    print(json.dumps({"ok": report["ok"], "report": str(report_path)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
