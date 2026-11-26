"""Independent Home Assistant Wyoming STT bridge and conversation router."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ENTITY_MATCH_ALL, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.helpers.typing import ConfigType
from wyoming.server import AsyncTcpServer

from .bridge import BridgeHandler
from .const import (
    ATTR_PERSONALITY,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_STT_ENTITY,
    DOMAIN,
    SERVICE_ROTATE,
    SERVICE_SET_PERSONALITY,
)
from .conversation import PersonalityRouter
from .frontend import async_setup as async_setup_frontend

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [
    Platform.BUTTON,
    Platform.CONVERSATION,
    Platform.SENSOR,
    Platform.STT,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the optional Lovelace card resource endpoint."""
    await async_setup_frontend(hass)
    return True


@dataclass
class Runtime:
    server: AsyncTcpServer
    router: PersonalityRouter


def _targeted_runtimes(hass: HomeAssistant, call: ServiceCall) -> list[Runtime]:
    """Resolve a service call target to the Assist Voice entries it addresses.

    Services are registered once for all loaded entries. A call without a
    target addresses every entry; a call with a target only the entries whose
    service device or entities are referenced.
    """
    runtimes: dict[str, Runtime] = hass.data.get(DOMAIN, {})
    target = TargetSelection(call.data)
    if not target.has_any_target or ENTITY_MATCH_ALL in target.entity_ids:
        return list(runtimes.values())

    selected = async_extract_referenced_entity_ids(hass, target)
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    entry_ids: set[str] = set()
    for device_id in selected.referenced_devices:
        if (device := device_registry.async_get(device_id)) is not None:
            entry_ids.update(device.config_entries)
    for entity_id in selected.referenced | selected.indirectly_referenced:
        if (entity := entity_registry.async_get(entity_id)) is not None and (
            entity.config_entry_id is not None
        ):
            entry_ids.add(entity.config_entry_id)
    return [
        runtimes[entry_id] for entry_id in sorted(entry_ids) if entry_id in runtimes
    ]


async def _async_rotate(call: ServiceCall) -> None:
    """Rotate the personality of each targeted Assist Voice entry."""
    runtimes = _targeted_runtimes(call.hass, call)
    if not runtimes:
        raise ServiceValidationError(
            "No Assist Voice device is targeted; target the Assist Voice device"
            " or one of its entities"
        )
    for runtime in runtimes:
        await runtime.router.rotate()


async def _async_set_personality(call: ServiceCall) -> None:
    """Select the personality of each targeted Assist Voice entry."""
    personality = call.data[ATTR_PERSONALITY]
    runtimes = _targeted_runtimes(call.hass, call)
    routers = [
        runtime.router for runtime in runtimes if personality in runtime.router.backends
    ]
    if not routers:
        raise ServiceValidationError(
            f"{personality} is not a configured personality of a targeted"
            " Assist Voice device"
        )
    for router in routers:
        await router.select_personality(personality)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    router = PersonalityRouter(hass, entry)
    await router.load()
    server = AsyncTcpServer(entry.data[CONF_LISTEN_HOST], entry.data[CONF_LISTEN_PORT])
    try:
        await server.start(
            partial(
                BridgeHandler,
                hass=hass,
                entity_id=entry.data[CONF_STT_ENTITY],
                slots=asyncio.Semaphore(16),
            )
        )
    except OSError as err:
        raise ConfigEntryNotReady("Cannot listen on the Wyoming bridge port") from err
    entry.runtime_data = Runtime(server, router)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await server.stop()
        raise

    runtimes: dict[str, Runtime] = hass.data.setdefault(DOMAIN, {})
    runtimes[entry.entry_id] = entry.runtime_data

    @callback
    def _discard_runtime() -> None:
        runtimes.pop(entry.entry_id, None)
        if not runtimes:
            hass.services.async_remove(DOMAIN, SERVICE_ROTATE)
            hass.services.async_remove(DOMAIN, SERVICE_SET_PERSONALITY)

    entry.async_on_unload(_discard_runtime)

    if not hass.services.has_service(DOMAIN, SERVICE_ROTATE):
        hass.services.async_register(DOMAIN, SERVICE_ROTATE, _async_rotate)
    if not hass.services.has_service(DOMAIN, SERVICE_SET_PERSONALITY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_PERSONALITY,
            _async_set_personality,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_PERSONALITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=Platform.CONVERSATION)
                    ),
                    **cv.TARGET_SERVICE_FIELDS,
                }
            ),
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.server.stop()
    return True
