"""Expose an HA STT entity over Wyoming without modifying the provider."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress

from homeassistant.components import stt
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info
from wyoming.server import AsyncEventHandler

_LOGGER = logging.getLogger(__name__)
ATTRIBUTION = Attribution(
    name="Home Assistant STT bridge", url="https://www.home-assistant.io/"
)
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # approximately 65 seconds of 16 kHz mono PCM
MAX_CHUNK_BYTES = 64 * 1024
MAX_CONNECTION_SECONDS = 120
QUEUE_SIZE = 32


class BridgeError(Exception):
    """Invalid request or unavailable provider."""


def get_target(hass: HomeAssistant, entity_id: str) -> stt.SpeechToTextEntity:
    """Resolve at request time: the cloud integration may load after this one."""
    registered = er.async_get(hass).async_get(entity_id)
    if entity_id == "stt.speaker_id_speech_to_text" or (
        registered is not None and registered.platform in {"speaker_id", "assist_voice"}
    ):
        raise BridgeError("Speaker ID cannot be its own STT upstream")
    target = stt.async_get_speech_to_text_entity(hass, entity_id)
    if target is None or not target.available:
        raise BridgeError("The configured STT entity is unavailable")
    return target


def metadata_for(
    language: str, rate: int, width: int, channels: int
) -> stt.SpeechMetadata:
    if (rate, width, channels) != (16000, 2, 1):
        raise BridgeError("Only 16 kHz, 16-bit, mono PCM is supported")
    return stt.SpeechMetadata(
        language=language,
        format=stt.AudioFormats.WAV,
        codec=stt.AudioCodecs.PCM,
        bit_rate=stt.AudioBitRates.BITRATE_16,
        sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
        channel=stt.AudioChannels.CHANNEL_MONO,
    )


def describe(target: stt.SpeechToTextEntity) -> Info:
    """Only advertise a provider which can accept the audio sent by Speaker ID."""
    languages = [
        language
        for language in target.supported_languages
        if target.check_metadata(metadata_for(language, 16000, 2, 1))
    ]
    if not languages:
        raise BridgeError("The STT entity does not support 16 kHz mono PCM")
    model = AsrModel(
        name="ha-stt",
        attribution=ATTRIBUTION,
        installed=True,
        description="Home Assistant speech-to-text entity",
        version="1",
        languages=languages,
    )
    processing = target.audio_processing
    return Info(
        asr=[
            AsrProgram(
                name="ha-stt",
                attribution=ATTRIBUTION,
                installed=True,
                description="Home Assistant STT bridge",
                version="1",
                models=[model],
                requires_external_vad=processing.requires_external_vad,
                prefers_auto_gain_enabled=processing.prefers_auto_gain_enabled,
                prefers_noise_reduction_enabled=processing.prefers_noise_reduction_enabled,
            )
        ]
    )


class BridgeHandler(AsyncEventHandler):
    """One bounded request per connection, streamed into the target STT entity."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        hass: HomeAssistant,
        entity_id: str,
        slots: asyncio.Semaphore,
    ) -> None:
        super().__init__(reader, writer)
        self.hass = hass
        self.entity_id = entity_id
        self.slots = slots
        self.language: str | None = None
        self.audio_format: tuple[int, int, int] | None = None
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE_SIZE)
        self.task: asyncio.Task[stt.SpeechResult] | None = None
        self.total_bytes = 0

    async def run(self) -> None:
        # Bound simultaneous STT streams and idle connections; also bounds queue memory.
        try:
            async with asyncio.timeout(MAX_CONNECTION_SECONDS):
                async with self.slots:
                    await super().run()
        except TimeoutError:
            await self.disconnect()
            self.writer.close()

    async def disconnect(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None

    async def _stream(self) -> AsyncIterator[bytes]:
        while (chunk := await self.queue.get()) is not None:
            yield chunk

    async def _put(self, chunk: bytes | None) -> None:
        assert self.task is not None
        if self.task.done():
            return
        put = asyncio.create_task(self.queue.put(chunk))
        try:
            await asyncio.wait({put, self.task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not put.done():
                put.cancel()
                with suppress(asyncio.CancelledError):
                    await put

    async def handle_event(self, event: Event) -> bool:
        try:
            return await self._handle(event)
        except BridgeError as err:
            await self.write_event(Error(text=str(err), code="stt_error").event())
        except Exception:
            _LOGGER.exception("Wyoming STT request failed")
            await self.write_event(
                Error(text="Speech-to-text request failed", code="stt_error").event()
            )
        return False

    async def _handle(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(
                describe(get_target(self.hass, self.entity_id)).event()
            )
            return True
        if Transcribe.is_type(event.type):
            if self.task is not None:
                raise BridgeError("Request already in progress")
            self.language = (
                Transcribe.from_event(event).language or self.hass.config.language
            )
            return True
        if AudioStart.is_type(event.type):
            if self.task is not None:
                raise BridgeError("Request already in progress")
            start = AudioStart.from_event(event)
            self.audio_format = (start.rate, start.width, start.channels)
            metadata = metadata_for(
                self.language or self.hass.config.language, *self.audio_format
            )
            target = get_target(self.hass, self.entity_id)
            if not target.check_metadata(metadata):
                raise BridgeError(
                    "The STT entity does not support this language or audio format"
                )
            self.task = asyncio.create_task(
                target.internal_async_process_audio_stream(metadata, self._stream())
            )
            return True
        if AudioChunk.is_type(event.type):
            if self.task is None:
                raise BridgeError("Audio received before audio-start")
            chunk = AudioChunk.from_event(event)
            if (chunk.rate, chunk.width, chunk.channels) != self.audio_format:
                raise BridgeError("Audio format changed during request")
            self.total_bytes += len(chunk.audio)
            if len(chunk.audio) > MAX_CHUNK_BYTES or self.total_bytes > MAX_AUDIO_BYTES:
                raise BridgeError("Audio request exceeds bridge limits")
            await self._put(chunk.audio)
            return True
        if AudioStop.is_type(event.type):
            if self.task is None:
                raise BridgeError("Audio stopped before audio-start")
            await self._put(None)
            result = await asyncio.wait_for(self.task, timeout=60)
            if result.result != stt.SpeechResultState.SUCCESS or result.text is None:
                raise BridgeError("The STT entity failed to transcribe audio")
            await self.write_event(Transcript(text=result.text).event())
            return False
        raise BridgeError("Unsupported Wyoming event")
