"""Small dependency-free audio inspection helpers used by every provider."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import wave
from array import array
from pathlib import Path
from typing import Any, Dict, Optional


def probe_audio(path: Path) -> Dict[str, Any]:
    """Return objective container metadata without listening or quality claims."""

    path = Path(path).resolve()
    result: Dict[str, Any] = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "duration_seconds": None,
        "sample_rate": None,
        "channels": None,
        "codec": None,
    }
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            raw = handle.readframes(frames) if sample_width == 2 else b""
            result.update(
                {
                    "duration_seconds": frames / rate if rate else None,
                    "sample_rate": rate,
                    "channels": channels,
                    "codec": "pcm",
                }
            )
            if raw:
                samples = array("h")
                samples.frombytes(raw)
                if sys.byteorder == "big":
                    samples.byteswap()
                values = [value / 32768.0 for value in samples]
                absolute = [abs(value) for value in values]
                peak = max(absolute) if absolute else 0.0
                rms = (
                    math.sqrt(sum(value * value for value in values) / len(values))
                    if values
                    else 0.0
                )
                frame_samples = max(1, int(rate * channels * 0.02))
                frame_rms = []
                for start in range(0, len(values), frame_samples):
                    frame = values[start : start + frame_samples]
                    if frame:
                        frame_rms.append(
                            math.sqrt(
                                sum(value * value for value in frame) / len(frame)
                            )
                        )
                ordered = sorted(frame_rms)
                floor = ordered[int((len(ordered) - 1) * 0.10)] if ordered else 0.0
                signs = [value < 0 for value in values]
                crossings = sum(
                    1 for index in range(1, len(signs)) if signs[index] != signs[index - 1]
                )
                result["signal"] = {
                    "peak_dbfs": 20.0 * math.log10(max(peak, 1e-12)),
                    "rms_dbfs": 20.0 * math.log10(max(rms, 1e-12)),
                    "low_energy_floor_dbfs": 20.0 * math.log10(max(floor, 1e-12)),
                    "dc_offset": sum(values) / len(values) if values else 0.0,
                    "clipped_fraction": (
                        sum(1 for value in absolute if value >= 0.999) / len(absolute)
                        if absolute
                        else 0.0
                    ),
                    "zero_crossing_rate": crossings / max(1, len(values) - 1),
                    "claim_boundary": "Gross signal measures do not prove absence of audible noise or artefacts.",
                }
            return result
    except (wave.Error, EOFError):
        pass

    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels:format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        result["probe_error"] = completed.stderr.strip() or "ffprobe failed"
        return result
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or [{}]
    stream = streams[0]
    duration: Optional[float]
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    result.update(
        {
            "duration_seconds": duration,
            "sample_rate": int(stream["sample_rate"])
            if str(stream.get("sample_rate", "")).isdigit()
            else None,
            "channels": stream.get("channels"),
            "codec": stream.get("codec_name"),
        }
    )
    return result
