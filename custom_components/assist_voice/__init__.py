"""Independent Home Assistant Wyoming STT bridge and conversation router."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from wyoming.server import AsyncTcpServer

from .bridge import BridgeHandler
from .const import (
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_STT_ENTITY,
    DOMAIN,
    SERVICE_ROTATE,
)
from .conversation import PersonalityRouter

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.CONVERSATION, Platform.STT]


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

    hass.services.async_register(DOMAIN, SERVICE_ROTATE, rotate)
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, SERVICE_ROTATE))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.server.stop()
    return True
