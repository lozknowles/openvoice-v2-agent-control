"""Stable provider-neutral API and conservative automatic routing policy."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ProviderCapabilities:
    local: bool
    cloud: bool
    streaming: bool
    voice_cloning: bool
    zero_shot_cloning: bool
    multilingual: bool
    speed_control: bool
    emotion_style_control: bool
    pronunciation_control: bool
    offline_operation: bool
    installed_languages: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["installed_languages"] = list(self.installed_languages)
        value["notes"] = list(self.notes)
        return value


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    voice: str
    provider: str = "auto"
    speed: float = 1.0
    style: Optional[Mapping[str, Any]] = None
    output_format: str = "wav"
    language: str = "en-GB"
    output_filename: str = "speech"
    output_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("SPEECH_OUTPUT_ROOT", "/tmp/speech-synthesis-samples")
        )
    )
    consent_confirmed: bool = False
    consent_basis: str = ""
    allow_cloud: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text is required")
        if len(self.text) > 40_000:
            raise ValueError("text exceeds the neutral 40,000-character limit")
        if not isinstance(self.voice, str) or not self.voice.strip():
            raise ValueError("voice is required")
        if not 0.5 <= float(self.speed) <= 2.0:
            raise ValueError("speed must be between 0.5 and 2.0")
        if self.output_format not in {"wav", "mp3"}:
            raise ValueError("output_format must be wav or mp3")
        if self.style is not None:
            unknown = set(self.style) - {"emotion", "exaggeration"}
            if unknown:
                raise ValueError("unsupported neutral style keys: %s" % sorted(unknown))
        if not re.fullmatch(r"[a-z][a-z0-9-]*", self.provider):
            raise ValueError("provider name is invalid")


@dataclass(frozen=True)
class SynthesisResult:
    provider: str
    engine: str
    output_path: Path
    synthetic: bool
    time_to_first_audio_seconds: Optional[float]
    time_to_first_audio_kind: str
    total_latency_seconds: float
    real_time_factor: Optional[float]
    output_duration_seconds: Optional[float]
    output_bytes: int
    sample_rate: Optional[int]
    retries: int
    request_id: Optional[str]
    estimated_cloud_cost_usd: Optional[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["output_path"] = str(self.output_path)
        return value


def synthetic_filename(value: str, output_format: str) -> str:
    leaf = Path(str(value or "speech")).name
    stem = Path(leaf).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("._-")[:80]
    if not stem:
        stem = "speech"
    if not stem.endswith("_synthetic"):
        stem += "_synthetic"
    return "%s.%s" % (stem, output_format)


def output_path_for(request: SynthesisRequest) -> Path:
    root = Path(request.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    path = root / synthetic_filename(request.output_filename, request.output_format)
    if path.exists():
        raise FileExistsError("refusing to overwrite existing audio: %s" % path)
    return path


def provider_class(name: str):
    if name == "openvoice":
        from speech.providers.openvoice import OpenVoiceProvider

        return OpenVoiceProvider
    if name == "local":
        from speech.providers.local import KokoroLocalProvider

        return KokoroLocalProvider
    if name == "melotts":
        from speech.providers.melotts import MeloTTSProvider

        return MeloTTSProvider
    if name == "elevenlabs":
        from speech.providers.elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider
    raise ValueError("unknown speech provider: %s" % name)


def choose_provider(request: SynthesisRequest) -> str:
    if request.provider != "auto":
        return request.provider
    if Path(request.voice).expanduser().is_file():
        available, _ = provider_class("openvoice").availability()
        if available:
            return "openvoice"
    for name in ("local", "melotts"):
        available, _ = provider_class(name).availability()
        if available:
            return name
    if request.allow_cloud:
        available, _ = provider_class("elevenlabs").availability()
        if available:
            return "elevenlabs"
    raise RuntimeError(
        "no eligible local speech provider is available; cloud routing is never automatic without allow_cloud"
    )


def synthesize(
    text: str,
    voice: str,
    provider: str = "auto",
    speed: float = 1.0,
    style: Optional[Mapping[str, Any]] = None,
    output_format: str = "wav",
    **kwargs: Any,
) -> SynthesisResult:
    """Synthesize once through a selected adapter.

    Cloud use is fail-closed. A voice-reference path is routed locally to
    OpenVoice and still requires explicit consent fields.
    """

    request = SynthesisRequest(
        text=text,
        voice=voice,
        provider=provider,
        speed=speed,
        style=style,
        output_format=output_format,
        **kwargs,
    )
    selected = choose_provider(request)
    adapter_type = provider_class(selected)
    adapter = adapter_type()
    try:
        return adapter.synthesize(request, output_path_for(request))
    finally:
        adapter.close()
