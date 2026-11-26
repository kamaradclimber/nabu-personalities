"""Expose the currently selected personality as a sensor entity."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .conversation import PersonalityRouter
from .device import assist_voice_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One sensor per config entry, following the router's current personality."""
    router: PersonalityRouter = entry.runtime_data.router
    async_add_entities([CurrentPersonalitySensor(entry.entry_id, router)])


class CurrentPersonalitySensor(SensorEntity):
    """Report the friendly name of the backend selected for new conversations."""

    _attr_should_poll = False
    _attr_icon = "mdi:account-voice"
    _attr_translation_key = "current_personality"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry_id: str, router: PersonalityRouter) -> None:
        self._attr_unique_id = f"{entry_id}-personality"
        self._attr_device_info = assist_voice_device_info(entry_id)
        self._router = router

    @property
    def native_value(self) -> str:
        return self._entity_name(self._router.current)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "current_backend": self._router.current,
            "backends": list(self._router.backends),
            "backend_names": {
                backend: self._entity_name(backend) for backend in self._router.backends
            },
        }

    def _entity_name(self, entity_id: str) -> str:
        """Resolve the user-facing name, falling back to registry then entity ID."""
        if (state := self.hass.states.get(entity_id)) is not None:
            return state.name
        registry_entry = er.async_get(self.hass).async_get(entity_id)
        if registry_entry is not None:
            return registry_entry.name or registry_entry.original_name or entity_id
        return entity_id

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._router.async_add_personality_listener(self._async_write_state)
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._router.backends, self._async_backend_state_changed
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        self._router.async_remove_personality_listener(self._async_write_state)
        await super().async_will_remove_from_hass()

    @callback
    def _async_backend_state_changed(self, event: Event) -> None:
        """Refresh names when backend entities are renamed or loaded."""
        self.async_write_ha_state()

    @callback
    def _async_write_state(self) -> None:
        self.async_write_ha_state()
