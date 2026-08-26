# Samples stay outside Git

The qualification runner writes synthetic audio and JSON sidecars beneath the
operator-supplied `/fast/qualification/.../samples` directory. This tracked
directory contains guidance only.

Never commit or attach:

- reference recordings or microphone captures;
- generated WAV, MP3, FLAC or other audio;
- speaker embeddings or NumPy arrays;
- checkpoints or model caches;
- cloud credentials or API responses containing account data.

Use the private `listening-manifest.json` generated beside each benchmark to
find samples and record human observations. Verify each SHA-256 before review.
Every output is synthetic. OpenVoice outputs retain the upstream `@MyShell`
watermark where decodable; the other local engines do not add one.
