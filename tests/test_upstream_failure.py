"""Document how the pinned upstream client handles Wyoming error events."""

import asyncio
import os
import socket
import sys
from functools import partial
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.components import stt
from wyoming.server import AsyncTcpServer

from tests.test_bridge import FakeStt

pytestmark = pytest.mark.skipif(
    not os.environ.get("ASSIST_SPEAKER_SOURCE"), reason="requires upstream checkout"
)


async def test_upstream_client_requires_caller_timeout_on_stt_error(
    hass, entry, port, tmp_path, socket_enabled
):
    sys.path.insert(0, str(Path(os.environ["ASSIST_SPEAKER_SOURCE"]) / "speaker_id"))
    from custom_components.speaker_id.client import SpeakerIdClient
    from wyoming_speaker_id.handler import SpeakerIdHandler
    from wyoming_speaker_id.service import Settings, SpeakerService
    from wyoming_speaker_id.speakers import SpeakerStore

    class FailingStt(FakeStt):
        async def internal_async_process_audio_stream(self, metadata, stream):
            async for _ in stream:
                pass
            return stt.SpeechResult(None, stt.SpeechResultState.ERROR)

    class Embedder:
        def embed(self, speech):
            raise AssertionError("short audio should not be embedded")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        proxy_port = sock.getsockname()[1]
    service = SpeakerService(
        Settings(upstream=f"tcp://127.0.0.1:{port}"),
        SpeakerStore(tmp_path / "speakers.json", 0.5, 0.05),
        Embedder(),
    )
    proxy = AsyncTcpServer("127.0.0.1", proxy_port)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.assist_voice.bridge.get_target", return_value=FailingStt()
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await proxy.start(partial(SpeakerIdHandler, service=service))
        try:

            async def audio():
                yield b"\x00\x00" * 8000

            client = SpeakerIdClient(None, "127.0.0.1", proxy_port, 1)
            # At the pinned upstream revision, the STT client ignores Wyoming's
            # error event and the proxy keeps the connection open. Do not hide it.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(client.transcribe("fr-FR", audio()), timeout=0.5)
        finally:
            await proxy.stop()
            assert await hass.config_entries.async_unload(entry.entry_id)
