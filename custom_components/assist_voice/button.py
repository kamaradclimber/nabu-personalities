"""Expose personality rotation as a device control."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .conversation import PersonalityRouter
from .device import assist_voice_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a button that rotates new conversations to another personality."""
    router: PersonalityRouter = entry.runtime_data.router
    async_add_entities([RotatePersonalityButton(entry.entry_id, router)])


class RotatePersonalityButton(ButtonEntity):
    """Rotate to a different configured personality when pressed."""

    _attr_should_poll = False
    _attr_icon = "mdi:account-switch"
    _attr_translation_key = "rotate_personality"

    def __init__(self, entry_id: str, router: PersonalityRouter) -> None:
        self._attr_unique_id = f"{entry_id}-rotate-personality"
        self._attr_device_info = assist_voice_device_info(entry_id)
        self._router = router

    @property
    def available(self) -> bool:
        """Rotation requires an alternative backend."""
        return len(self._router.backends) > 1

    async def async_press(self) -> None:
        """Select a different personality for future conversations."""
        # async_press runs as an entity service call, which set the context of
        # the call; pass it on so the personality change is attributed to it.
        await self._router.rotate(self._context)
