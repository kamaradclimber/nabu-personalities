"""Targeting the Assist Voice device from the personality services."""

from __future__ import annotations

import socket

import pytest
from homeassistant.components import search
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import entity_sources as get_entity_sources
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry

from custom_components.assist_voice.const import (
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_STT_ENTITY,
    DOMAIN,
    SERVICE_ROTATE,
    SERVICE_SET_PERSONALITY,
)

BACKENDS = ["conversation.personality_one", "conversation.personality_two"]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry, backends: list[str] = BACKENDS
) -> None:
    for backend in backends:
        hass.states.async_set(backend, "unknown", {"friendly_name": backend})
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "backends": list(backends)}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)


def _device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert devices, "no Assist Voice device registered for the entry"
    return devices[0].id


async def _foreign_device_id(hass: HomeAssistant) -> str:
    other_entry = MockConfigEntry(domain="other", title="Other")
    other_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={("other", "device")},
    )
    return device.id


async def test_rotate_without_target_rotates_all_entries(hass, entry, socket_enabled):
    await _setup_entry(hass, entry)
    router = entry.runtime_data.router
    assert router.current == BACKENDS[0]

    await hass.services.async_call(DOMAIN, SERVICE_ROTATE, {}, blocking=True)
    assert router.current == BACKENDS[1]


async def test_rotate_targeting_the_device(hass, entry, socket_enabled):
    await _setup_entry(hass, entry)
    router = entry.runtime_data.router
    device_id = _device_id(hass, entry)

    await hass.services.async_call(
        DOMAIN, SERVICE_ROTATE, {"device_id": device_id}, blocking=True
    )
    assert router.current == BACKENDS[1]


async def test_rotate_targeting_a_device_entity(hass, entry, socket_enabled):
    await _setup_entry(hass, entry)
    router = entry.runtime_data.router

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ROTATE,
        {"entity_id": "button.assist_voice"},
        blocking=True,
    )
    assert router.current == BACKENDS[1]


async def test_rotate_targeting_a_foreign_device_fails(hass, entry, socket_enabled):
    await _setup_entry(hass, entry)
    router = entry.runtime_data.router
    foreign_device_id = await _foreign_device_id(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_ROTATE, {"device_id": foreign_device_id}, blocking=True
        )
    assert router.current == BACKENDS[0]


async def test_set_personality_targeting_the_device(hass, entry, socket_enabled):
    await _setup_entry(hass, entry)
    router = entry.runtime_data.router
    device_id = _device_id(hass, entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_PERSONALITY,
        {"personality": BACKENDS[1], "device_id": device_id},
        blocking=True,
    )
    assert router.current == BACKENDS[1]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_PERSONALITY,
            {"personality": "conversation.not_configured", "device_id": device_id},
            blocking=True,
        )
    assert router.current == BACKENDS[1]


async def test_set_personality_without_target(hass, entry, socket_enabled):
    await _setup_entry(hass, entry)
    router = entry.runtime_data.router

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_PERSONALITY,
        {"personality": BACKENDS[1]},
        blocking=True,
    )
    assert router.current == BACKENDS[1]


async def test_services_removed_after_last_entry_unload(hass, entry, socket_enabled):
    await _setup_entry(hass, entry)
    assert hass.services.has_service(DOMAIN, SERVICE_ROTATE)
    assert hass.services.has_service(DOMAIN, SERVICE_SET_PERSONALITY)

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, SERVICE_ROTATE)
    assert not hass.services.has_service(DOMAIN, SERVICE_SET_PERSONALITY)


async def test_multiple_entries_share_services_and_honor_targets(
    hass, entry, socket_enabled
):
    await _setup_entry(hass, entry)
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_STT_ENTITY: "stt.test",
            "backends": ["conversation.alpha", "conversation.beta"],
            CONF_LISTEN_HOST: "127.0.0.1",
            CONF_LISTEN_PORT: _free_port(),
        },
    )
    await _setup_entry(
        hass, entry2, backends=["conversation.alpha", "conversation.beta"]
    )
    router1 = entry.runtime_data.router
    router2 = entry2.runtime_data.router

    # A call without a target addresses every entry.
    await hass.services.async_call(DOMAIN, SERVICE_ROTATE, {}, blocking=True)
    assert router1.current == BACKENDS[1]
    assert router2.current == "conversation.beta"

    # A targeted call only addresses the targeted entry.
    await hass.services.async_call(
        DOMAIN, SERVICE_ROTATE, {"device_id": _device_id(hass, entry2)}, blocking=True
    )
    assert router2.current == "conversation.alpha"
    assert router1.current == BACKENDS[1]

    # Unloading one entry leaves the services registered for the other.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass.services.has_service(DOMAIN, SERVICE_ROTATE)
    await hass.services.async_call(DOMAIN, SERVICE_ROTATE, {}, blocking=True)
    assert router2.current == "conversation.beta"

    assert await hass.config_entries.async_unload(entry2.entry_id)
    assert not hass.services.has_service(DOMAIN, SERVICE_ROTATE)


async def test_automation_with_target_is_linked_to_the_device(
    hass, entry, socket_enabled
):
    """Automations targeting the device show up as related on the device page."""
    await _setup_entry(hass, entry)
    device_id = _device_id(hass, entry)

    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "rotate linked",
                    "triggers": [{"platform": "event", "event_type": "a"}],
                    "actions": [
                        {
                            "action": "assist_voice.rotate",
                            "target": {"device_id": device_id},
                        }
                    ],
                },
                {
                    "alias": "rotate unlinked",
                    "triggers": [{"platform": "event", "event_type": "b"}],
                    "actions": [{"action": "assist_voice.rotate"}],
                },
            ]
        },
    )

    searcher = search.Searcher(hass, get_entity_sources(hass))
    result = searcher.async_search(search.ItemType.DEVICE, device_id)
    assert "automation.rotate_linked" in result.get("automation", set())
    assert "automation.rotate_unlinked" not in result.get("automation", set())
