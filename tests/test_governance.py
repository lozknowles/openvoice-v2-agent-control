from pathlib import Path

import pytest

from scripts.openvoice_v2_runtime import (
    OpenVoiceV2Runtime,
    synthetic_output_name,
    validate_bind_host,
)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "100.125.120.114"])
def test_loopback_and_tailscale_binds_are_allowed(host):
    assert validate_bind_host(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "8.8.8.8", "example.com"])
def test_public_and_lan_binds_are_rejected(host):
    with pytest.raises(ValueError):
        validate_bind_host(host)


def test_output_name_is_leaf_synthetic_wav():
    assert synthetic_output_name("../../private recording.mp3") == "private-recording_synthetic.wav"


def test_generation_requires_explicit_consent(tmp_path):
    runtime = object.__new__(OpenVoiceV2Runtime)
    with pytest.raises(PermissionError):
        runtime.synthesise_many(
            reference_path=tmp_path / "reference.wav",
            texts=["test"],
            output_dir=tmp_path,
            filename_prefix="test",
            consent_confirmed=False,
            consent_basis="",
        )


def test_interface_has_no_share_argument():
    source = (Path(__file__).parents[1] / "scripts/local_interface.py").read_text(encoding="utf-8")
    assert "--share" not in source
    assert "share=True" not in source
    assert "share=False" in source


def test_runtime_does_not_disable_upstream_watermarking():
    source = (Path(__file__).parents[1] / "scripts/openvoice_v2_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "enable_watermark=False" not in source
