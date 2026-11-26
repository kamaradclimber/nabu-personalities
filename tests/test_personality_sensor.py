"""Assist Voice device controls and personality diagnostics."""

from homeassistant.components import assist_pipeline
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import EntityCategory
from homeassistant.setup import async_setup_component

from custom_components.assist_voice.const import DOMAIN


async def test_sensor_tracks_named_personality_and_device_entities(
    hass, entry, socket_enabled, hass_client_no_auth
):
    assert await async_setup_component(hass, "conversation", {})
    backend_ids = ["conversation.personality_one", "conversation.personality_two"]
    backend_names = ["Personality One", "Personality Two"]
    for entity_id, name in zip(backend_ids, backend_names, strict=True):
        hass.states.async_set(entity_id, "unknown", {"friendly_name": name})

    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "backends": backend_ids}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    client = await hass_client_no_auth()
    card_response = await client.get("/api/assist_voice/pipeline-card.js")
    assert card_response.status == 200
    assert "javascript" in card_response.content_type
    assert "assist-voice-pipeline-card" in await card_response.text()

    entity_registry = er.async_get(hass)
    sensor_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}-personality"
    )
    button_id = entity_registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}-rotate-personality"
    )
    topology_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}-pipeline-topology"
    )
    assert sensor_id is not None
    assert button_id is not None
    assert topology_id == "sensor.assist_voice_pipeline_topology"

    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state == backend_names[0]
    assert state.attributes["current_backend"] == backend_ids[0]
    assert state.attributes["backends"] == backend_ids
    assert state.attributes["backend_names"] == dict(zip(backend_ids, backend_names))

    pipeline = assist_pipeline.async_get_pipeline(hass)
    topology_state = hass.states.get(topology_id)
    assert topology_state is not None
    assert topology_state.state == pipeline.name
    assert topology_state.attributes["pipeline_id"] == pipeline.id
    assert topology_state.attributes["pipeline_name"] == pipeline.name
    assert [stage["stage"] for stage in topology_state.attributes["stages"]] == [
        "Wake word",
        "Speech-to-text",
        "Conversation",
        "Text-to-speech",
    ]
    assert topology_state.attributes["assist_voice"]["timeouts"] == {
        "max_request_seconds": 120,
        "response_after_audio_seconds": 30,
    }
    assert (
        topology_state.attributes["assist_voice"]["personality_router"][
            "current_backend"
        ]["entity_id"]
        == backend_ids[0]
    )

    await hass.services.async_call(
        "button", "press", {"entity_id": button_id}, blocking=True
    )
    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state == backend_names[1]
    assert state.attributes["current_backend"] == backend_ids[1]
    topology_state = hass.states.get(topology_id)
    assert topology_state is not None
    assert (
        topology_state.attributes["assist_voice"]["personality_router"][
            "current_backend"
        ]["entity_id"]
        == backend_ids[1]
    )

    # Display-name changes on configured backends refresh diagnostic attributes.
    hass.states.async_set(backend_ids[1], "unknown", {"friendly_name": "Updated Two"})
    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state == "Updated Two"
    assert state.attributes["backend_names"][backend_ids[1]] == "Updated Two"

    sensor_entry = entity_registry.async_get(sensor_id)
    assert sensor_entry is not None
    assert sensor_entry.entity_category == EntityCategory.DIAGNOSTIC

    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.entry_type == DeviceEntryType.SERVICE
    config_entry_entities = er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    )
    assert len(config_entry_entities) == 5
    assert {entity.device_id for entity in config_entry_entities} == {device.id}

    assert await hass.config_entries.async_unload(entry.entry_id)
