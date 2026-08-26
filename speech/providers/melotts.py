"""Adapter for the MeloTTS base engine already installed with OpenVoice."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from speech.interface import ProviderCapabilities
from speech.providers.base import JsonWorkerProvider


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class MeloTTSProvider(JsonWorkerProvider):
    name = "melotts"
    engine = "MyShell MeloTTS"

    @classmethod
    def availability(cls) -> Tuple[bool, str]:
        python = Path(os.environ.get("SPEECH_MELO_PYTHON", "/fast/venvs/openvoice-v2-py39/bin/python"))
        model_root = Path(os.environ.get("SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2"))
        required = [
            python,
            model_root / "melotts-english/config.json",
            model_root / "melotts-english/checkpoint.pth",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            return False, "MeloTTS installation is incomplete: %s" % ", ".join(missing)
        return True, "MeloTTS English model is present in the OpenVoice environment"

    def __init__(self) -> None:
        python = os.environ.get("SPEECH_MELO_PYTHON", "/fast/venvs/openvoice-v2-py39/bin/python")
        environment = {
            "SPEECH_REPOSITORY_ROOT": str(REPOSITORY_ROOT),
            "SPEECH_OPENVOICE_MODEL_ROOT": os.environ.get(
                "SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2"
            ),
            "SPEECH_MELO_DEVICE": os.environ.get("SPEECH_MELO_DEVICE", "cpu"),
            "NLTK_DATA": str(
                Path(
                    os.environ.get(
                        "SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2"
                    )
                )
                / "nltk-data"
            ),
            "HF_HOME": str(
                Path(
                    os.environ.get(
                        "SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2"
                    )
                )
                / "hf-cache"
            ),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "SPEECH_WORKER_MAX_REQUESTS": os.environ.get(
                "SPEECH_MELO_MAX_REQUESTS", "3"
            ),
        }
        super().__init__(
            [python, str(REPOSITORY_ROOT / "speech/providers/workers/melotts_worker.py")],
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
            installed_languages=("en-GB", "en-US", "en-AU", "en-IN", "en"),
            notes=("Qualified installation contains only the pinned English checkpoint.",),
        )
