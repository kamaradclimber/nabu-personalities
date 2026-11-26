"""The current-personality sensor reflects router selection changes."""

from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component


async def test_sensor_tracks_current_personality(hass, entry, socket_enabled):
    assert await async_setup_component(hass, "conversation", {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    sensor_id = er.async_get(hass).async_get_entity_id(
        "sensor", "assist_voice", f"{entry.entry_id}-personality"
    )
    assert sensor_id is not None
    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state == "agent_a"
    assert state.attributes["backends"] == ["agent_a", "agent_b"]

    await hass.services.async_call("assist_voice", "rotate", {}, blocking=True)
    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state == entry.runtime_data.router.current == "agent_b"

    assert await hass.config_entries.async_unload(entry.entry_id)
