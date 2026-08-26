# Speech synthesis qualification

## Verdict

**PARTIAL.** Three local providers produced speech successfully. OpenVoice V2
passed the complete CPU corpus and a bounded GPU corpus; Kokoro ONNX and MeloTTS
passed complete CPU and GPU corpora. ElevenLabs remains unqualified because no
credentialed live synthesis was possible. Human listening has not been
performed, so no provider is declared best for subjective quality or speaker
similarity.

## Current host state

Inventory was read before installation or testing. No system Python, CUDA
toolkit, NVIDIA driver, protected service, or existing TTS environment was
changed.

| Item | Observed state |
| --- | --- |
| OS/kernel | Ubuntu 24.04.4 LTS; Linux 6.8.0-137 |
| CPU | Intel Core i7-7700HQ, 4 cores / 8 threads |
| RAM | 62 GiB total; 47 GiB available at inventory |
| `/fast` | 1.8 TiB total; 647 GiB free at inventory |
| GPU | NVIDIA Quadro P5000, 16 GiB, compute capability 6.1 |
| Driver/system CUDA | 580.173.02 / CUDA toolkit 12.0; unchanged |
| System Python | 3.12.3; unchanged |
| OpenVoice Python | isolated 3.9.23 |
| OpenVoice PyTorch | 2.5.1+cu121 |
| Existing Kokoro | Python 3.12; kokoro-onnx 0.6.1; onnxruntime-gpu 1.18.1 |

The protected user units for llama.cpp, Kokoro, OCR, image identification, and
the existing OpenVoice beta remained active through qualification. No OASIS unit
or process was observed. The absence of a process was not treated as authority
to alter any OASIS installation.

## Corpus and method

`speech/benchmarks/corpus.en-GB.json` contains 11 fixed cases covering a short
conversation, long paragraph, numbers, dates, UK place names, unusual names,
abbreviations, technical terminology, a question, excited delivery, and neutral
information. The same text and provider settings are retained per comparison.

Metrics include worker initialisation, complete-file time to first audio, total
latency, duration, real-time factor, output size, peak worker RSS/CPU, process
VRAM, host GPU delta, failures/retries, watermark result, and coarse signal
statistics. None of the local adapters streams, so first audio equals completed
file availability. Worker restart time is included.

The optional tiny.en transcription comparison is an objective regression proxy,
not a listening score. Speaker-embedding cosine is an internal pipeline proxy,
not independent evidence of identity. Samples and listening-template metadata
are retained outside Git for a later blind human exercise.

## CPU benchmark

| Provider | Cases | Init s | Total s | Audio s | Mean latency s | Mean RTF | Peak RSS | Peak CPU | Clipping |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenVoice V2 | 11/11 | 7.679 | 306.362 | 83.267 | 27.851 | 3.891 | 5.15 GiB | 207.7% | 0 |
| Kokoro ONNX | 11/11 | 1.058 | 122.631 | 98.091 | 11.148 | 1.278 | 0.845 GiB | 403.9% | 0 |
| MeloTTS | 11/11 | 7.069 | 227.945 | 83.077 | 20.722 | 2.853 | 4.82 GiB | 218.5% | 0 |

Kokoro was the fastest tested CPU provider and used much less resident memory.
This supports a default-routing decision for ordinary preset speech; it does not
establish superior sound quality.

## GPU benchmark

| Provider | Cases | Init s | Total s | Audio s | Mean latency s | Mean RTF | Peak RSS | Peak process VRAM | Clipping |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenVoice V2 | 10/10 bounded | 7.897 | 48.395 | 64.308 | 4.840 | 0.824 | 2.73 GiB | 2,082 MiB | 0 |
| Kokoro ONNX | 11/11 | 1.613 | 109.456 | 98.240 | 9.951 | 1.151 | 1.07 GiB | 644 MiB | 0 |
| MeloTTS | 11/11 | 7.342 | 35.697 | 83.321 | 3.245 | 0.584 | 2.37 GiB | 2,108 MiB | 0 |

For matching work, OpenVoice GPU was approximately 5.08 times faster than CPU,
Kokoro approximately 1.12 times faster, and MeloTTS approximately 6.39 times
faster. MeloTTS was the fastest tested complete-file GPU path. Kokoro's small GPU
gain does not justify displacing protected GPU workloads for the default route.

The full OpenVoice GPU run reached the free-VRAM safety threshold on the long
case and was stopped. Peak new use was 2,586 MiB, total use 9,525 MiB, and free
VRAM 6,742 MiB at abort. The benchmark child alone was terminated; protected
units/endpoints stayed healthy. Long-form OpenVoice GPU operation is not
qualified.

## Objective transcription proxy

| Provider/path | Word edits / words | Micro WER |
| --- | ---: | ---: |
| Kokoro CPU | 32 / 214 | 0.14953 |
| MeloTTS CPU | 33 / 214 | 0.15421 |
| OpenVoice CPU | 34 / 214 | 0.15888 |
| Kokoro GPU | 29 / 214 | 0.13551 |
| MeloTTS GPU | 41 / 214 | 0.19159 |
| OpenVoice GPU, bounded | 36 / 161 | 0.22360 |

The small recogniser misheard several unusual names and technical terms. These
figures may detect gross regressions but cannot replace intelligibility ratings.

## CPU/GPU output comparison

Every corresponding CPU/GPU output had a different SHA-256: 10/10 for
OpenVoice, 11/11 for Kokoro, and 11/11 for MeloTTS. Outputs are therefore not
byte equivalent. All successful files had clipped fraction 0.0. Neither finding
proves equal perceptual quality or absence of noise and artefacts.

OpenVoice decoded `@MyShell` from all 11 CPU and all 10 bounded GPU samples. Its
internal speaker-embedding proxy ranged 0.72293-0.90995 on CPU and
0.74803-0.91223 on GPU. Because the synthesiser's own representation supplies
that proxy, it does not prove speaker similarity.

## Evidence manifest

Evidence lives outside Git under `/fast/qualification`. SHA-256 values bind the
reports without publishing audio or private runtime data.

| Evidence | SHA-256 |
| --- | --- |
| Exact-commit CPU smoke report | `bea5c5acc1ad7ab517cc3412bfcad8fce5f45aa7f01760bac3da3623f45eda5b` |
| Exact-commit CPU guard | `34a26a4f222f8c4bd21a7e4e71bc438493650de1c8114291fe08af19608876e5` |
| Exact-commit GPU smoke report | `9dccd4f18dfb17313ce930916ad6abb3340d56249053823227beb5a0ddae179a` |
| Exact-commit GPU guard | `987ac2e3eef01082668f5e8d2035adcc998d1ec72282848d10f829fc5d210aad` |
| Full CPU OpenVoice/Melo report | `10ff7205a74c7f471977df81f6e64259a66106e9f027415756e1b6a70500e79e` |
| Full CPU Kokoro report | `3df990b435a3f315943a4e2498f6f0d3f3f335ec62d7cfb8e01a43803469e9fc` |
| Bounded GPU OpenVoice report | `fb3a3c199c38cd02720d211eefa0ed13f6c248f8ee2915744f3a9f4bf022771b` |
| Full GPU Kokoro report | `f72c1fecff0cfb0def52dac7bc6756fa847654a9253f5b8e73c67042dd00abd1` |
| Full GPU Melo report | `b779d08e321b0ff351277c306059d88071c8b780c7f42e46b14c00b618b8ddb0` |
| Aborted full OpenVoice GPU guard | `39a0ccf4a1d4ad2cac414b62a1dee88d0fefbfdb3d1889870f75594635e0689d` |

The complete-corpus reports were produced immediately before the source was
sealed and consequently record base commit `c5c416d`. Clean-checkout CPU and GPU
smoke reports were then run from source commit
`d9e6991d30a8f36da040723501a662ebd4e1049f`, binding the execution code used for
the final adapter implementation. The distinction is retained rather than
rewriting provenance.

## Recommendations

- Default ordinary British English preset speech: Kokoro CPU.
- Private/local authorised cloning: OpenVoice CPU; guarded GPU only for bounded
  short/medium work.
- Lowest tested complete-file latency when GPU is available: MeloTTS GPU.
- High-quality provider: not yet selected; perform blind human listening first.
- Cloud provider: ElevenLabs remains unavailable until a credentialed run
  produces speech and records actual account/model/cost evidence.

## Quality tests still required

Blind listeners should assess intelligibility, authorised speaker similarity,
noise, clicks, metallic or phase artefacts, prosody, pronunciation, emotional
appropriateness, and preference without seeing provider or CPU/GPU labels. Use a
clean authorised real-person reference only after consent and retention approval.
Do not turn those judgements into a claim of biometric identity.
