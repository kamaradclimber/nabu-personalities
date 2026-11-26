"""Expose the currently selected personality as a sensor entity."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .conversation import PersonalityRouter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One sensor per config entry, following the router's current personality."""
    router: PersonalityRouter = entry.runtime_data.router
    async_add_entities([CurrentPersonalitySensor(entry.entry_id, router)])


class CurrentPersonalitySensor(SensorEntity):
    """Report the backend the router selects for new conversations."""

    _attr_should_poll = False
    _attr_icon = "mdi:account-voice"
    _attr_translation_key = "current_personality"

    def __init__(self, entry_id: str, router: PersonalityRouter) -> None:
        self._attr_unique_id = f"{entry_id}-personality"
        self._router = router

    @property
    def native_value(self) -> str | None:
        return self._router.current

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        return {"backends": list(self._router.backends)}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._router.async_add_personality_listener(self._async_write_state)

    async def async_will_remove_from_hass(self) -> None:
        self._router.async_remove_personality_listener(self._async_write_state)
        await super().async_will_remove_from_hass()

    @callback
    def _async_write_state(self) -> None:
        self.async_write_ha_state()
