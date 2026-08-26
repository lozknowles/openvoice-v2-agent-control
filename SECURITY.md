# Security policy

## Non-negotiable controls

- Use only a voice owned by the operator or covered by explicit permission.
- Never use the system Python, upgrade the NVIDIA driver, replace system CUDA,
  or stop protected workloads to make GPU inference fit.
- Never bind the interface to `0.0.0.0`, `::`, a public address, or a LAN address
  outside Tailscale. Never use Gradio sharing or a public tunnel.
- Grant microphone permission only on the operator's loopback origin or a
  tailnet-only HTTPS origin. Record in private surroundings and clear the
  microphone reference when it is no longer needed.
- Never commit or push reference audio, generated audio, speaker embeddings,
  checkpoints, model caches, environment files, tokens, credentials or personal
  recordings.
- Preserve the upstream watermark. This integration always passes
  `@MyShell` to `ToneColorConverter.convert` and records whether decoding was
  observed.
- Treat generated speech as synthetic in filenames, metadata and downstream
  descriptions.

## Data handling

Uploaded WAV/MP3 or browser-recorded WAV references are copied into a private
temporary working directory, normalised for inference, hashed for evidence, and
removed after the request.
Extracted embeddings remain in process memory and are not deliberately
persisted. Qualification audio lives only beneath `/fast/qualification` and is
excluded from Git; operator test output lives beneath `/fast/openvoice-v2-data`.

## Network boundary

Installation may read the pinned GitHub, PyTorch, conda-forge and Hugging Face
artifacts recorded in `UPSTREAM.lock.json`. Inference uses local files. The UI
does not require outbound network access after the pinned model cache is
present.

## Resource safety

The guard records llama.cpp, OCR, image-identification and existing TTS health
before execution and checks it throughout. GPU work requires a configurable
minimum free-VRAM margin. A breach aborts only the OpenVoice child. CPU work is
nice/idle-I/O scheduled and thread-limited.

## Reporting a problem

Do not attach voice samples, credentials, model files or embeddings to an issue.
Provide redacted logs, hashes, package versions and the Agent Control Run ID.
