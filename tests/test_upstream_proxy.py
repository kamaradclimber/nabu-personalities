"""Optional integration test against the unmodified upstream speaker-id proxy."""

import asyncio
import os
import socket
import sys
from functools import partial
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.server import AsyncTcpServer

from tests.test_bridge import FakeStt


@pytest.mark.skipif(
    not os.environ.get("ASSIST_SPEAKER_SOURCE"),
    reason="set ASSIST_SPEAKER_SOURCE to an upstream checkout",
)
async def test_unmodified_speaker_proxy_to_bridge(
    hass, entry, port, tmp_path, socket_enabled
):
    source = Path(os.environ["ASSIST_SPEAKER_SOURCE"])
    sys.path.insert(0, str(source / "speaker_id"))
    from wyoming_speaker_id.handler import SpeakerIdHandler
    from wyoming_speaker_id.service import Settings, SpeakerService
    from wyoming_speaker_id.speakers import SpeakerStore

    class FakeEmbedder:
        def embed(self, speech):
            return np.array([1.0, 0.0], dtype=np.float32)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        proxy_port = sock.getsockname()[1]
    service = SpeakerService(
        Settings(upstream=f"tcp://127.0.0.1:{port}"),
        SpeakerStore(tmp_path / "speakers.json", threshold=0.5, margin=0.05),
        FakeEmbedder(),
    )
    proxy = AsyncTcpServer("127.0.0.1", proxy_port)
    fake = FakeStt()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.assist_voice.bridge.get_target",
        return_value=fake,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await proxy.start(partial(SpeakerIdHandler, service=service))
        try:
            audio = (np.sin(np.arange(32000) * 0.1) * 10000).astype("<i2").tobytes()
            async with AsyncTcpClient("127.0.0.1", proxy_port) as client:
                await client.write_event(Transcribe(language="fr-FR").event())
                await client.write_event(
                    AudioStart(rate=16000, width=2, channels=1).event()
                )
                for i in range(0, len(audio), 4096):
                    await client.write_event(
                        AudioChunk(
                            rate=16000, width=2, channels=1, audio=audio[i : i + 4096]
                        ).event()
                    )
                await client.write_event(AudioStop().event())
                result = await asyncio.wait_for(client.read_event(), 10)
            assert Transcript.from_event(result).text == "bonjour"
            assert result.data["speaker"] is None
            assert fake.audio == audio
        finally:
            await proxy.stop()
            assert await hass.config_entries.async_unload(entry.entry_id)
