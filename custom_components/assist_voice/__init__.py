"""Independent Home Assistant Wyoming STT bridge and conversation router."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
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

    async def rotate(call: ServiceCall) -> None:
        await router.rotate()

    async def set_personality(call: ServiceCall) -> None:
        await router.select_personality(call.data[ATTR_PERSONALITY])

    hass.services.async_register(DOMAIN, SERVICE_ROTATE, rotate)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PERSONALITY,
        set_personality,
        schema=vol.Schema(
            {
                vol.Required(ATTR_PERSONALITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=Platform.CONVERSATION,
                        include_entities=router.backends,
                    )
                )
            }
        ),
    )
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, SERVICE_ROTATE))
    entry.async_on_unload(
        lambda: hass.services.async_remove(DOMAIN, SERVICE_SET_PERSONALITY)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.server.stop()
    return True
