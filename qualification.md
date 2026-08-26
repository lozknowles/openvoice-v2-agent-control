# hpubuntu qualification, 2026-08-26

## Verdict

**PARTIAL overall; CPU and GPU functional qualification PASS.**

The fixed British-English pipeline completed on CPU and the Quadro P5000, all
three synthetic samples retained and decoded the upstream `@MyShell` watermark,
ASR intelligibility and gross-signal checks passed, and protected workloads
remained healthy. The overall verdict is PARTIAL because the authorised
reference was a locally generated synthetic MeloTTS fixture, not a real person's
voice, and no independent human listening was performed. Model-internal speaker
embedding cosine values are recorded only as a proxy; they do not prove
subjective speaker similarity.

## Authoritative evidence

- Agent Control Run: `run-908f817d-9235-40dd-9650-c0e4db75d4ff`
- Run status: `SUCCEEDED` (all six steps succeeded)
- Evidence directory: `/fast/qualification/openvoice-v2-20260826T183239Z`
- OpenVoice upstream: `74a1d147b17a8c3092dd5430504bd83ef6c7eb23`
- MeloTTS upstream: `209145371cff8fc3bd60d7be902ea69cbdb7965a`
- Agent Control source base observed by the run:
  `31d9c2378a23d37df8c8a29bd752c30752383c74`

Audio remains private outside Git. The evidence directory contains the
synthetic fixture and outputs, so it must not be pushed or attached to issues.

## Host and installation

| Item | Observed result |
| --- | --- |
| CPU | Intel Core i7-7700HQ, 4 cores / 8 threads |
| RAM | 62 GiB total; about 51 GiB available at initial inventory |
| Storage | about 658 GiB free on `/fast` at initial inventory |
| GPU | NVIDIA Quadro P5000, 16,384 MiB, compute capability 6.1 |
| Driver / system CUDA | 580.173.02 / CUDA toolkit 12.0; unchanged |
| Isolated Python | 3.9.23 at `/fast/venvs/openvoice-v2-py39` |
| PyTorch | 2.5.1+cu121; live CUDA tensor and `sm_60` support observed |
| OpenVoice / MeloTTS | 0.0.0 / 0.1.2 |
| UniDic / WavMark | 1.1.0 / 0.0.3, full dictionary and pinned model present |
| NumPy / PyAV | 1.22.4 / 10.0.0 in the isolated conda environment |
| Checkpoint manifest | 26 allow-listed files with SHA-256 records |

The official OpenVoice checkpoint S3 URL in the upstream documentation returned
404 during inspection. Checkpoints were therefore downloaded from the official
`myshell-ai/OpenVoiceV2` Hugging Face repository at the immutable revision in
`UPSTREAM.lock.json`; no mirror was used. PyAV and FFmpeg are conda-forge packages
inside the isolated environment. A separately hashed packaging-only patch moves
OpenVoice's NumPy metadata from 1.22.0 to 1.22.4 so the exact PyAV 10 build is
satisfiable; the pinned upstream runtime code remains unchanged.

## Fixed British-English comparison

| Sentence | CPU seconds / RTF / WER | GPU seconds / RTF / WER |
| --- | --- | --- |
| The quick brown fox... | 12.925 / 2.953 / 0.000 | 4.015 / 0.917 / 0.000 |
| At half past seven... | 14.668 / 3.037 / 0.000 | 0.884 / 0.183 / 0.000 |
| Clear speech should... | 17.379 / 3.099 / 0.0714 | 1.315 / 0.234 / 0.0714 |
| Mean | 14.991 / 3.030 / 0.0238 | 2.071 / 0.445 / 0.0238 |

The first GPU generation includes warm-up work. CPU and GPU WAV hashes differ,
as expected. All six outputs decoded `@MyShell`; no output clipped. The internal
reference-embedding cosine ranges were 0.8461-0.8693 on CPU and 0.8564-0.8796 on
GPU. These values are not an independent speaker-verification result.

GPU model loading took 8.984 seconds. The conservative guard observed a peak
1,646 MiB of new VRAM and a peak total of 8,585 MiB; the finer process monitor
observed a 1,550 MiB process peak and at least 7,756 MiB free. The guard did not
abort and the live CUDA tensor probe returned 496.0.

## Safety and interface

The final preflight and every guarded step monitored these existing user units:

- `cartoon-collingham-kokoro-gpu.service`
- `lincoln-course-match-ocr.service`
- `llama-coder.service`
- `llama-server.service`
- `localwalks-imageid-staging-api.service`
- `localwalks-imageid-staging-worker.service`
- `localwalks-imageid.service`

They remained active, both llama health endpoints stayed `OK`, and the three
baseline GPU PIDs remained present. No matching OASIS unit or process was
observed during inventory. Nothing was stopped, restarted, upgraded, deployed,
or exposed publicly.

The Gradio interface was smoke-tested at `http://127.0.0.1:17861`. Socket
inspection proved a loopback-only listener; the required reference, text,
language, output-name and consent fields were present. The test process was then
stopped and the port was verified closed. No resident service address is
enabled, no schedule exists, and Gradio sharing is disabled.

## Remaining limitations

- Independent, consented human listening is still required to assess naturalness,
  speaker similarity, background noise and audible artefacts.
- A separately authorised real-person reference is required before making any
  claim about cloning a human speaker.
- Python 3.9 is end-of-life and is retained only because it is the upstream
  environment target; the capability should remain isolated and optional.
- Only the pinned English MeloTTS model and its documented English accents are
  installed and qualified.
