# Speech providers

## Qualification matrix

`Qualified` below means the adapter actually produced speech during this run.
It does not imply a subjective quality ranking.

| Provider | Status | Local | Cloud | Streaming | Cloning | Zero-shot | Multilingual | Speed | Style/emotion | Pronunciation | Offline |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenVoice V2 | CPU PASS; bounded GPU PASS | yes | no | no | yes | yes | yes upstream; British English qualified | yes | limited base-speaker style | no portable control | yes |
| Kokoro ONNX (`local`) | CPU PASS; GPU PASS | yes | no | no | no | no | no in this deployment | yes | no portable control | no portable control | yes |
| MeloTTS | CPU PASS; GPU PASS | yes | no | no | no | no | yes upstream; British English qualified | yes | base-speaker choice | no portable control | yes |
| ElevenLabs | UNQUALIFIED: no live credentialed run | no | yes | yes | yes in official service | yes in official service | model dependent | yes | yes | yes | no |

The ElevenLabs row records documented service capabilities, not locally proven
capabilities. See [`elevenlabs.md`](elevenlabs.md) for the qualification boundary.

## Portable interface

```python
synthesize(
    text,
    voice,
    provider="auto",
    speed=1.0,
    style=None,
    output_format="wav",
    output_path=None,
    language="en-GB",
    reference_path=None,
    allow_cloud=False,
)
```

The result records provider identity, output path and format, sample rate,
duration, size, latency, first-audio time, real-time factor, retries, and
provider metadata. Local non-streaming adapters report complete-file
availability as time to first audio.

## OpenVoice V2

The `openvoice` adapter uses MeloTTS to generate base speech, extracts a speaker
embedding from an authorised reference, and applies the pinned V2 tone-colour
converter. It is the only qualified zero-shot cloning adapter in this repository.
The worker always requests the upstream watermark and uses `_synthetic.wav`
outputs. A reference is mandatory.

## Existing local Kokoro

The `local` adapter targets the already-installed `kokoro-onnx` service through
its isolated worker. The observed environment is Python 3.12,
`kokoro-onnx 0.6.1`, `onnxruntime-gpu 1.18.1`; CUDAExecutionProvider was active
for the GPU run. The existing service, client restriction, environment, and
unit were not changed.

This is currently the safest `auto` default for ordinary British English
preset-voice work because its CPU corpus was fastest among the tested CPU paths
and it leaves GPU capacity to protected workloads.

## Direct MeloTTS

The `melotts` adapter exposes the pinned British English base synthesiser without
OpenVoice conversion. It shares the isolated OpenVoice Python 3.9 environment
but runs in its own worker. It was the fastest complete-file GPU path among the
three live local adapters, though it does not clone a reference voice.

## ElevenLabs

The adapter uses the official streaming HTTP endpoint, environment-only API-key
loading, and an existing voice ID. It never enters `auto`, never uploads a
reference, and never creates a voice. Mock transport tests prove request and
stream handling only. No speech was produced because no credential was present,
so the provider is not qualified.

## Other inspected software

- Jarvis components observed on the host are speech-to-text or analysis tools,
  not a synthesiser, so they were not adapted.
- A flite library was present without a supported command-line/runtime path and
  was not treated as a qualified provider.
- No OASIS service or process was observed during inventory. This is an
  observation, not permission to alter an OASIS installation elsewhere.

## Selection guidance

- Use `auto` or `local` for private ordinary British English preset speech.
- Use `openvoice` only for an authorised cloning case.
- Use `melotts` for a local base-voice comparison or guarded low-latency GPU
  batch when capacity is available.
- Use `elevenlabs` only after explicit cloud/data approval, a permitted voice
  ID, and credentialed qualification.
