"""Official HTTP streaming TTS adapter for ElevenLabs.

The adapter never creates or uploads a clone. It synthesizes only with an
existing, explicitly supplied voice ID and requires an explicit cloud opt-in.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from speech.audio import probe_audio
from speech.interface import ProviderCapabilities, SynthesisResult
from speech.providers.base import ProviderAdapter, ProviderUnavailable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ElevenLabsProvider(ProviderAdapter):
    name = "elevenlabs"
    engine = "ElevenLabs Text to Speech API"

    @classmethod
    def availability(cls) -> Tuple[bool, str]:
        if not os.environ.get("ELEVENLABS_API_KEY", "").strip():
            return False, "ELEVENLABS_API_KEY is absent"
        return True, "ElevenLabs API key is present in the process environment"

    def __init__(self) -> None:
        available, reason = self.availability()
        if not available:
            raise ProviderUnavailable(reason)
        self._api_key = os.environ["ELEVENLABS_API_KEY"].strip()
        self._api_base = os.environ.get(
            "ELEVENLABS_API_BASE", "https://api.elevenlabs.io"
        ).rstrip("/")
        self._model_id = os.environ.get(
            "ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"
        )
        self._timeout = float(os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "120"))
        self._max_retries = int(os.environ.get("ELEVENLABS_MAX_RETRIES", "2"))
        parsed = urllib.parse.urlparse(self._api_base)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("ElevenLabs API base must use HTTPS")

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            local=False,
            cloud=True,
            streaming=True,
            voice_cloning=True,
            zero_shot_cloning=False,
            multilingual=True,
            speed_control=True,
            emotion_style_control=True,
            pronunciation_control=True,
            offline_operation=False,
            notes=(
                "This adapter consumes existing voice IDs and never uploads reference audio.",
                "Instant and Professional Voice Clone creation are separate governed API actions.",
                "Streaming uses the official HTTP stream endpoint.",
            ),
        )

    @staticmethod
    def _pricing() -> Dict[str, Any]:
        path = REPOSITORY_ROOT / "speech/benchmarks/elevenlabs-pricing-2026-08-26.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _estimated_cost(self, characters: int) -> Optional[float]:
        rates = self._pricing().get("model_rates_usd_per_1000_characters", {})
        rate = rates.get(self._model_id)
        if rate is None:
            return None
        return round(characters * float(rate) / 1000.0, 8)

    @staticmethod
    def _output_api_format(output_format: str) -> Tuple[str, Optional[int]]:
        if output_format == "wav":
            return "pcm_24000", 24000
        if output_format == "mp3":
            return "mp3_44100_128", None
        raise ValueError("ElevenLabs adapter supports wav or mp3")

    def _request(self, request, api_format: str):
        voice = request.voice.strip()
        if Path(voice).expanduser().exists():
            raise ValueError(
                "ElevenLabs requires an existing voice ID; this adapter never uploads a reference"
            )
        if not request.allow_cloud:
            raise PermissionError("ElevenLabs requires explicit allow_cloud=True")
        if request.consent_confirmed is not True or not request.consent_basis.strip():
            raise PermissionError("voice-use permission and consent basis are required")
        if not 0.7 <= request.speed <= 1.2:
            raise ValueError("ElevenLabs speed must be between 0.7 and 1.2")
        style = dict(request.style or {})
        if style.get("emotion"):
            raise ValueError(
                "neutral emotion labels are not mapped automatically to ElevenLabs prompts"
            )
        voice_settings: Dict[str, Any] = {"speed": request.speed}
        if style.get("exaggeration") is not None:
            value = float(style["exaggeration"])
            if not 0.0 <= value <= 1.0:
                raise ValueError("style exaggeration must be between 0 and 1")
            voice_settings["style"] = value
        payload: Dict[str, Any] = {
            "text": request.text,
            "model_id": self._model_id,
            "voice_settings": voice_settings,
        }
        query = urllib.parse.urlencode({"output_format": api_format})
        url = "%s/v1/text-to-speech/%s/stream?%s" % (
            self._api_base,
            urllib.parse.quote(voice, safe=""),
            query,
        )
        return urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "audio/mpeg, audio/wav, application/octet-stream",
                "Content-Type": "application/json",
                "xi-api-key": self._api_key,
                "User-Agent": "agent-control-speech-qualification/1.0",
            },
        )

    def synthesize(self, request, output_path: Path) -> SynthesisResult:
        if output_path.exists() or output_path.with_suffix(".json").exists():
            raise FileExistsError("refusing to overwrite existing audio")
        output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        api_format, raw_sample_rate = self._output_api_format(request.output_format)
        http_request = self._request(request, api_format)
        temporary_fd, temporary_name = tempfile.mkstemp(
            prefix="elevenlabs-", suffix=".partial", dir=str(output_path.parent)
        )
        os.close(temporary_fd)
        temporary_path = Path(temporary_name)
        retries = 0
        first_audio: Optional[float] = None
        request_id: Optional[str] = None
        started = time.perf_counter()
        try:
            while True:
                try:
                    with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
                        request_id = (
                            response.headers.get("request-id")
                            or response.headers.get("x-request-id")
                        )
                        with temporary_path.open("wb") as handle:
                            read_chunk = getattr(response, "read1", response.read)
                            while True:
                                chunk = read_chunk(64 * 1024)
                                if not chunk:
                                    break
                                if first_audio is None:
                                    first_audio = time.perf_counter() - started
                                handle.write(chunk)
                    break
                except urllib.error.HTTPError as exc:
                    retryable = exc.code == 429 or 500 <= exc.code <= 599
                    if not retryable or retries >= self._max_retries:
                        raise RuntimeError("ElevenLabs HTTP %s" % exc.code) from exc
                except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                    if retries >= self._max_retries:
                        raise RuntimeError("ElevenLabs network request failed") from exc
                retries += 1
                time.sleep(min(2.0, 0.5 * (2 ** (retries - 1))))

            if first_audio is None or temporary_path.stat().st_size == 0:
                raise RuntimeError("ElevenLabs returned no audio bytes")
            if raw_sample_rate is not None:
                wav_fd, wav_name = tempfile.mkstemp(
                    prefix="elevenlabs-wav-", suffix=".partial", dir=str(output_path.parent)
                )
                os.close(wav_fd)
                wav_path = Path(wav_name)
                try:
                    with wave.open(str(wav_path), "wb") as handle:
                        handle.setnchannels(1)
                        handle.setsampwidth(2)
                        handle.setframerate(raw_sample_rate)
                        handle.writeframes(temporary_path.read_bytes())
                    os.replace(str(wav_path), str(output_path))
                finally:
                    if wav_path.exists():
                        wav_path.unlink()
            else:
                os.replace(str(temporary_path), str(output_path))
            output_path.chmod(0o600)
            total = time.perf_counter() - started
            audio = probe_audio(output_path)
            duration = audio.get("duration_seconds")
            estimate = self._estimated_cost(len(request.text))
            sidecar = {
                "schema": "speech-synthesis.synthetic-output/v1",
                "provider": "elevenlabs",
                "engine": self.engine,
                "synthetic": True,
                "model_id": self._model_id,
                "voice_id": request.voice,
                "consent_confirmed": True,
                "consent_basis": request.consent_basis,
                "characters": len(request.text),
                "estimated_cloud_cost_usd": estimate,
                "cost_is_estimate": True,
                "request_id": request_id,
            }
            sidecar_path = output_path.with_suffix(".json")
            sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
            sidecar_path.chmod(0o600)
            return SynthesisResult(
                provider=self.name,
                engine=self.engine,
                output_path=output_path,
                synthetic=True,
                time_to_first_audio_seconds=first_audio,
                time_to_first_audio_kind="first-network-audio-byte",
                total_latency_seconds=total,
                real_time_factor=(total / duration) if duration else None,
                output_duration_seconds=duration,
                output_bytes=audio["bytes"],
                sample_rate=audio.get("sample_rate"),
                retries=retries,
                request_id=request_id,
                estimated_cloud_cost_usd=estimate,
                metadata={
                    "audio": audio,
                    "model_id": self._model_id,
                    "api_output_format": api_format,
                    "cost_is_estimate": True,
                    "pricing_snapshot": self._pricing().get("as_of"),
                },
            )
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
