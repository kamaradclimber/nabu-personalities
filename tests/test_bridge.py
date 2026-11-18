import asyncio
from typing import ClassVar
from unittest.mock import patch

from homeassistant.components import stt
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.error import Error
from wyoming.info import Describe, Info


class FakeStt(stt.SpeechToTextEntity):
    _attr_available = True
    supported_languages: ClassVar = ["fr-FR"]
    supported_formats: ClassVar = [stt.AudioFormats.WAV]
    supported_codecs: ClassVar = [stt.AudioCodecs.PCM]
    supported_bit_rates: ClassVar = [stt.AudioBitRates.BITRATE_16]
    supported_sample_rates: ClassVar = [stt.AudioSampleRates.SAMPLERATE_16000]
    supported_channels: ClassVar = [stt.AudioChannels.CHANNEL_MONO]

    def __init__(self):
        self.audio = b""
        self.metadata = None

    async def async_process_audio_stream(self, metadata, stream):
        self.metadata = metadata
        async for chunk in stream:
            self.audio += chunk
        return stt.SpeechResult("bonjour", stt.SpeechResultState.SUCCESS)

    async def internal_async_process_audio_stream(self, metadata, stream):
        return await self.async_process_audio_stream(metadata, stream)


async def test_describe_and_stream(hass, entry, port, socket_enabled):
    fake = FakeStt()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.assist_voice.bridge.get_target",
        return_value=fake,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Describe().event())
            info = Info.from_event(await asyncio.wait_for(client.read_event(), 5))
            assert info.asr[0].models[0].languages == ["fr-FR"]
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Transcribe(language="fr-FR").event())
            await client.write_event(
                AudioStart(rate=16000, width=2, channels=1).event()
            )
            await client.write_event(
                AudioChunk(rate=16000, width=2, channels=1, audio=b"abcd").event()
            )
            await client.write_event(AudioStop().event())
            result = await asyncio.wait_for(client.read_event(), 5)
            assert Transcript.from_event(result).text == "bonjour"
        assert fake.audio == b"abcd"
        assert fake.metadata.language == "fr-FR"
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(AudioStart(rate=8000, width=2, channels=1).event())
            result = await asyncio.wait_for(client.read_event(), 5)
            assert Error.is_type(result.type)
        assert await hass.config_entries.async_unload(entry.entry_id)
