# Assist Voice Bridge and Router

A small, independent Home Assistant custom integration containing:

- A Wyoming STT server backed by an existing HA STT entity (e.g. NabuCasa).
- A timeout-protected STT entity delegating to the upstream Speaker ID integration.
- A conversation entity routing new conversations to a selected existing agent, with an `assist_voice.rotate` action to choose a different personality.

Designed to work with the **unmodified** [Assist Speaker ID](https://github.com/witold-gren/home-assistant-assist-speaker-id) integration and its separately deployed Wyoming service. Point Speaker ID's STT upstream at this bridge and its speaker-aware conversation agent at the personality router.

**Development status:** not yet production-validated. Do not deploy without reviewing the deployment plan, image, security and remaining tests.

## Configuration

Add Assist Voice as an integration and select an HA STT entity and one or more conversation entities. The default listener is `0.0.0.0:10352`. Reconfigure the integration to change settings. Configure the upstream speaker-aware agent to use the personality router as its target. Do not select the speaker-aware agent itself as a router backend, or Speaker ID STT as the bridge target.

Select `stt.assist_voice_speaker_id` as the test pipeline's STT, not the upstream entity directly. It delegates to `stt.speaker_id_speech_to_text` (or a separately selected, renamed Speaker ID entity). It permits at most 120 seconds for a complete request and defaults to 30 seconds for the response after audio ends. The latter is configurable from 5 to 90 seconds. On timeout it returns an STT error, not a transcript or automatic fallback.

Invoke `assist_voice.rotate` from an HA automation or the Actions developer tool. Rotation requires at least two configured agents and persists across restarts. Assist Voice's entities are grouped under one **Assist Voice** service device. Its **Rotate personality** button selects a different backend for new conversations, and the diagnostic **Current personality** sensor reports the selected backend's friendly name. Sensor attributes include the selected backend entity ID (`current_backend`), all configured backend entity IDs (`backends`), and a mapping from backend IDs to friendly names (`backend_names`). Existing conversations normally remain on their original agent until they expire (24 hours), are evicted, or HA/the integration restarts; after that, start a new conversation. HA-supplied session IDs that are no longer in the router's memory may be treated as new conversations. Agent failures do not trigger an automatic switch. Router attributes also show the selected backend and eligible backends.

The diagnostic **Voice pipeline topology** sensor visualizes Home Assistant's preferred Assist pipeline and the integration's STT/personality routes. It refreshes the preferred pipeline view once a minute. This prototype does not discover pipelines assigned individually to satellites.

To render it as a native Markdown dashboard card, add:

```yaml
type: markdown
title: Voice pipeline
content: |
  {% set entity = 'sensor.assist_voice_pipeline_topology' %}
  {% set voice = state_attr(entity, 'assist_voice') %}
  ## {{ state_attr(entity, 'pipeline_name') }}

  {{ state_attr(entity, 'topology') }}

  {% if voice['stt_path_configured'] %}
  **Assist Voice STT route:** {{ voice['guarded_stt']['name'] }} → {{ voice['speaker_id_stt']['name'] }} → Wyoming ({{ voice['wyoming_bridge']['host'] }}:{{ voice['wyoming_bridge']['port'] }}) → {{ voice['wyoming_bridge']['upstream_stt']['name'] }}
  {% else %}
  **Assist Voice STT route:** not active in this pipeline; it uses a different STT engine.
  {% endif %}

  **Personality router:** {{ voice['personality_router']['entity']['name'] }} → {{ voice['personality_router']['current_backend']['name'] }} (configure the Speaker ID conversation agent to target the router when applicable).
```

The integration's icon and logo are in `custom_components/assist_voice/brand/`. `uv run --with pillow python custom_components/assist_voice/brand/generate.py` regenerates the current simple waveform artwork.

## Security and limitations

Wyoming has no authentication or encryption. The listener exposes your configured STT entity to network clients; restrict access at the network level and do not expose it to the Internet. Stream size, duration and concurrency are limited. Speaker ID's HTTP API needs its own token and network restrictions.

A test pipeline is essential: the upstream Speaker ID STT entity may not carry the target provider's audio-processing preferences through to the satellite. VAD and transcription results can therefore differ from direct NabuCasa STT. At upstream Speaker ID v0.3.0 (`e6e5e5c`), its STT client ignores Wyoming error events and can wait indefinitely if the upstream STT fails. The protected STT entity bounds this wait, and a local end-to-end failure test verifies the mitigation; the upstream issue itself remains unfixed. Very short audio can also trigger an upstream VAD indexing exception. The bridge doesn't provide failover. The router doesn't advertise streaming support. Changing personalities doesn't change the pipeline's TTS voice. Prefer-local-intent handling may bypass the router.

## Development

Python 3.14; tests use Home Assistant's official `pytest-homeassistant` package pinned to 2026.11.2. For the optional upstream proxy and pipeline tests, point `ASSIST_SPEAKER_SOURCE` at a checkout of upstream v0.3.0 commit `e6e5e5ce80861f2ef8f4bc84525744abec7de0c2`.

```sh
uv venv --python 3.14
uv pip install -r requirements-test.txt
ASSIST_SPEAKER_SOURCE=~/github/witold-gren/home-assistant-assist-speaker-id uv run pytest
```

The deployment plans and Kubernetes manifest live separately in `kamaradclimber/nomad-infrastructure/home-assistant/`.
