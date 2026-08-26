# Consent and synthetic-media guidance

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
contains no sensitive conversation, and is no longer than needed. After use,
remove references and outputs that are no longer required.

Every output must be described as synthetic. Keep the `_synthetic.wav` filename,
its JSON sidecar and the upstream watermark. Do not use generated speech for
impersonation, authentication bypass, fraud, harassment, political deception or
misleading evidence.

The bundled qualification fixture is generated locally by the MIT-licensed
MeloTTS British English base speaker. It tests the pipeline without asserting a
human identity or human consent. It does not qualify cloning of any real person.
