"""A same-task timeout wrapper around the upstream Speaker ID STT entity."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, AsyncIterator

from homeassistant.components import stt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_RESPONSE_TIMEOUT,
    CONF_SPEAKER_STT,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_SPEAKER_STT,
    GUARDED_STT_ENTITY,
)

_LOGGER = logging.getLogger(__name__)
MAX_REQUEST_SECONDS = 120


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([GuardedSpeakerStt(entry)])


class GuardedSpeakerStt(stt.SpeechToTextEntity):
    """Bound an upstream hang without breaking Speaker ID's task-local context."""

    _attr_name = "Speaker ID (timeout protected)"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._attr_unique_id = f"{entry.entry_id}-guarded-stt"
        self.entity_id = GUARDED_STT_ENTITY
        self._target_id = entry.data.get(CONF_SPEAKER_STT) or DEFAULT_SPEAKER_STT
        self._response_timeout = entry.data.get(
            CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT
        )

    def _target(self) -> stt.SpeechToTextEntity | None:
        # Require the actual upstream integration, even after entity renames. This
        # prevents recursion and accidentally bypassing speaker identification.
        record = er.async_get(self.hass).async_get(self._target_id)
        if record is None or record.platform != "speaker_id":
            return None
        target = stt.async_get_speech_to_text_entity(self.hass, self._target_id)
        return target if target is not None and target is not self else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def state_changed(event: Event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._target_id], state_changed)
        )

    @property
    def available(self) -> bool:
        target = self._target()
        return target is not None and target.available

    @property
    def supported_languages(self) -> list[str]:
        target = self._target()
        return target.supported_languages if target else []

    @property
    def supported_formats(self) -> list[stt.AudioFormats]:
        target = self._target()
        return target.supported_formats if target else []

    @property
    def supported_codecs(self) -> list[stt.AudioCodecs]:
        target = self._target()
        return target.supported_codecs if target else []

    @property
    def supported_bit_rates(self) -> list[stt.AudioBitRates]:
        target = self._target()
        return target.supported_bit_rates if target else []

    @property
    def supported_sample_rates(self) -> list[stt.AudioSampleRates]:
        target = self._target()
        return target.supported_sample_rates if target else []

    @property
    def supported_channels(self) -> list[stt.AudioChannels]:
        target = self._target()
        return target.supported_channels if target else []

    @property
    def audio_processing(self) -> stt.SpeechAudioProcessing:
        target = self._target()
        return target.audio_processing if target else stt.DEFAULT_AUDIO_PROCESSING

    async def async_process_audio_stream(
        self, metadata: stt.SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> stt.SpeechResult:
        target = self._target()
        if target is None or not target.available:
            _LOGGER.warning("Speaker ID STT entity %s is unavailable", self._target_id)
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            # Unlike wait_for/create_task, timeout cancels this very task, so the
            # upstream ContextVar remains visible to the conversation stage.
            loop = asyncio.get_running_loop()
            max_deadline = loop.time() + MAX_REQUEST_SECONDS
            async with asyncio.timeout_at(max_deadline) as deadline:

                async def tracked_audio() -> AsyncIterator[bytes]:
                    async for chunk in stream:
                        yield chunk
                    # Speech itself may take time: start the shorter response
                    # timeout only when the input audio has finished.
                    deadline.reschedule(
                        min(max_deadline, loop.time() + self._response_timeout)
                    )

                return await target.internal_async_process_audio_stream(
                    metadata, tracked_audio()
                )
        except TimeoutError:
            _LOGGER.warning("Speaker ID STT timed out")
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)
