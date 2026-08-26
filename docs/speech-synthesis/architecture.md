# Speech synthesis architecture

## Purpose

The speech layer separates a portable synthesis request from engine-specific
installation and execution. It is a qualification harness, not a permanently
running multi-provider service. Agent Control may invoke it as an optional,
governed capability after its resource and consent gates pass.

## Request flow

```text
application or benchmark
  -> synthesize(text, voice, provider, speed, style, output_format, ...)
  -> provider registry
  -> availability and capability validation
  -> provider adapter
       openvoice -> isolated Python 3.9 worker -> MeloTTS -> tone converter
       local     -> isolated Kokoro worker -> existing restricted ONNX service
       melotts   -> isolated Python 3.9 worker -> MeloTTS
       elevenlabs-> HTTPS streaming API, only with explicit cloud opt-in
  -> normalised SynthesisResult
  -> synthetic audio outside Git plus structured benchmark evidence
```

The core request model contains portable fields: `text`, `voice`, `provider`,
`speed`, `style`, `output_format`, `output_path`, `language`, and an optional
authorised reference. Adapters declare capability flags. A caller must inspect
those flags rather than assuming that every provider supports streaming,
cloning, emotion, pronunciation dictionaries, or multilingual output.

## Provider selection

`provider="auto"` is deliberately local-first. It never sends text to a cloud
provider. A cloud adapter must be named explicitly and called with
`allow_cloud=True`. A missing provider, missing voice, unsupported format, or
missing consent fails closed.

The current local order favours the existing Kokoro service for ordinary
British English preset-voice synthesis. OpenVoice is selected explicitly for
authorised zero-shot cloning. MeloTTS remains directly selectable for comparison
and as the OpenVoice base synthesiser.

## Environment isolation

Each local adapter talks to a JSON-lines subprocess worker. This permits the
host's existing Kokoro Python 3.12 environment and the OpenVoice/Melo Python 3.9
environment to coexist without merging dependencies or changing system Python.
Worker standard output is machine-readable; diagnostic output stays on standard
error.

OpenVoice and direct MeloTTS workers recycle after three successful requests.
The complete CPU corpus exposed cumulative allocator RSS growth to roughly
8 GiB without recycling; bounded recycling kept observed peak RSS to about
5.15 GiB for OpenVoice and 4.82 GiB for MeloTTS. Restart time remains part of
the measured synthesis latency.

## Resource governance

The benchmark runner samples child CPU, resident memory, process VRAM, and total
GPU use. A separate guard records protected service state before, during, and
after GPU work. If a free-VRAM margin or protected-health condition fails, only
the benchmark child is terminated. The guard never stops or reconfigures another
workload.

The Quadro P5000 uses compute capability 6.1. OpenVoice runs in its isolated
PyTorch 2.5.1+cu121 environment against the existing driver; the system CUDA
toolkit and NVIDIA driver are not upgraded. Long-form OpenVoice GPU synthesis is
not qualified because the guard stopped that case at its safety threshold.

## Evidence and data boundary

Benchmark output is placed under `/fast/qualification`, outside the repository.
Reports contain timings, resource measurements, hashes, capability flags, and
errors. Audio samples remain external and are never committed. Reference audio,
generated audio, speaker embeddings, checkpoints, caches, credentials, and
personal recordings are excluded by both Git ignore rules and repository audits.

OpenVoice outputs keep the upstream `@MyShell` watermark where audio duration
permits it. Every generated filename and sidecar identifies the output as
synthetic. The ElevenLabs adapter does not create or upload a voice clone; it
accepts only an existing, separately authorised voice ID.

## Agent Control boundary

Agent Control owns approval, the resource lock, run ledger, and checksummed JSON
artifacts. This repository owns adapters, installation, consent enforcement,
benchmarking, and local execution. Registration does not create a schedule or an
always-running service. The separately deployed password-protected website beta
uses only OpenVoice CPU and is not the provider-neutral qualification endpoint.

## Network boundary

Local inference makes no network call once models are present. The existing
Kokoro service retains its restricted LAN client policy. Operator interfaces may
bind only to loopback or a literal Tailscale address; Gradio sharing is absent.
ElevenLabs is the only cloud synthesis path and must be explicitly selected.
