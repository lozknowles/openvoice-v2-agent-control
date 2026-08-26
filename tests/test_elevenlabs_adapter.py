import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from speech.interface import SynthesisRequest
from speech.providers.base import ProviderUnavailable
from speech.providers.elevenlabs import ElevenLabsProvider


class FakeElevenLabsHandler(BaseHTTPRequestHandler):
    request_body = None
    request_key = None
    request_path = None

    def log_message(self, fmt, *args):
        return None

    def do_POST(self):  # noqa: N802
        type(self).request_path = self.path
        type(self).request_key = self.headers.get("xi-api-key")
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_body = json.loads(self.rfile.read(length).decode("utf-8"))
        first = b"\x00\x00" * 1200
        second = b"\x00\x00" * 1200
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("request-id", "mock-request-123")
        self.end_headers()
        self.wfile.write(first)
        self.wfile.flush()
        time.sleep(0.05)
        self.wfile.write(second)
        self.wfile.flush()


@pytest.fixture
def fake_elevenlabs(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeElevenLabsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "unit-test-secret-never-write")
    monkeypatch.setenv(
        "ELEVENLABS_API_BASE", "http://127.0.0.1:%s" % server.server_address[1]
    )
    monkeypatch.setenv("ELEVENLABS_MAX_RETRIES", "0")
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_streaming_adapter_writes_wav_measures_ttfa_and_never_persists_key(
    fake_elevenlabs, tmp_path
):
    provider = ElevenLabsProvider()
    request = SynthesisRequest(
        text="A short authorised cloud test.",
        voice="voice_mock_123",
        provider="elevenlabs",
        output_dir=tmp_path,
        output_filename="cloud-test",
        consent_confirmed=True,
        consent_basis="official mock voice used only by a local unit test",
        allow_cloud=True,
    )
    output = tmp_path / "cloud-test_synthetic.wav"
    result = provider.synthesize(request, output)
    assert output.read_bytes().startswith(b"RIFF")
    assert result.request_id == "mock-request-123"
    assert result.time_to_first_audio_seconds is not None
    assert result.time_to_first_audio_seconds <= result.total_latency_seconds
    assert result.output_duration_seconds == pytest.approx(0.1, rel=0.01)
    assert result.metadata["audio"]["signal"]["clipped_fraction"] == 0.0
    assert result.estimated_cloud_cost_usd == pytest.approx(len(request.text) * 0.0001)
    assert FakeElevenLabsHandler.request_key == "unit-test-secret-never-write"
    assert "pcm_24000" in FakeElevenLabsHandler.request_path
    assert FakeElevenLabsHandler.request_body["model_id"] == "eleven_multilingual_v2"
    assert FakeElevenLabsHandler.request_body["voice_settings"]["speed"] == 1.0
    persisted = output.with_suffix(".json").read_text(encoding="utf-8")
    assert "unit-test-secret-never-write" not in persisted
    assert "unit-test-secret-never-write" not in json.dumps(result.as_dict())


def test_cloud_adapter_requires_explicit_opt_in(fake_elevenlabs, tmp_path):
    provider = ElevenLabsProvider()
    request = SynthesisRequest(
        text="Do not send this.",
        voice="voice_mock_123",
        provider="elevenlabs",
        output_dir=tmp_path,
        consent_confirmed=True,
        consent_basis="test",
        allow_cloud=False,
    )
    with pytest.raises(PermissionError, match="allow_cloud"):
        provider.synthesize(request, tmp_path / "blocked_synthetic.wav")


def test_cloud_adapter_reports_missing_credentials(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    available, reason = ElevenLabsProvider.availability()
    assert available is False
    assert "absent" in reason
    with pytest.raises(ProviderUnavailable):
        ElevenLabsProvider()
