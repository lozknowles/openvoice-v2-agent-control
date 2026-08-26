from scripts.audit_public_history import forbidden_path


def test_public_history_audit_rejects_audio_models_and_credentials():
    assert forbidden_path("samples/reference.wav")
    assert forbidden_path("models/voice.safetensors")
    assert forbidden_path(".env")
    assert forbidden_path("deploy/.htpasswd")


def test_public_history_audit_allows_source_and_redacted_metadata():
    assert forbidden_path("speech/providers/openvoice.py") is None
    assert forbidden_path("docs/speech-synthesis/qualification.md") is None
    assert forbidden_path("MODEL_HASHES.json") is None
