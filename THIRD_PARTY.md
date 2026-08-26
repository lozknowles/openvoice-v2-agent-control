# Third-party provenance

This repository orchestrates, but does not vendor, the following projects:

- MyShell OpenVoice, MIT licence, pinned Git commit recorded in
  `UPSTREAM.lock.json`.
- MyShell MeloTTS, MIT licence, pinned Git commit recorded in
  `UPSTREAM.lock.json`.
- MyShell OpenVoice V2 and MeloTTS model repositories on Hugging Face, pinned by
  immutable revision and hashed after download.
- PyTorch and torchaudio official CUDA 12.1 wheels, pinned versions recorded in
  `UPSTREAM.lock.json`.
- WavMark model `M4869/WavMark`, pinned by immutable revision and hashed after
  download, used by the upstream `wavmark` package to preserve watermarking.
- PyAV 10, FFmpeg 6.1.2 and NumPy 1.22.4 exact conda-forge builds, installed
  only in the isolated environment.
- Miniforge and conda-forge Python packages, isolated beneath `/fast`.

Model and dataset licences remain applicable independently of this integration
licence. Consent to clone a human voice is a separate requirement and is never
implied by software or model licensing.
