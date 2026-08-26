# ElevenLabs qualification

## Status

**UNQUALIFIED.** No `ELEVENLABS_API_KEY` was present and no live ElevenLabs
speech was generated. The adapter, request validation, explicit cloud gate, and
stream assembly are covered by tests using a mock transport. Those tests do not
qualify audio quality, account access, model availability, latency, cost, voice
permissions, or production reliability.

## Official API findings

The current official API exposes standard text-to-speech conversion and a
streaming endpoint. Authentication uses the `xi-api-key` header. Voice settings
include stability, similarity boost, style, speaker boost, and speed; documented
speed is constrained to the provider's accepted range. Models and features vary,
so callers must retain the returned model/provider identity.

Official references inspected on 2026-08-26:

- [Create speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)
- [Stream speech](https://elevenlabs.io/docs/api-reference/text-to-speech/stream)
- [Authentication](https://elevenlabs.io/docs/api-reference/authentication)
- [Voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/get)
- [Model overview](https://elevenlabs.io/docs/overview/models)
- [Pronunciation dictionaries](https://elevenlabs.io/docs/api-reference/pronunciation-dictionaries)

The service documents Instant Voice Cloning and Professional Voice Cloning. Its
guidance requires the user to have the right and consent to clone the voice.
This repository intentionally does not implement voice creation or reference
upload:

- [Voice cloning overview](https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning)
- [Instant Voice Cloning API guide](https://elevenlabs.io/docs/eleven-api/guides/how-to/voices/instant-voice-cloning)

## Agents and MCP

ElevenLabs Agents can call an external MCP server over supported remote
transports, subject to workspace opt-in, approvals, and product restrictions.
ElevenLabs also documents hosted agent tooling for MCP clients. These are agent
integration capabilities, not evidence that the TTS adapter has synthesized
audio. The official documentation states that external MCP use is not available
for Zero Retention Mode or HIPAA environments.

- [ElevenLabs Agents overview](https://elevenlabs.io/docs/eleven-agents/overview/)
- [External MCP tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/mcp)
- [Agent tooling and hosted MCP](https://elevenlabs.io/docs/eleven-api/resources/agent-tooling)

## Adapter boundary

The adapter:

1. Requires `provider="elevenlabs"` and `allow_cloud=True`.
2. Reads `ELEVENLABS_API_KEY` at runtime and never serialises it.
3. Requires an existing authorised voice ID.
4. Calls the official streaming endpoint and writes the returned audio to the
   requested synthetic output path.
5. Maps portable speed/style settings only when supported.
6. Records model identity, latency, first-chunk time, bytes, retry count, and
   provider response metadata available without exposing secrets.

It does not upload audio, create a clone, choose a cloud provider through
`auto`, place a key in a URL or command line, or claim a cloud cost from a local
estimate.

## Pricing and cost evidence

The public API pricing page inspected on 2026-08-26 listed indicative rates of
USD 0.10 per 1,000 characters for v2/v3 speech and USD 0.05 per 1,000 characters
for Flash/Turbo, excluding tax and subject to plan/model changes. This snapshot
is recorded in `speech/benchmarks/elevenlabs-pricing-2026-08-26.json` and is not
an invoice. The subscription endpoint can expose usage and overage information,
but a credentialed account run is required to establish actual cost.

- [API pricing](https://elevenlabs.io/pricing/api)
- [Subscription usage endpoint](https://elevenlabs.io/docs/api-reference/user/subscription/get)

## Remaining qualification

With a separately provisioned restricted API key and authorised existing voice
ID, run the fixed corpus explicitly against `elevenlabs`. Record model and voice
IDs, first chunk, total latency, duration, characters, bytes, retries, account
usage delta, and the provider response/request identifiers. Then perform the
same blind human listening exercise used for local samples. Until that succeeds,
ElevenLabs must remain unavailable rather than failed-over automatically.
