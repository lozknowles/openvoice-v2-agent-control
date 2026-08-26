from pathlib import Path

import pytest

from scripts.local_interface import select_reference
from scripts.local_loopback_proxy import validate_proxy_endpoints
from scripts.public_interface import (
    FixedWindowLimiter,
    PUBLIC_MAX_TEXT_CHARS,
    cleanup_expired,
    remove_uploaded_reference,
    validate_public_text,
)
from scripts.openvoice_v2_runtime import (
    OpenVoiceV2Runtime,
    synthetic_output_name,
    validate_bind_host,
)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "100.64.0.1"])
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


@pytest.mark.parametrize(
    ("upload_reference", "microphone_reference", "expected"),
    [
        ("authorised-upload.mp3", None, "authorised-upload.mp3"),
        (None, "authorised-microphone.wav", "authorised-microphone.wav"),
    ],
)
def test_exactly_one_upload_or_microphone_reference_is_selected(
    upload_reference, microphone_reference, expected
):
    assert select_reference(upload_reference, microphone_reference) == expected


@pytest.mark.parametrize(
    ("upload_reference", "microphone_reference"),
    [(None, None), ("upload.wav", "microphone.wav")],
)
def test_missing_or_ambiguous_reference_is_rejected(
    upload_reference, microphone_reference
):
    with pytest.raises(ValueError):
        select_reference(upload_reference, microphone_reference)


def test_interface_has_no_share_argument():
    source = (Path(__file__).parents[1] / "scripts/local_interface.py").read_text(
        encoding="utf-8"
    )
    assert "--share" not in source
    assert "share=True" not in source
    assert "share=False" in source


def test_interface_exposes_upload_and_microphone_sources():
    source = (Path(__file__).parents[1] / "scripts/local_interface.py").read_text(
        encoding="utf-8"
    )
    assert 'source="upload"' in source
    assert 'source="microphone"' in source
    assert source.count("show_share_button=False") == 2


def test_loopback_proxy_accepts_only_loopback_to_tailscale():
    assert validate_proxy_endpoints("127.0.0.1", "100.64.0.1") == (
        "127.0.0.1",
        "100.64.0.1",
    )
    with pytest.raises(ValueError):
        validate_proxy_endpoints("0.0.0.0", "100.64.0.1")
    with pytest.raises(ValueError):
        validate_proxy_endpoints("127.0.0.1", "192.168.1.10")


def test_runtime_does_not_disable_upstream_watermarking():
    source = (Path(__file__).parents[1] / "scripts/openvoice_v2_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "enable_watermark=False" not in source


def test_public_text_limit_is_bounded():
    assert validate_public_text("A short test sentence.") == "A short test sentence."
    with pytest.raises(ValueError):
        validate_public_text("x" * (PUBLIC_MAX_TEXT_CHARS + 1))


def test_public_limiter_enforces_client_and_global_windows():
    limiter = FixedWindowLimiter(global_limit=3, client_limit=2, window_seconds=60)
    assert limiter.consume("first", now=1)[0]
    assert limiter.consume("first", now=2)[0]
    assert not limiter.consume("first", now=3)[0]
    assert limiter.consume("second", now=3)[0]
    assert not limiter.consume("third", now=4)[0]
    assert limiter.consume("first", now=70)[0]


def test_public_retention_and_upload_removal_are_scoped(tmp_path):
    data_root = tmp_path / "runtime"
    upload_root = data_root / "gradio"
    outputs = data_root / "outputs"
    upload_dir = upload_root / "request"
    upload_dir.mkdir(parents=True)
    outputs.mkdir(parents=True)
    reference = upload_dir / "reference.wav"
    reference.write_bytes(b"RIFF")
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"keep")
    remove_uploaded_reference(reference, upload_root)
    remove_uploaded_reference(outside, upload_root)
    assert not reference.exists()
    assert outside.exists()

    expired = outputs / "expired"
    fresh = outputs / "fresh"
    expired.mkdir()
    fresh.mkdir()
    import os

    os.utime(expired, (1, 1))
    os.utime(fresh, (100, 100))
    assert cleanup_expired(data_root, retention_seconds=50, now=120) == 1
    assert not expired.exists()
    assert fresh.exists()


def test_public_interface_is_cpu_only_bounded_and_unshared():
    source = (Path(__file__).parents[1] / "scripts/public_interface.py").read_text(
        encoding="utf-8"
    )
    assert 'device="cpu"' in source
    assert 'choices=["cpu", "cuda"]' not in source
    assert "share=False" in source
    assert "concurrency_count=1" in source
    assert "max_size=2" in source
    assert "root_path=PUBLIC_ROOT_PATH" in source


def test_public_deployment_templates_require_auth_and_resource_caps():
    root = Path(__file__).parents[1]
    apache = (root / "deploy/apache-lozknowles-voice-clone.conf").read_text(
        encoding="utf-8"
    )
    service = (root / "deploy/openvoice-v2-public.service").read_text(
        encoding="utf-8"
    )
    assert "AuthType Basic" in apache
    assert "Require valid-user" in apache
    assert "LimitRequestBody 16777216" in apache
    assert "voice_clone_no_log" in apache
    assert 'microphone=(self)' in apache
    assert "MemoryMax=10G" in service
    assert "CPUQuota=150%" in service
    assert "CUDA_VISIBLE_DEVICES=" in service
    assert "PrivateDevices=true" in service
