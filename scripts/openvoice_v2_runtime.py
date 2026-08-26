#!/usr/bin/env python3
"""Consent-gated OpenVoice V2 runtime with no persistent speaker embeddings."""

import hashlib
import ipaddress
import json
import math
import os
import random
import re
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np


WATERMARK_MESSAGE = "@MyShell"
SUPPORTED_LANGUAGES = {
    "British English": {"melo_language": "EN", "speaker": "EN-BR", "source_se": "en-br.pth"},
    "American English": {"melo_language": "EN", "speaker": "EN-US", "source_se": "en-us.pth"},
    "Australian English": {"melo_language": "EN", "speaker": "EN-AU", "source_se": "en-au.pth"},
    "Indian English": {"melo_language": "EN", "speaker": "EN_INDIA", "source_se": "en-india.pth"},
    "Default English": {"melo_language": "EN", "speaker": "EN-Default", "source_se": "en-default.pth"},
}
ALLOWED_REFERENCE_SUFFIXES = {".wav", ".mp3"}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_bind_host(host):
    if host in {"localhost", "127.0.0.1", "::1"}:
        return host
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("Bind host must be loopback or a literal Tailscale address") from exc
    if address.version == 4 and address in ipaddress.ip_network("100.64.0.0/10"):
        return host
    raise ValueError("Public and ordinary LAN binds are prohibited; use loopback or Tailscale")


def synthetic_output_name(value):
    leaf = Path(str(value or "openvoice-output")).name
    stem = Path(leaf).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("._-")[:64]
    if not stem:
        stem = "openvoice-output"
    if not stem.endswith("_synthetic"):
        stem += "_synthetic"
    return stem + ".wav"


def signal_metrics(path):
    import soundfile as sf

    audio, sample_rate = sf.read(str(path), always_2d=False)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float64)
    absolute = np.abs(audio)
    peak = float(absolute.max()) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    frame_size = max(1, int(sample_rate * 0.02))
    frame_rms = []
    for start in range(0, len(audio), frame_size):
        frame = audio[start : start + frame_size]
        if frame.size:
            frame_rms.append(float(np.sqrt(np.mean(np.square(frame)))))
    floor = float(np.percentile(frame_rms, 10)) if frame_rms else 0.0
    zcr = float(np.mean(np.diff(np.signbit(audio)) != 0)) if len(audio) > 1 else 0.0
    return {
        "sample_rate": int(sample_rate),
        "duration_seconds": float(len(audio) / sample_rate) if sample_rate else 0.0,
        "channels": 1,
        "peak_dbfs": 20.0 * math.log10(max(peak, 1e-12)),
        "rms_dbfs": 20.0 * math.log10(max(rms, 1e-12)),
        "low_energy_floor_dbfs": 20.0 * math.log10(max(floor, 1e-12)),
        "dc_offset": float(np.mean(audio)) if audio.size else 0.0,
        "clipped_fraction": float(np.mean(absolute >= 0.999)) if audio.size else 0.0,
        "zero_crossing_rate": zcr,
    }


def prepare_environment(model_root):
    model_root = Path(model_root).resolve()
    os.environ.setdefault("HF_HOME", str(model_root / "hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("NLTK_DATA", str(model_root / "nltk-data"))
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")


class OpenVoiceV2Runtime:
    def __init__(self, device, language="British English", model_root="/fast/models/openvoice-v2"):
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError("Unsupported installed language: %s" % language)
        if device not in {"cpu", "cuda"}:
            raise ValueError("Device must be cpu or cuda")
        self.device = device
        self.language = language
        self.model_root = Path(model_root).resolve()
        prepare_environment(self.model_root)
        started = time.perf_counter()
        import torch
        from melo.api import TTS
        from openvoice.api import ToneColorConverter

        torch.set_num_threads(2)
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but PyTorch cannot use it")
        random.seed(20260826)
        np.random.seed(20260826)
        torch.manual_seed(20260826)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(20260826)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        self.torch = torch
        converter_root = self.model_root / "checkpoints_v2/converter"
        self.converter = ToneColorConverter(
            str(converter_root / "config.json"),
            device=device,
        )
        self.converter.load_ckpt(str(converter_root / "checkpoint.pth"))
        melo_root = self.model_root / "melotts-english"
        mapping = SUPPORTED_LANGUAGES[language]
        self.tts = TTS(
            language=mapping["melo_language"],
            device=device,
            config_path=str(melo_root / "config.json"),
            ckpt_path=str(melo_root / "checkpoint.pth"),
        )
        self.mapping = mapping
        self.source_se = torch.load(
            str(self.model_root / "checkpoints_v2/base_speakers/ses" / mapping["source_se"]),
            map_location=device,
        )
        self.model_load_seconds = time.perf_counter() - started

    def generate_authorised_fixture(self, output_path):
        text = (
            "This is an authorised synthetic British English reference voice, "
            "created only for local OpenVoice qualification. The recording has "
            "one speaker, no music, and no background sound."
        )
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._seed(100)
        speaker_id = self.tts.hps.data.spk2id["EN-BR"]
        self.tts.tts_to_file(text, speaker_id, str(output_path), speed=1.0, quiet=True)
        output_path.chmod(0o600)
        metadata = {
            "schema": "openvoice-v2.authorised-synthetic-reference/v1",
            "synthetic": True,
            "human_identity_claimed": False,
            "generator": "MeloTTS English EN-BR",
            "consent_basis": "authorised synthetic MIT-licensed qualification fixture",
            "text": text,
            "sha256": sha256_file(output_path),
            "signal": signal_metrics(output_path),
        }
        output_path.with_suffix(".json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        output_path.with_suffix(".json").chmod(0o600)
        return metadata

    def _seed(self, offset):
        seed = 20260826 + int(offset)
        random.seed(seed)
        np.random.seed(seed % (2**32 - 1))
        self.torch.manual_seed(seed)
        if self.torch.cuda.is_available():
            self.torch.cuda.manual_seed_all(seed)

    def _prepare_reference(self, reference_path, work_root):
        from pydub import AudioSegment
        from pydub.silence import detect_nonsilent

        reference = Path(reference_path).resolve()
        if not reference.is_file() or reference.suffix.lower() not in ALLOWED_REFERENCE_SUFFIXES:
            raise ValueError("Reference must be an existing WAV or MP3")
        if reference.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("Reference exceeds the 50 MiB limit")
        audio = AudioSegment.from_file(str(reference)).set_channels(1).set_frame_rate(22050)
        if len(audio) < 2000 or len(audio) > 60000:
            raise ValueError("Reference speech must be between 2 and 60 seconds")
        threshold = max(-45.0, audio.dBFS - 18.0)
        spans = detect_nonsilent(audio, min_silence_len=250, silence_thresh=threshold)
        if spans:
            audio = audio[max(0, spans[0][0] - 100) : min(len(audio), spans[-1][1] + 100)]
        if audio.max_dBFS > -3.0:
            audio = audio.apply_gain(-3.0 - audio.max_dBFS)
        prepared = Path(work_root) / "authorised-reference-normalised.wav"
        audio.export(str(prepared), format="wav")
        prepared.chmod(0o600)
        return prepared

    def extract_target_embedding(self, reference_path, work_root):
        started = time.perf_counter()
        prepared = self._prepare_reference(reference_path, work_root)
        target = self.converter.extract_se([str(prepared)])
        return target, prepared, time.perf_counter() - started

    def synthesise_many(
        self,
        reference_path,
        texts,
        output_dir,
        filename_prefix,
        consent_confirmed,
        consent_basis,
        speed=1.0,
    ):
        if consent_confirmed is not True:
            raise PermissionError("Explicit voice permission confirmation is required")
        if not str(consent_basis).strip():
            raise PermissionError("Consent basis must be recorded")
        speed = float(speed)
        if speed < 0.7 or speed > 1.3:
            raise ValueError("Speed must be between 0.7 and 1.3")
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        work_root = Path(tempfile.mkdtemp(prefix="openvoice-v2-", dir=str(output_dir.parent)))
        work_root.chmod(0o700)
        reference_hash = sha256_file(reference_path)
        results = []
        try:
            target_se, prepared, extraction_seconds = self.extract_target_embedding(
                reference_path, work_root
            )
            speaker_id = self.tts.hps.data.spk2id[self.mapping["speaker"]]
            for index, text in enumerate(texts, start=1):
                clean_text = str(text).strip()
                if len(clean_text) < 2 or len(clean_text) > 500:
                    raise ValueError("Text must be between 2 and 500 characters")
                self._seed(index)
                source_path = work_root / ("base-%02d.wav" % index)
                base_started = time.perf_counter()
                self.tts.tts_to_file(
                    clean_text,
                    speaker_id,
                    str(source_path),
                    speed=speed,
                    quiet=True,
                )
                base_seconds = time.perf_counter() - base_started
                filename = synthetic_output_name("%s-%02d" % (filename_prefix, index))
                output_path = output_dir / filename
                convert_started = time.perf_counter()
                self.converter.convert(
                    audio_src_path=str(source_path),
                    src_se=self.source_se,
                    tgt_se=target_se,
                    output_path=str(output_path),
                    message=WATERMARK_MESSAGE,
                )
                conversion_seconds = time.perf_counter() - convert_started
                output_path.chmod(0o600)
                metrics = signal_metrics(output_path)
                output_embedding = self.converter.extract_se([str(output_path)])
                similarity = self.torch.nn.functional.cosine_similarity(
                    target_se.flatten().unsqueeze(0),
                    output_embedding.flatten().unsqueeze(0),
                ).item()
                import soundfile as sf

                waveform, _ = sf.read(str(output_path), always_2d=False)
                if getattr(waveform, "ndim", 1) > 1:
                    waveform = np.mean(waveform, axis=1)
                try:
                    decoded = self.converter.detect_watermark(np.asarray(waveform), 2)
                except Exception as exc:
                    decoded = "ERROR:%s" % type(exc).__name__
                generation_seconds = base_seconds + conversion_seconds
                result = {
                    "index": index,
                    "text": clean_text,
                    "filename": filename,
                    "sha256": sha256_file(output_path),
                    "synthetic": True,
                    "speed": speed,
                    "watermark_requested": WATERMARK_MESSAGE,
                    "watermark_decoded": decoded,
                    "base_tts_seconds": base_seconds,
                    "conversion_seconds": conversion_seconds,
                    "generation_seconds": generation_seconds,
                    "real_time_factor": generation_seconds / max(metrics["duration_seconds"], 1e-9),
                    "signal": metrics,
                    "speaker_similarity_proxy": {
                        "method": "OpenVoice converter embedding cosine",
                        "cosine": similarity,
                        "independent": False,
                        "subjective_similarity_proven": False,
                    },
                }
                sidecar = {
                    "schema": "openvoice-v2.synthetic-output/v1",
                    **result,
                    "reference_sha256": reference_hash,
                    "consent_confirmed": True,
                    "consent_basis": consent_basis,
                    "reference_retained_by_runtime": False,
                    "embedding_persisted": False,
                }
                output_path.with_suffix(".json").write_text(
                    json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
                )
                output_path.with_suffix(".json").chmod(0o600)
                results.append(result)
            return {
                "reference_sha256": reference_hash,
                "reference_signal": signal_metrics(prepared),
                "embedding_extraction_seconds": extraction_seconds,
                "model_load_seconds": self.model_load_seconds,
                "device": self.device,
                "language": self.language,
                "outputs": results,
            }
        finally:
            shutil.rmtree(str(work_root), ignore_errors=True)


def synthesise_one(
    reference_path,
    text,
    language,
    output_filename,
    device,
    consent_confirmed,
    output_root="/fast/openvoice-v2-data/outputs",
    model_root="/fast/models/openvoice-v2",
):
    runtime = OpenVoiceV2Runtime(device=device, language=language, model_root=model_root)
    prefix = Path(synthetic_output_name(output_filename)).stem.replace("_synthetic", "")
    result = runtime.synthesise_many(
        reference_path=reference_path,
        texts=[text],
        output_dir=output_root,
        filename_prefix=prefix,
        consent_confirmed=consent_confirmed,
        consent_basis="operator affirmed own voice or explicit permission in local interface",
    )
    output = result["outputs"][0]
    return str(Path(output_root) / output["filename"]), result
