# Changelog

All notable source and qualification changes are recorded here. Generated
audio, speaker embeddings, model files, credentials, and personal recordings
are intentionally excluded from Git.

## 2026-08-26 - Multi-provider qualification harness

### Added

- Provider-neutral `speech.synthesize(...)` interface with capability metadata.
- OpenVoice V2, existing Kokoro ONNX, direct MeloTTS, and ElevenLabs adapters.
- Fixed British English benchmark corpus and repeatable CPU/GPU runner.
- Process, RAM, CPU, VRAM, duration, latency, real-time-factor, retry, and output
  metadata collection.
- Optional tiny.en ASR transcription-error proxy and human listening template.
- Public-history and current-tree repository hygiene gates.
- Official-API ElevenLabs streaming adapter with explicit cloud opt-in and
  environment-only authentication.
- Detailed provider, architecture, OpenVoice, ElevenLabs, and qualification
  documentation under `docs/speech-synthesis/`.

### Qualified

- OpenVoice V2: complete CPU corpus and bounded ten-case Pascal GPU corpus.
- Kokoro ONNX: complete CPU and GPU corpora.
- MeloTTS: complete CPU and GPU corpora.

### Not yet qualified

- ElevenLabs live synthesis: no credential was present.
- Subjective intelligibility, similarity, noise, and artefact judgements: human
  listening has not yet been performed.
- OpenVoice long-form GPU synthesis: stopped by the VRAM safety guard while all
  protected workloads remained healthy.

## 2026-08-26 - Initial governed OpenVoice V2 integration

- Pinned upstream OpenVoice commit and V2 checkpoint manifests.
- Added isolated Python 3.9 installation and Pascal-compatible PyTorch CUDA
  runtime without changing the host driver or CUDA toolkit.
- Added CPU-first qualification, bounded GPU guard, consent enforcement,
  synthetic filenames, JSON sidecars, and watermark preservation.
- Registered an optional manual Agent Control capability.
- Added localhost/Tailscale operator UI and separately governed,
  password-protected CPU-only website beta.
