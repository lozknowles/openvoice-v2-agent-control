from pathlib import Path

import pytest

import speech.interface as interface
from speech.interface import ProviderCapabilities, SynthesisRequest, synthetic_filename


def test_neutral_signature_defaults_to_local_only_auto_policy(monkeypatch, tmp_path):
    class Unavailable:
        @classmethod
        def availability(cls):
            return False, "not installed"

    monkeypatch.setattr(interface, "provider_class", lambda name: Unavailable)
    request = SynthesisRequest(text="Hello.", voice="preset", output_dir=tmp_path)
    with pytest.raises(RuntimeError, match="cloud routing is never automatic"):
        interface.choose_provider(request)


def test_auto_routes_reference_files_to_openvoice(monkeypatch, tmp_path):
    reference = tmp_path / "authorised.wav"
    reference.write_bytes(b"RIFF")

    class Available:
        @classmethod
        def availability(cls):
            return True, "available"

    monkeypatch.setattr(interface, "provider_class", lambda name: Available)
    request = SynthesisRequest(
        text="Hello.", voice=str(reference), output_dir=tmp_path / "outputs"
    )
    assert interface.choose_provider(request) == "openvoice"


def test_output_names_are_leaf_only_and_marked_synthetic():
    assert synthetic_filename("../../private recording.mp3", "wav") == (
        "private-recording_synthetic.wav"
    )
    assert synthetic_filename("result_synthetic.wav", "wav") == "result_synthetic.wav"


def test_request_rejects_provider_specific_style_keys(tmp_path):
    with pytest.raises(ValueError, match="unsupported neutral style keys"):
        SynthesisRequest(
            text="Hello.",
            voice="preset",
            style={"similarity_boost": 1.0},
            output_dir=tmp_path,
        )


def test_capability_flags_are_serialisable():
    flags = ProviderCapabilities(
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
        installed_languages=("en-GB",),
    ).as_dict()
    assert flags["voice_cloning"] is True
    assert flags["installed_languages"] == ["en-GB"]
