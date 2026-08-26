"""Adapter for the already-installed local Kokoro ONNX engine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from speech.interface import ProviderCapabilities
from speech.providers.base import JsonWorkerProvider


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class KokoroLocalProvider(JsonWorkerProvider):
    name = "local"
    engine = "Kokoro ONNX"

    @classmethod
    def availability(cls) -> Tuple[bool, str]:
        python = Path(
            os.environ.get(
                "SPEECH_KOKORO_PYTHON",
                "/fast/work/cartoon-collingham-gpu-tts/.venv-gpu18/bin/python",
            )
        )
        model = Path(
            os.environ.get(
                "SPEECH_KOKORO_MODEL",
                "/fast/work/cartoon-collingham-gpu-tts/models/kokoro/kokoro-v1.0.int8.onnx",
            )
        )
        voices = Path(
            os.environ.get(
                "SPEECH_KOKORO_VOICES",
                "/fast/work/cartoon-collingham-gpu-tts/models/kokoro/voices-v1.0.bin",
            )
        )
        missing = [str(path) for path in (python, model, voices) if not path.exists()]
        if missing:
            return False, "Kokoro installation is incomplete: %s" % ", ".join(missing)
        return True, "existing Kokoro ONNX model and environment are present"

    def __init__(self) -> None:
        python = os.environ.get(
            "SPEECH_KOKORO_PYTHON",
            "/fast/work/cartoon-collingham-gpu-tts/.venv-gpu18/bin/python",
        )
        nvidia_root = Path(python).expanduser().absolute().parents[1] / "lib/python3.12/site-packages/nvidia"
        existing_cuda_libraries = ":".join(
            str(nvidia_root / relative)
            for relative in (
                "cudnn/lib",
                "cublas/lib",
                "cuda_runtime/lib",
                "cuda_nvrtc/lib",
                "cufft/lib",
            )
        )
        environment = {
            "SPEECH_KOKORO_MODEL": os.environ.get(
                "SPEECH_KOKORO_MODEL",
                "/fast/work/cartoon-collingham-gpu-tts/models/kokoro/kokoro-v1.0.int8.onnx",
            ),
            "SPEECH_KOKORO_VOICES": os.environ.get(
                "SPEECH_KOKORO_VOICES",
                "/fast/work/cartoon-collingham-gpu-tts/models/kokoro/voices-v1.0.bin",
            ),
            "SPEECH_KOKORO_DEVICE": os.environ.get("SPEECH_KOKORO_DEVICE", "cpu"),
            "LD_LIBRARY_PATH": os.environ.get(
                "SPEECH_KOKORO_LD_LIBRARY_PATH",
                existing_cuda_libraries + ":/usr/lib/x86_64-linux-gnu",
            ),
        }
        super().__init__(
            [python, str(REPOSITORY_ROOT / "speech/providers/workers/kokoro_worker.py")],
            environment,
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            local=True,
            cloud=False,
            streaming=False,
            voice_cloning=False,
            zero_shot_cloning=False,
            multilingual=False,
            speed_control=True,
            emotion_style_control=False,
            pronunciation_control=False,
            offline_operation=True,
            installed_languages=("en-GB", "en-US"),
            notes=(
                "The installed voice bank contains multiple voices; en-GB bm_george is the governed default.",
                "Additional upstream languages are not marked available until separately qualified.",
                "This adapter loads a separate one-shot worker and does not modify or restart the protected Kokoro service.",
            ),
        )
