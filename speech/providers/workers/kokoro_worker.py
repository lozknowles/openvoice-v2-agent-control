#!/usr/bin/env python3
"""Persistent Kokoro ONNX worker; never touches the protected resident service."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    model = Path(os.environ["SPEECH_KOKORO_MODEL"]).resolve()
    voices = Path(os.environ["SPEECH_KOKORO_VOICES"]).resolve()
    device = os.environ.get("SPEECH_KOKORO_DEVICE", "cpu")
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import onnxruntime as ort
            import soundfile as sf
            from kokoro_onnx import Kokoro

            available = ort.get_available_providers()
            requested = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if device == "cuda"
                else ["CPUExecutionProvider"]
            )
            providers = [provider for provider in requested if provider in available]
            if not providers:
                raise RuntimeError("requested ONNX provider is unavailable")
            options = ort.SessionOptions()
            options.intra_op_num_threads = max(1, min(os.cpu_count() or 1, 4))
            session = ort.InferenceSession(
                str(model), providers=providers, sess_options=options
            )
            kokoro = Kokoro.from_session(session, str(voices))
            active = session.get_providers()
        emit(
            {
                "type": "ready",
                "ok": True,
                "provider": "local",
                "engine": "Kokoro ONNX",
                "model": model.name,
                "requested_device": device,
                "active_providers": active,
                "worker_initialization_seconds": time.perf_counter() - started,
            }
        )
    except Exception as exc:
        emit({"type": "ready", "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
        return 1

    for line in sys.stdin:
        temporary = None
        try:
            request = json.loads(line)
            if request.get("type") == "shutdown":
                return 0
            if request.get("type") != "synthesize":
                raise ValueError("unknown worker request")
            if request.get("output_format") != "wav":
                raise ValueError("Kokoro supports WAV output in this installation")
            if request.get("style"):
                raise ValueError("Kokoro has no qualified style control")
            speed = float(request.get("speed", 1.0))
            if not 0.7 <= speed <= 1.35:
                raise ValueError("Kokoro speed must be between 0.7 and 1.35")
            output_path = Path(request["output_path"]).resolve()
            sidecar_path = output_path.with_suffix(".json")
            if output_path.exists() or sidecar_path.exists():
                raise FileExistsError("refusing to overwrite an existing output")
            output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp_dir = Path(tempfile.mkdtemp(prefix="kokoro-", dir=str(output_path.parent)))
            temporary = temp_dir / "output.wav"
            generated_started = time.perf_counter()
            language = {
                "en-GB": "en-gb",
                "en-US": "en-us",
            }.get(request.get("language"), request.get("language") or "en-gb")
            with contextlib.redirect_stdout(sys.stderr):
                samples, sample_rate = kokoro.create(
                    request["text"],
                    voice=request.get("voice") or "bm_george",
                    speed=speed,
                    lang=language,
                )
                sf.write(str(temporary), samples, sample_rate, format="WAV", subtype="PCM_16")
            generation_seconds = time.perf_counter() - generated_started
            os.replace(str(temporary), str(output_path))
            temp_dir.rmdir()
            sidecar = {
                "schema": "speech-synthesis.synthetic-output/v1",
                "provider": "local",
                "engine": "Kokoro ONNX",
                "synthetic": True,
                "voice": request.get("voice") or "bm_george",
                "language": language,
                "speed": speed,
                "watermark": "not provided by Kokoro ONNX",
                "consent_basis": request.get("consent_basis") or "pinned licensed model voice",
            }
            sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
            output_path.chmod(0o600)
            sidecar_path.chmod(0o600)
            emit(
                {
                    "ok": True,
                    "output_path": str(output_path),
                    "device": "cuda" if "CUDAExecutionProvider" in active else "cpu",
                    "active_providers": active,
                    "provider_generation_seconds": generation_seconds,
                    "sample_rate": int(sample_rate),
                    "watermark": "not provided by Kokoro ONNX",
                }
            )
        except Exception as exc:
            if temporary and temporary.exists():
                temporary.unlink()
                try:
                    temporary.parent.rmdir()
                except OSError:
                    pass
            emit({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
