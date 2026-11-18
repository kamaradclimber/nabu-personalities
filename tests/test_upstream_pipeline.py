"""Complete HA audio pipeline with the unchanged upstream Speaker ID components."""

import asyncio
import os
import socket
import sys
from functools import partial
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from aiohttp import web
from homeassistant.components import assist_pipeline, conversation, stt
from homeassistant.components.assist_pipeline.pipeline import KEY_ASSIST_PIPELINE
from homeassistant.core import Context
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry
from wyoming.server import AsyncTcpServer

from tests.test_bridge import FakeStt
from tests.test_chat_entities import ChatAgent

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASSIST_SPEAKER_SOURCE"),
    reason="set ASSIST_SPEAKER_SOURCE to the pinned upstream checkout",
)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_speaker_prompt_reaches_selected_agent(
    hass, entry, port, tmp_path, socket_enabled
):
    source = Path(os.environ["ASSIST_SPEAKER_SOURCE"])
    sys.path.insert(0, str(source / "speaker_id"))
    from wyoming_speaker_id.handler import SpeakerIdHandler
    from wyoming_speaker_id.http_api import build_app
    from wyoming_speaker_id.service import Settings, SpeakerService
    from wyoming_speaker_id.speakers import SpeakerStore

    class Embedder:
        model = "fake"
        dim = 2

        def embed(self, speech):
            return np.array([1.0, 0.0], dtype=np.float32)

    store = SpeakerStore(tmp_path / "speakers.json", threshold=0.5, margin=0.05)
    store.upsert("gregoire", "Grégoire", None)
    store.add_sample("gregoire", np.array([1.0, 0.0], dtype=np.float32), 2.0)
    service = SpeakerService(
        Settings(upstream=f"tcp://127.0.0.1:{port}"), store, Embedder()
    )
    proxy_port, api_port = free_port(), free_port()
    proxy = AsyncTcpServer("127.0.0.1", proxy_port)
    runner = web.AppRunner(build_app(service, token=None))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", api_port).start()
    await proxy.start(partial(SpeakerIdHandler, service=service))
    speaker_entry = None
    try:
        assert await async_setup_component(hass, "conversation", {})
        agent = ChatAgent("Personality One")
        second_agent = ChatAgent("Personality Two")
        await hass.data[conversation.DATA_COMPONENT].async_add_entities(
            [agent, second_agent]
        )
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, "backends": [agent.entity_id, second_agent.entity_id]},
        )
        with patch(
            "custom_components.assist_voice.bridge.get_target", return_value=FakeStt()
        ) as bridge_target:
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            guarded = stt.async_get_speech_to_text_entity(
                hass, "stt.assist_voice_speaker_id"
            )
            assert guarded is not None and not guarded.available
            speaker_entry = MockConfigEntry(
                domain="speaker_id",
                title="Speaker ID",
                data={"host": "127.0.0.1", "port": proxy_port, "api_port": api_port},
                options={
                    "agent_id": entry.runtime_data.router.entity_id,
                    "prompt": "La personne qui parle est {name}.",
                },
            )
            speaker_entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(speaker_entry.entry_id)
            await hass.async_block_till_done()
            assert guarded.available and "fr-FR" in guarded.supported_languages
            assert hass.states.get("stt.assist_voice_speaker_id").state != "unavailable"
            assert await async_setup_component(hass, "assist_pipeline", {})
            pipeline = await hass.data[
                KEY_ASSIST_PIPELINE
            ].pipeline_store.async_create_item(
                {
                    "conversation_engine": "conversation.speaker_id_agent",
                    "conversation_language": "fr-FR",
                    "language": "fr-FR",
                    "name": "Test",
                    "stt_engine": "stt.assist_voice_speaker_id",
                    "stt_language": "fr-FR",
                    "tts_engine": None,
                    "tts_language": None,
                    "tts_voice": None,
                    "wake_word_entity": None,
                    "wake_word_id": None,
                }
            )
            tone = np.sin(np.arange(32000) * 0.1) * 10000
            audio = (
                np.concatenate([np.zeros(8000), tone, np.zeros(8000)])
                .astype("<i2")
                .tobytes()
            )

            async def stream():
                for i in range(0, len(audio), 2048):
                    yield audio[i : i + 2048]

            metadata = stt.SpeechMetadata(
                "fr-FR",
                stt.AudioFormats.WAV,
                stt.AudioCodecs.PCM,
                stt.AudioBitRates.BITRATE_16,
                stt.AudioSampleRates.SAMPLERATE_16000,
                stt.AudioChannels.CHANNEL_MONO,
            )
            events = []
            await assist_pipeline.async_pipeline_from_audio_stream(
                hass,
                context=Context(),
                event_callback=events.append,
                stt_metadata=metadata,
                stt_stream=stream(),
                pipeline_id=pipeline.id,
                end_stage=assist_pipeline.PipelineStage.INTENT,
            )
            assert agent.inputs, [(event.type, event.data) for event in events]
            assert agent.inputs[-1].text == "bonjour"
            assert (
                agent.inputs[-1].extra_system_prompt
                == "La personne qui parle est Grégoire."
            ), (
                service.last().to_dict() if service.last() else None,
                hass.states.get("sensor.speaker_id_last_speaker"),
            )
            assert any(event.type == "intent-end" for event in events)
            session_id = next(
                event.data["conversation_id"]
                for event in events
                if event.type == "run-start"
            )
            await hass.services.async_call("assist_voice", "rotate", {}, blocking=True)
            await assist_pipeline.async_pipeline_from_audio_stream(
                hass,
                context=Context(),
                event_callback=lambda event: None,
                stt_metadata=metadata,
                stt_stream=stream(),
                pipeline_id=pipeline.id,
                conversation_id=session_id,
                end_stage=assist_pipeline.PipelineStage.INTENT,
            )
            assert len(agent.inputs) == 2
            assert agent.inputs[-1].conversation_id == session_id
            assert not second_agent.inputs
            await assist_pipeline.async_pipeline_from_audio_stream(
                hass,
                context=Context(),
                event_callback=lambda event: None,
                stt_metadata=metadata,
                stt_stream=stream(),
                pipeline_id=pipeline.id,
                end_stage=assist_pipeline.PipelineStage.INTENT,
            )
            assert (
                second_agent.inputs[-1].extra_system_prompt
                == "La personne qui parle est Grégoire."
            )

            class FailingStt(FakeStt):
                async def async_process_audio_stream(self, metadata, stream):
                    async for _ in stream:
                        pass
                    return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

            bridge_target.return_value = FailingStt()
            guarded = stt.async_get_speech_to_text_entity(
                hass, "stt.assist_voice_speaker_id"
            )
            assert guarded is not None
            guarded._response_timeout = 0.2  # shorten the real timeout for this test
            errors = []
            await asyncio.wait_for(
                assist_pipeline.async_pipeline_from_audio_stream(
                    hass,
                    context=Context(),
                    event_callback=errors.append,
                    stt_metadata=metadata,
                    stt_stream=stream(),
                    pipeline_id=pipeline.id,
                    end_stage=assist_pipeline.PipelineStage.INTENT,
                ),
                timeout=3,
            )
            assert any(event.type == "error" for event in errors), errors
            assert len(second_agent.inputs) == 1
    finally:
        if speaker_entry and speaker_entry.state.value == "loaded":
            await hass.config_entries.async_unload(speaker_entry.entry_id)
        if entry.state.value == "loaded":
            await hass.config_entries.async_unload(entry.entry_id)
        await proxy.stop()
        await runner.cleanup()
