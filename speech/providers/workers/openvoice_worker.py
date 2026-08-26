#!/usr/bin/env python3
"""Persistent OpenVoice worker running only inside the pinned Python 3.9 env."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    repository = Path(os.environ["SPEECH_REPOSITORY_ROOT"]).resolve()
    sys.path.insert(0, str(repository / "scripts"))
    device = os.environ.get("SPEECH_OPENVOICE_DEVICE", "cpu")
    model_root = os.environ.get("SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2")
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from openvoice_v2_runtime import OpenVoiceV2Runtime

            runtime = OpenVoiceV2Runtime(
                device=device, language="British English", model_root=model_root
            )
        emit(
            {
                "type": "ready",
                "ok": True,
                "provider": "openvoice",
                "engine": "MyShell OpenVoice V2 + MeloTTS",
                "device": device,
                "model_load_seconds": runtime.model_load_seconds,
                "worker_initialization_seconds": time.perf_counter() - started,
            }
        )
    except Exception as exc:
        emit({"type": "ready", "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
        return 1

    max_requests = max(1, int(os.environ.get("SPEECH_WORKER_MAX_REQUESTS", "3")))
    successful_requests = 0
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("type") == "shutdown":
                return 0
            if request.get("type") != "synthesize":
                raise ValueError("unknown worker request")
            if request.get("output_format") != "wav":
                raise ValueError("OpenVoice supports WAV output in this installation")
            if request.get("style"):
                raise ValueError("OpenVoice has no qualified style control")
            speed = float(request.get("speed", 1.0))
            if not 0.7 <= speed <= 1.3:
                raise ValueError("OpenVoice speed must be between 0.7 and 1.3")
            output_path = Path(request["output_path"]).resolve()
            if output_path.exists() or output_path.with_suffix(".json").exists():
                raise FileExistsError("refusing to overwrite an existing output")
            output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            prefix = output_path.stem
            if prefix.endswith("_synthetic"):
                prefix = prefix[: -len("_synthetic")]
            with contextlib.redirect_stdout(sys.stderr):
                result = runtime.synthesise_many(
                    reference_path=request["voice"],
                    texts=[request["text"]],
                    output_dir=output_path.parent,
                    filename_prefix=prefix,
                    consent_confirmed=request.get("consent_confirmed") is True,
                    consent_basis=request.get("consent_basis", ""),
                    speed=speed,
                )
            generated = result["outputs"][0]
            generated_path = output_path.parent / generated["filename"]
            generated_sidecar = generated_path.with_suffix(".json")
            sidecar = json.loads(generated_sidecar.read_text(encoding="utf-8"))
            sidecar["filename"] = output_path.name
            sidecar["speed"] = speed
            generated["filename"] = output_path.name
            generated["speed"] = speed
            os.replace(str(generated_path), str(output_path))
            output_path.with_suffix(".json").write_text(
                json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
            )
            generated_sidecar.unlink()
            output_path.chmod(0o600)
            output_path.with_suffix(".json").chmod(0o600)
            successful_requests += 1
            recycle = successful_requests >= max_requests
            emit(
                {
                    "ok": True,
                    "output_path": str(output_path),
                    "device": device,
                    "model_load_seconds": result["model_load_seconds"],
                    "embedding_extraction_seconds": result["embedding_extraction_seconds"],
                    "provider_generation_seconds": generated["generation_seconds"],
                    "watermark_requested": generated["watermark_requested"],
                    "watermark_decoded": generated["watermark_decoded"],
                    "speaker_similarity_proxy": generated["speaker_similarity_proxy"],
                    "worker_successful_requests": successful_requests,
                    "recycle_after_response": recycle,
                }
            )
            if recycle:
                return 0
        except Exception as exc:
            emit({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
