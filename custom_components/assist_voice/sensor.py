"""Expose personality diagnostics and an Assist pipeline topology sensor."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components import assist_pipeline
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_RESPONSE_TIMEOUT,
    CONF_SPEAKER_STT,
    CONF_STT_ENTITY,
    DEFAULT_LISTEN_HOST,
    DEFAULT_LISTEN_PORT,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_SPEAKER_STT,
    GUARDED_STT_ENTITY,
)
from .conversation import PersonalityRouter
from .device import assist_voice_device_info
from .stt import MAX_REQUEST_SECONDS

SCAN_INTERVAL = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add diagnostic entities for the selected personality and pipeline."""
    router: PersonalityRouter = entry.runtime_data.router
    async_add_entities(
        [
            CurrentPersonalitySensor(entry.entry_id, router),
            PipelineTopologySensor(entry, router),
        ]
    )


def _entity_name(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Resolve an entity's user-facing name, with registry and ID fallbacks."""
    if entity_id is None:
        return None
    if (state := hass.states.get(entity_id)) is not None:
        return state.name
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is not None:
        return registry_entry.name or registry_entry.original_name or entity_id
    return entity_id


def _entity_details(
    hass: HomeAssistant, entity_id: str | None
) -> dict[str, str] | None:
    """Return an entity ID and its display name, if an entity is configured."""
    if entity_id is None:
        return None
    return {"entity_id": entity_id, "name": _entity_name(hass, entity_id) or entity_id}


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
        return _entity_name(self.hass, self._router.current) or self._router.current

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "current_backend": self._router.current,
            "backends": list(self._router.backends),
            "backend_names": {
                backend: _entity_name(self.hass, backend) or backend
                for backend in self._router.backends
            },
        }

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
    def _async_write_state(self, context: Context | None = None) -> None:
        # Attribute the state change to the call that selected the personality.
        if context is not None:
            self.async_set_context(context)
        self.async_write_ha_state()


class PipelineTopologySensor(SensorEntity):
    """Describe the preferred Assist pipeline and the integration's routing paths."""

    _attr_should_poll = True
    _attr_translation_key = "pipeline_topology"
    _attr_icon = "mdi:graph-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, router: PersonalityRouter) -> None:
        self._attr_unique_id = f"{entry.entry_id}-pipeline-topology"
        self._attr_device_info = assist_voice_device_info(entry.entry_id)
        self.entity_id = "sensor.assist_voice_pipeline_topology"
        self._entry = entry
        self._router = router
        self._pipeline: assist_pipeline.Pipeline | None = None

    @property
    def available(self) -> bool:
        """The sensor is available when Assist has a preferred pipeline."""
        return self._pipeline is not None

    @property
    def native_value(self) -> str | None:
        """Use the pipeline name as the sensor state."""
        return self._pipeline.name if self._pipeline is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the stages and Assist Voice paths for a dashboard diagram."""
        if self._pipeline is None:
            return {}

        pipeline = self._pipeline
        stages = [
            {
                "stage": "Wake word",
                "entity": _entity_details(self.hass, pipeline.wake_word_entity),
                "wake_word_id": pipeline.wake_word_id,
            },
            {
                "stage": "Speech-to-text",
                "entity": _entity_details(self.hass, pipeline.stt_engine),
                "language": pipeline.stt_language,
            },
            {
                "stage": "Conversation",
                "entity": _entity_details(self.hass, pipeline.conversation_engine),
                "language": pipeline.conversation_language,
            },
            {
                "stage": "Text-to-speech",
                "entity": _entity_details(self.hass, pipeline.tts_engine),
                "language": pipeline.tts_language,
                "voice": pipeline.tts_voice,
            },
        ]
        stage_labels = [
            f"{stage['stage']}: "
            f"{stage['entity']['name'] if stage['entity'] else 'not configured'}"
            for stage in stages
        ]
        speaker_stt = self._entry.data.get(CONF_SPEAKER_STT) or DEFAULT_SPEAKER_STT
        current_backend = self._router.current
        return {
            "pipeline_id": pipeline.id,
            "pipeline_name": pipeline.name,
            "pipeline_language": pipeline.language,
            "stages": stages,
            "topology": " → ".join(stage_labels),
            "assist_voice": {
                "stt_path_configured": pipeline.stt_engine == GUARDED_STT_ENTITY,
                "timeouts": {
                    "max_request_seconds": MAX_REQUEST_SECONDS,
                    "response_after_audio_seconds": self._entry.data.get(
                        CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT
                    ),
                },
                "guarded_stt": _entity_details(self.hass, GUARDED_STT_ENTITY),
                "speaker_id_stt": _entity_details(self.hass, speaker_stt),
                "wyoming_bridge": {
                    "host": self._entry.data.get(CONF_LISTEN_HOST, DEFAULT_LISTEN_HOST),
                    "port": self._entry.data.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT),
                    "upstream_stt": _entity_details(
                        self.hass, self._entry.data[CONF_STT_ENTITY]
                    ),
                },
                "personality_router": {
                    "entity": _entity_details(self.hass, self._router.entity_id),
                    "pipeline_uses_router_directly": (
                        pipeline.conversation_engine == self._router.entity_id
                    ),
                    "current_backend": _entity_details(self.hass, current_backend),
                    "backends": [
                        _entity_details(self.hass, backend)
                        for backend in self._router.backends
                    ],
                },
                "tts_changes_with_personality": False,
            },
        }

    async def async_added_to_hass(self) -> None:
        """Load the current pipeline and listen for personality rotations."""
        await super().async_added_to_hass()
        self._router.async_add_personality_listener(self._async_write_state)
        await self.async_update()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from router updates."""
        self._router.async_remove_personality_listener(self._async_write_state)
        await super().async_will_remove_from_hass()

    @callback
    def _async_write_state(self, context: Context | None = None) -> None:
        # Attribute the state change to the call that selected the personality.
        if context is not None:
            self.async_set_context(context)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Refresh the preferred pipeline so configuration edits appear in the view."""
        try:
            self._pipeline = assist_pipeline.async_get_pipeline(self.hass)
        except assist_pipeline.PipelineNotFound:
            self._pipeline = None
