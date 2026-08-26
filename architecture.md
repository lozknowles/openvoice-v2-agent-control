# Architecture

## Boundary

OpenVoice qualification remains an optional, one-shot capability. Agent Control owns the Job,
approval, resource lock, run ledger and JSON evidence. The OpenVoice repository
owns the fixed installer, runtime, consent checks, resource guard and local UI.
The password-protected website beta is a separately authorised deployment. It
does not change or schedule the Agent Control qualification Job.

```text
Agent Control manual Job
  -> exact install approval
  -> fixed action adapter
  -> resource guard
  -> isolated /fast Python 3.9 environment
  -> MeloTTS base speech
  -> OpenVoice V2 tone-colour conversion + @MyShell watermark
  -> synthetic WAV + JSON sidecar outside Git
  -> CPU/GPU reports -> checksummed Agent Control artifacts
```

## Filesystem layout

| Purpose | Default path | Git status |
| --- | --- | --- |
| Integration source | `/fast/repos/openvoice-v2-agent-control` | tracked source/docs only |
| Pinned upstream source | `/fast/repos/openvoice-v2-upstream` | public clone; never pushed as integration |
| Verified packaging build | `/fast/build/openvoice-v2-74a1d147b17a8c3092dd5430504bd83ef6c7eb23` | archived commit plus hashed metadata-only patch |
| Python environment | `/fast/venvs/openvoice-v2-py39` | never tracked |
| Miniforge runtime | `/fast/tools/miniforge-openvoice-v2` | never tracked |
| Checkpoints/models | `/fast/models/openvoice-v2` | never tracked |
| Hugging Face cache | `/fast/models/openvoice-v2/hf-cache` | never tracked |
| Runtime uploads/outputs | `/fast/openvoice-v2-data` | never tracked |
| Qualification evidence | `/fast/qualification/openvoice-v2-*` | reports may be distilled; audio never tracked |

## Execution and isolation

- Python 3.9 is installed by Miniforge into `/fast`; `/usr/bin/python3` is not
  changed.
- The pristine upstream archive receives one reproducible `setup.py` metadata
  patch for NumPy 1.22.4/PyAV 10 compatibility. Runtime source is unchanged.
- PyAV 10 and FFmpeg 6.1.2 are installed from exact conda-forge builds inside
  the environment, avoiding system FFmpeg development-package changes.
- PyTorch carries its own CUDA 12.1 runtime. The system CUDA toolkit and NVIDIA
  driver are observed but never upgraded or replaced.
- CPU qualification uses a low-priority process and two inference threads.
- GPU qualification starts only after CPU success, a live compute-capability
  probe, sufficient free VRAM, and protected-service health checks.
- The guard terminates only the OpenVoice child process if protected health or
  VRAM safety thresholds fail. It never stops another process or service.
- Reference audio and extracted speaker embeddings are temporary. Only hashes,
  timings and aggregate measurements enter Agent Control artifacts.

## Interface

`scripts/local_interface.py` defaults to `127.0.0.1`. Bind validation allows
loopback or the Tailscale CGNAT range (`100.64.0.0/10`) only. The program has no
share option. Separate drop/upload and microphone components feed a fail-closed
selector that requires exactly one reference. Browser microphone capture must
use a secure origin such as loopback or tailnet-only HTTPS. The optional
client-side raw TCP helper binds only to loopback, accepts only a literal
Tailscale CGNAT target, logs no audio and has a bounded lifetime. A consent
affirmation is mandatory for every generation, output names are sanitised, and
generated files receive `_synthetic.wav` plus a JSON sidecar.

The public beta is a separate `public_interface.py` process and never reuses the
operator qualification endpoint. Apache on cottageserver enforces password
authentication at `/voice-clone/`, then proxies over Tailscale to port 17862 on
hpubuntu. The backend is CPU-only, single-concurrency, size/time/rate bounded and
has no public or LAN listener. A low-priority user service applies memory, CPU,
task and device isolation. Ephemeral references and results live only under the
user runtime directory and are removed within one hour or on service stop.

## Qualification scope

British English is the qualified path. The V2 converter supports the upstream
languages, but this integration prefetches and qualifies the pinned English
MeloTTS base model only. Other languages require separately pinned base and BERT
models plus their own evidence.
