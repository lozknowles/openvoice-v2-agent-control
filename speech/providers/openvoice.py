"""Adapter for the pinned isolated OpenVoice V2 installation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from speech.interface import ProviderCapabilities
from speech.providers.base import JsonWorkerProvider


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class OpenVoiceProvider(JsonWorkerProvider):
    name = "openvoice"
    engine = "MyShell OpenVoice V2 + MeloTTS"

    @classmethod
    def availability(cls) -> Tuple[bool, str]:
        python = Path(os.environ.get("SPEECH_OPENVOICE_PYTHON", "/fast/venvs/openvoice-v2-py39/bin/python"))
        model_root = Path(os.environ.get("SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2"))
        required = [
            python,
            model_root / "checkpoints_v2/converter/checkpoint.pth",
            model_root / "melotts-english/checkpoint.pth",
            REPOSITORY_ROOT / "scripts/openvoice_v2_runtime.py",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            return False, "OpenVoice installation is incomplete: %s" % ", ".join(missing)
        return True, "pinned OpenVoice V2 environment is present"

    def __init__(self) -> None:
        python = os.environ.get(
            "SPEECH_OPENVOICE_PYTHON", "/fast/venvs/openvoice-v2-py39/bin/python"
        )
        environment = {
            "SPEECH_REPOSITORY_ROOT": str(REPOSITORY_ROOT),
            "SPEECH_OPENVOICE_MODEL_ROOT": os.environ.get(
                "SPEECH_OPENVOICE_MODEL_ROOT", "/fast/models/openvoice-v2"
            ),
            "SPEECH_OPENVOICE_DEVICE": os.environ.get("SPEECH_OPENVOICE_DEVICE", "cpu"),
            "SPEECH_WORKER_MAX_REQUESTS": os.environ.get(
                "SPEECH_OPENVOICE_MAX_REQUESTS", "3"
            ),
        }
        super().__init__(
            [python, str(REPOSITORY_ROOT / "speech/providers/workers/openvoice_worker.py")],
            environment,
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            local=True,
            cloud=False,
            streaming=False,
            voice_cloning=True,
            zero_shot_cloning=True,
            multilingual=False,
            speed_control=True,
            emotion_style_control=False,
            pronunciation_control=False,
            offline_operation=True,
            installed_languages=("en-GB", "en-US", "en-AU", "en-IN", "en"),
            notes=(
                "Installed qualification scope is English only.",
                "Every clone requires an authorised reference and explicit consent.",
                "Upstream @MyShell watermarking remains enabled.",
            ),
        )
