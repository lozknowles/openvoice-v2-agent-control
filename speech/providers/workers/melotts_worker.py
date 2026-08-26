#!/usr/bin/env python3
"""Persistent MeloTTS worker inside the pinned OpenVoice Python environment."""

from __future__ import annotations

import contextlib
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path


def emit(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    model_root = Path(os.environ.get("SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2"))
    device = os.environ.get("SPEECH_MELO_DEVICE", "cpu")
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import numpy as np
            import torch
            from melo.api import TTS

            torch.set_num_threads(2)
            random.seed(20260826)
            np.random.seed(20260826)
            torch.manual_seed(20260826)
            if device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but PyTorch cannot use it")
            melo_root = model_root / "melotts-english"
            tts = TTS(
                language="EN",
                device=device,
                config_path=str(melo_root / "config.json"),
                ckpt_path=str(melo_root / "checkpoint.pth"),
            )
        emit(
            {
                "type": "ready",
                "ok": True,
                "provider": "melotts",
                "engine": "MyShell MeloTTS",
                "device": device,
                "worker_initialization_seconds": time.perf_counter() - started,
            }
        )
    except Exception as exc:
        emit({"type": "ready", "ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
        return 1

    max_requests = max(1, int(os.environ.get("SPEECH_WORKER_MAX_REQUESTS", "3")))
    successful_requests = 0
    for line in sys.stdin:
        temp_dir = None
        try:
            request = json.loads(line)
            if request.get("type") == "shutdown":
                return 0
            if request.get("type") != "synthesize":
                raise ValueError("unknown worker request")
            if request.get("output_format") != "wav":
                raise ValueError("MeloTTS supports WAV output in this installation")
            if request.get("style"):
                raise ValueError("MeloTTS has no qualified style control")
            speed = float(request.get("speed", 1.0))
            if not 0.7 <= speed <= 1.3:
                raise ValueError("MeloTTS speed must be between 0.7 and 1.3")
            voice = request.get("voice") or "EN-BR"
            if voice not in tts.hps.data.spk2id:
                raise ValueError("unknown installed MeloTTS voice: %s" % voice)
            output_path = Path(request["output_path"]).resolve()
            sidecar_path = output_path.with_suffix(".json")
            if output_path.exists() or sidecar_path.exists():
                raise FileExistsError("refusing to overwrite an existing output")
            output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp_dir = Path(tempfile.mkdtemp(prefix="melotts-", dir=str(output_path.parent)))
            temporary = temp_dir / "output.wav"
            generated_started = time.perf_counter()
            with contextlib.redirect_stdout(sys.stderr):
                tts.tts_to_file(
                    request["text"],
                    tts.hps.data.spk2id[voice],
                    str(temporary),
                    speed=speed,
                    quiet=True,
                )
            generation_seconds = time.perf_counter() - generated_started
            os.replace(str(temporary), str(output_path))
            temp_dir.rmdir()
            sidecar_path.write_text(
                json.dumps(
                    {
                        "schema": "speech-synthesis.synthetic-output/v1",
                        "provider": "melotts",
                        "engine": "MyShell MeloTTS",
                        "synthetic": True,
                        "voice": voice,
                        "language": request.get("language") or "en-GB",
                        "speed": speed,
                        "watermark": "not provided by MeloTTS base synthesis",
                        "consent_basis": request.get("consent_basis") or "pinned licensed model voice",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            output_path.chmod(0o600)
            sidecar_path.chmod(0o600)
            successful_requests += 1
            recycle = successful_requests >= max_requests
            emit(
                {
                    "ok": True,
                    "output_path": str(output_path),
                    "device": device,
                    "provider_generation_seconds": generation_seconds,
                    "watermark": "not provided by MeloTTS base synthesis",
                    "worker_successful_requests": successful_requests,
                    "recycle_after_response": recycle,
                }
            )
            if recycle:
                return 0
        except Exception as exc:
            if temp_dir and temp_dir.exists():
                import shutil

                shutil.rmtree(str(temp_dir), ignore_errors=True)
            emit({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
