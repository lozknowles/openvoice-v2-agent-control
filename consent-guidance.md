# Consent and synthetic-media guidance

## Password-protected website beta

The shared password controls access; it is not evidence of permission from a
speaker. Every user must upload or record only their own voice, or a voice whose
speaker has explicitly agreed to this cloning use. Users must not upload voices
captured from calls, broadcasts, social media, meetings or other recordings
merely because those recordings are accessible to them.

Keep every downloaded filename and description marked as synthetic. Do not use
generated speech as identity evidence, for authentication, or in a context that
could reasonably make a listener believe the speaker actually said it. The
website deletes its server-side reference promptly and its output within one
hour, but users remain responsible for copies they download or redistribute.

Use this capability only when one of the following is true:

1. You are cloning your own voice and understand the intended use.
2. The speaker has given explicit permission for this specific cloning and use.
3. The reference is an authorised synthetic fixture whose licence permits the
   test and which is not presented as a real person.

Permission should identify the speaker, operator, intended purpose, permitted
audience, retention period and how consent can be withdrawn. A public recording
is not consent. Employment, family relationship, celebrity status or online
availability is not consent.

Before generation, confirm that the reference contains one speaker, is clean,
contains no sensitive conversation, and is no longer than needed. Whether the
reference is dropped, uploaded or recorded through the microphone, use exactly
one source and record only in private surroundings. After use, clear the browser
recording and remove references and outputs that are no longer required.

Every output must be described as synthetic. Keep the `_synthetic.wav` filename,
its JSON sidecar and the upstream watermark. Do not use generated speech for
impersonation, authentication bypass, fraud, harassment, political deception or
misleading evidence.

For a cloud provider, an existing voice ID is not proof of consent. Confirm that
the account holder is authorised to use that voice for the intended text and
audience before selecting it. This repository does not create or upload voice
clones to ElevenLabs. Adding such a workflow would require a separate consent,
retention, and security review.

The bundled qualification fixture is generated locally by the MIT-licensed
MeloTTS British English base speaker. It tests the pipeline without asserting a
human identity or human consent. It does not qualify cloning of any real person.
