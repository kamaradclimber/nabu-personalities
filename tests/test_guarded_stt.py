"""Timeout and cancellation behavior of the protected STT entity."""

import asyncio
from contextvars import ContextVar

import pytest
from homeassistant.components import stt

from custom_components.assist_voice.stt import GuardedSpeakerStt
from tests.test_bridge import FakeStt

METADATA = stt.SpeechMetadata(
    "fr-FR",
    stt.AudioFormats.WAV,
    stt.AudioCodecs.PCM,
    stt.AudioBitRates.BITRATE_16,
    stt.AudioSampleRates.SAMPLERATE_16000,
    stt.AudioChannels.CHANNEL_MONO,
)
IDENTITY = ContextVar("test_speaker", default=None)


async def test_response_timeout_cancels_provider(entry, monkeypatch):
    cancelled = asyncio.Event()

    class Hanging(FakeStt):
        async def internal_async_process_audio_stream(self, metadata, stream):
            try:
                async for _ in stream:
                    pass
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    guarded = GuardedSpeakerStt(entry)
    guarded._response_timeout = 0.05
    monkeypatch.setattr(guarded, "_target", lambda: Hanging())

    async def audio():
        yield b"abcd"

    result = await asyncio.wait_for(
        guarded.async_process_audio_stream(METADATA, audio()), 2
    )
    assert result.result == stt.SpeechResultState.ERROR
    assert cancelled.is_set()


async def test_slow_audio_does_not_use_response_timeout_and_context_is_preserved(
    entry, monkeypatch
):
    class Target(FakeStt):
        async def internal_async_process_audio_stream(self, metadata, stream):
            async for _ in stream:
                pass
            IDENTITY.set("gregoire")
            return stt.SpeechResult("bonjour", stt.SpeechResultState.SUCCESS)

    guarded = GuardedSpeakerStt(entry)
    guarded._response_timeout = 0.03
    monkeypatch.setattr(guarded, "_target", lambda: Target())

    async def slow_audio():
        await asyncio.sleep(0.08)
        yield b"abcd"

    token = IDENTITY.set(None)
    try:
        result = await guarded.async_process_audio_stream(METADATA, slow_audio())
        assert result.text == "bonjour"
        assert IDENTITY.get() == "gregoire"
    finally:
        IDENTITY.reset(token)


async def test_concurrent_speaker_contexts_stay_separate(entry, monkeypatch):
    class Target(FakeStt):
        async def internal_async_process_audio_stream(self, metadata, stream):
            async for chunk in stream:
                IDENTITY.set(chunk.decode())
            await asyncio.sleep(0)
            return stt.SpeechResult("bonjour", stt.SpeechResultState.SUCCESS)

    guarded = GuardedSpeakerStt(entry)
    monkeypatch.setattr(guarded, "_target", lambda: Target())

    async def turn(name):
        token = IDENTITY.set(None)
        try:

            async def audio():
                yield name.encode()

            await guarded.async_process_audio_stream(METADATA, audio())
            return IDENTITY.get()
        finally:
            IDENTITY.reset(token)

    assert await asyncio.gather(turn("gregoire"), turn("noemi")) == [
        "gregoire",
        "noemi",
    ]


async def test_external_cancellation_is_not_swallowed(entry, monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class Target(FakeStt):
        async def internal_async_process_audio_stream(self, metadata, stream):
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    guarded = GuardedSpeakerStt(entry)
    monkeypatch.setattr(guarded, "_target", lambda: Target())

    async def audio():
        yield b"abcd"

    task = asyncio.create_task(guarded.async_process_audio_stream(METADATA, audio()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
