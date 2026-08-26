# OpenVoice V2 qualification

## Status

**CPU PASS; bounded GPU PASS; overall PARTIAL.** OpenVoice produced every case
in the complete CPU corpus and ten bounded GPU cases. The full GPU corpus's long
case was stopped by the free-VRAM safety guard; long-form GPU use is therefore
not qualified. Human listening and an independently authorised real-person
reference remain outstanding.

## Reproducible installation

- Upstream repository: `myshell-ai/OpenVoice`
- Upstream commit: `74a1d147b17a8c3092dd5430504bd83ef6c7eb23`
- Integration source commit used by exact-commit smoke tests:
  `d9e6991d30a8f36da040723501a662ebd4e1049f`
- Isolated Python: 3.9.23 at `/fast/venvs/openvoice-v2-py39`
- OpenVoice V2 and MeloTTS models: `/fast/models/openvoice-v2`
- PyTorch: 2.5.1+cu121
- MeloTTS: 0.1.2
- Host GPU: Quadro P5000, 16 GiB, Pascal compute capability 6.1
- Existing NVIDIA driver: 580.173.02
- Existing system CUDA toolkit: 12.0, unchanged

Exact code, model, installer, packaging-patch, and environment pins are recorded
in `UPSTREAM.lock.json` and `MODEL_HASHES.json`. Models, environments, and audio
are not stored in this repository.

## CPU result

The complete 11-case British English corpus generated 83.267 seconds of audio.
Total synthesis time was 306.362 seconds; mean per-case complete-file latency
was 27.851 seconds and mean real-time factor was 3.891. Peak observed worker RSS
was 5,530,431,488 bytes (about 5.15 GiB) with three-success worker recycling.
No GPU memory was used and no successful sample showed digital clipping.

All 11 outputs decoded the upstream `@MyShell` watermark. The bundled reference
fixture is synthetic MeloTTS speech and therefore validates pipeline mechanics,
not similarity to a real person.

## GPU result

The bounded ten-case corpus generated 64.308 seconds of audio. Total synthesis
time was 48.395 seconds; mean per-case complete-file latency was 4.840 seconds
and mean real-time factor was 0.824. Peak worker RSS was 2,936,184,832 bytes
(about 2.73 GiB), peak process VRAM was 2,082 MiB, and all ten outputs decoded
the watermark.

For the same ten cases, CPU total time was 245.645 seconds, making the guarded
GPU path about 5.08 times faster on this host. This is a latency comparison, not
a quality or similarity result.

The attempted full GPU corpus was aborted only at the long case when the VRAM
safety margin was breached. The guard observed 2,586 MiB of new GPU allocation,
9,525 MiB total use, and 6,742 MiB free at abort. Every protected unit and health
endpoint remained healthy. The threshold was not weakened.

## Output comparison

CPU and GPU output hashes differed for all ten matching cases. That is expected
from different execution paths and prevents byte-equivalence claims. Gross
signal checks showed zero clipped fraction, but those checks do not establish
absence of noise or artefacts.

The optional tiny.en ASR proxy produced a CPU micro word-error rate of 34/214
(0.15888) and a bounded GPU value of 36/161 (0.22360). This small recogniser has
known difficulty with unusual names and technical terms; the values are useful
for regression triage only and are not subjective intelligibility scores.

The internal speaker-embedding cosine proxy ranged from 0.72293 to 0.90995 on
CPU and 0.74803 to 0.91223 on GPU. It is produced by the synthesis stack itself,
is not an independent biometric evaluation, and does not prove speaker
similarity.

## Safety and deployment

Use CPU for long-form cloning. Use the bounded GPU path only when the live guard
permits it and leave the long case disabled until a separate resource window can
be qualified. Never stop or resize protected workloads to make inference fit.

OpenVoice is registered with Agent Control as a manual optional capability, not
an always-running service. The separately authorised website beta is CPU-only,
password protected, rate limited, and backed by a Tailscale-only listener.
