# Assist Voice Bridge and Router

A personal Home Assistant integration built for my voice setup. It bridges HA speech-to-text through Wyoming, provides a timeout-protected entity for the Assist Speaker ID integration, and routes conversations to a selectable personality.

This is intended for my own use, not presented as a generic, production-supported integration. If others are interested, PRs are welcome; I can make it more generic around concrete use cases.

## How it fits together

- The Wyoming bridge proxies requests to a configured Home Assistant STT entity.
- The guarded STT entity delegates to the configured Speaker ID STT entity.
- The personality router delegates conversations to one of the configured conversation entities.
- The pipeline topology sensor and optional Lovelace card show the preferred Assist pipeline and these handoffs.

This is designed to work with the unmodified [Assist Speaker ID](https://github.com/witold-gren/home-assistant-assist-speaker-id) integration and its separately deployed server.

## Setup

1. Add Assist Voice and select the upstream HA STT entity and one or more conversation backends. The Wyoming listener defaults to `0.0.0.0:10352`.
2. Configure the Speaker ID integration to use this Wyoming bridge for STT, and point its conversation agent at the Assist Voice personality router.
3. In the Assist pipeline, use `stt.assist_voice_speaker_id` for STT and the Speaker ID conversation agent for conversation handling. Reconfigure Assist Voice to change its selected entities or listener settings.

Do not select Speaker ID STT as the bridge's upstream STT entity, or the Speaker ID conversation agent as a router backend; both would create a loop.

The guarded STT entity applies a 120-second maximum request timeout and defaults to 30 seconds waiting for a result after audio ends. That response timeout can be configured from 5 to 90 seconds. A timeout returns an STT error, never a fallback transcript.

## Personality controls

All Assist Voice entities are grouped under one **Assist Voice** service device. Use the **Rotate personality** button or `assist_voice.rotate` to randomly select a different configured backend. Clicking a personality chip in the pipeline card, or calling `assist_voice.set_personality` with the `personality` conversation entity ID, selects a specific backend. Both actions persist across restarts.

Both services accept a target: the Assist Voice device, or any of its entities. Automations that use the target are shown as related on the device page; without a target every configured Assist Voice device is addressed instead. A target that resolves to no Assist Voice device fails the call instead of rotating something else.

The **Current personality** diagnostic sensor displays the selected backend's friendly name. Its attributes expose the selected backend ID, all configured backend IDs, and an ID-to-name mapping. Existing sessions stay with their original backend; session mappings are in memory, so start a new conversation after restarting HA or reloading the integration. Changing personality does not change the TTS engine or voice.

## Pipeline visualization

The **Voice pipeline topology** diagnostic sensor describes Home Assistant's preferred Assist pipeline and refreshes once a minute. It does not discover pipelines assigned individually to satellites.

To use the clickable Lovelace card, add this resource under **Settings → Dashboards → Resources**:

- URL: `/api/assist_voice/pipeline-card.js`
- Resource type: **JavaScript Module**

Then add this card to a dashboard:

```yaml
type: custom:assist-voice-pipeline-card
```

Pipeline stage nodes open entity details. Personality chips select a backend, and the card's button rotates to a random one. The STT handoff shows the timeout limits, the Speaker ID integration's HTTP call to its server, and the server's Wyoming handoff to the configured HA STT provider. The integration's brand assets live in `custom_components/assist_voice/brand/`.

## Security and limitations

Wyoming has no authentication or encryption. Restrict access to the listener at the network level and never expose it to the Internet. The Speaker ID HTTP API also needs its own token and network restrictions.

Test the complete pipeline: audio-processing preferences may not pass through the Speaker ID STT entity. The integration provides no failover, the router does not advertise streaming support, and Prefer Local Intents may bypass the router. At the tested Speaker ID v0.3.0 revision, its STT client ignores Wyoming error events; the guarded entity bounds the resulting wait. Very short audio may also trigger an upstream VAD error. This setup has not been production-validated.

## Development

Python 3.14; tests use Home Assistant and `pytest-homeassistant` pinned to 2026.11.2.

```sh
uv venv --python 3.14
uv pip install -r requirements-test.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest \
  -p pytest_homeassistant.bootstrap -p pytest_asyncio.plugin -p pytest_socket
```

For optional upstream Speaker ID proxy/pipeline tests, set `ASSIST_SPEAKER_SOURCE` to a checkout of v0.3.0 commit `e6e5e5ce80861f2ef8f4bc84525744abec7de0c2` before running the test command.
