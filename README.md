# Governed Speech Synthesis Qualification for Agent Control

This public repository provides a provider-neutral speech synthesis interface,
reproducible qualification harness, and a pinned MyShell OpenVoice V2
installation for hpubuntu. It compares OpenVoice V2, the already-installed
Kokoro ONNX service, MeloTTS, and an opt-in ElevenLabs adapter without changing
the system Python, NVIDIA driver, system CUDA toolkit, or protected workloads.
The installer and Agent Control Job remain optional. A separately authorised
password-protected OpenVoice beta is documented below.

Voice cloning is allowed only for the operator's own voice or a voice for which
explicit permission has been obtained. All outputs are marked synthetic and the
upstream `@MyShell` watermark is preserved where audio length permits.

## Current verdict

**PARTIAL.** OpenVoice V2, Kokoro, and MeloTTS have each produced speech on the
qualification host. OpenVoice is qualified for the complete CPU corpus and a
bounded ten-case Pascal GPU corpus; its long GPU case deliberately failed the
VRAM safety gate. ElevenLabs is implemented against the official streaming API
but remains unqualified because no credential or live synthesis was available.
Human listening is still required before making a subjective quality claim.

The portable entry point is:

```python
from speech import synthesize

result = synthesize(
    text="The next train leaves Newark at half past seven.",
    voice="default",
    provider="auto",
    speed=1.0,
    style=None,
    output_format="wav",
    output_path="/tmp/example_synthetic.wav",
)
```

`provider="auto"` is local-first and never selects a cloud provider. See
[`docs/speech-synthesis/qualification.md`](docs/speech-synthesis/qualification.md)
for the evidence matrix and [`CHANGELOG.md`](CHANGELOG.md) for release history.

## Pinned layout

- Integration: `/fast/repos/openvoice-v2-agent-control` (this repository)
- Upstream source: `/fast/repos/openvoice-v2-upstream` at
  `74a1d147b17a8c3092dd5430504bd83ef6c7eb23`
- Verified packaging build: `/fast/build/openvoice-v2-74a1d147b17a8c3092dd5430504bd83ef6c7eb23`
- Python: `/fast/venvs/openvoice-v2-py39` (3.9.23 only)
- Models: `/fast/models/openvoice-v2`
- Runtime data: `/fast/openvoice-v2-data`
- Qualification: an external `/fast/qualification/openvoice-v2-*` directory

See [`UPSTREAM.lock.json`](UPSTREAM.lock.json) for every code/model/runtime pin.
The upstream code and models are fetched from the MyShell GitHub/Hugging Face
projects and are never vendored into this public source repository.
The upstream checkout remains pristine. A hashed packaging-only patch adjusts
the NumPy patch version required by the isolated PyAV 10 build; see the lock and
[`qualification.md`](qualification.md) for the exact boundary.

## Qualified result

The 2026-08-26 hpubuntu run completed all OpenVoice Agent Control steps and the
multi-provider harness produced speech with every available local adapter. The
overall verdict remains **PARTIAL** pending independent human listening, a
separately authorised real-person reference, and a credentialed ElevenLabs run.
See [`qualification.md`](qualification.md),
[`docs/speech-synthesis/qualification.md`](docs/speech-synthesis/qualification.md),
and [`MODEL_HASHES.json`](MODEL_HASHES.json).

## Agent Control

Agent Control registers a manual-only `openvoice-v2-install-qualify` Job. Its
steps are protected-workload preflight, explicitly approved install, CPU-first
British English smoke, bounded Pascal GPU test or safe skip, CPU/GPU comparison,
and a repository privacy gate. The Job writes JSON artifacts only; voice audio
and embeddings never enter its artifact store.

The one-shot operator command is exposed by Agent Control as:

```bash
npm run qualify:openvoice
```

Required path variables are supplied by the reviewed hpubuntu invocation. There
is no qualification schedule and the capability is not advertised in the
default configuration.

## Local interface

After installation, for an explicitly requested interactive session only:

```bash
/fast/venvs/openvoice-v2-py39/bin/python scripts/local_interface.py \
  --host 127.0.0.1 --port 7861 --device cpu
```

The interface accepts exactly one authorised reference from either a WAV/MP3
drop/upload or a browser microphone recording, plus text, installed
language/accent and output filename. Microphone capture requires a browser secure
context: use loopback or tailnet-only HTTPS (for example, Tailscale Serve), not
plain HTTP on a Tailscale IP. The interface rejects public/LAN binds; only
loopback or a literal Tailscale `100.64.0.0/10` address is accepted. There is
deliberately no Gradio share option. British, American, Australian, Indian and
default English use the pinned English MeloTTS model; other languages require
separately pinned models/evidence. Do not leave this process running as a
service. No interface is enabled by the installation or Agent Control
registration.

## Password-protected public beta

The separately authorised `lozknowles.com/voice-clone/` beta uses
`scripts/public_interface.py`; it does not publish the local qualification UI.
Apache requires a password before proxying over Tailscale to a dedicated
CPU-only backend on port 17862. The username, password and password hash are
never stored in Git.

The beta fixes concurrency at one, keeps only two queued requests, limits each
reference to 15 MiB and 2–30 seconds, limits text to 300 characters, applies
per-client and global hourly limits, and removes server-side references and
outputs within one hour. Runtime data is held beneath the user systemd runtime
directory and disappears when the service stops. The service hides GPU devices,
runs at low CPU/I/O priority, and has explicit CPU, memory and task limits.

The reviewed service and Apache templates are in [`deploy/`](deploy/). They are
not installed by the qualification script or Agent Control Job. Enabling the
beta requires a separate deliberate deployment, a root-owned Apache password
file, configuration validation, and protected-workload checks before and after.

If the browser is on another tailnet device, SSH forwarding is unavailable and
Tailscale Serve HTTPS is not enabled, run the bounded client-side proxy with a
literal Tailscale target:

```bash
python scripts/local_loopback_proxy.py \
  --listen-port 17861 \
  --target-host <server-tailscale-ipv4> \
  --target-port 17861 \
  --lifetime-seconds 28800
```

Then open `http://127.0.0.1:17861`. The helper accepts only a loopback listener
and a Tailscale CGNAT target, forwards raw bytes without logging audio, and exits
when its bounded lifetime ends.

## Verification

```bash
/fast/venvs/openvoice-v2-py39/bin/python -m pytest -q
/fast/venvs/openvoice-v2-py39/bin/python scripts/synthesize.py --list-providers
/fast/venvs/openvoice-v2-py39/bin/python scripts/verify_repo_hygiene.py \
  --repo . --report /fast/qualification/openvoice-v2-hygiene.json
python3 scripts/audit_public_history.py \
  --repo . --report /fast/qualification/openvoice-v2-public-history.json
```

Read [`architecture.md`](architecture.md), [`SECURITY.md`](SECURITY.md), and
[`consent-guidance.md`](consent-guidance.md) before use. Provider-specific
documents are under [`docs/speech-synthesis/`](docs/speech-synthesis/).

## Upstream

- OpenVoice: <https://github.com/myshell-ai/OpenVoice>
- MeloTTS: <https://github.com/myshell-ai/MeloTTS>
- OpenVoice V2 checkpoints: <https://huggingface.co/myshell-ai/OpenVoiceV2>

OpenVoice and MeloTTS are MIT licensed. This integration is also MIT licensed;
see [`THIRD_PARTY.md`](THIRD_PARTY.md) and [`LICENSE`](LICENSE).
