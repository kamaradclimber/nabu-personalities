import os
import socket
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant.common import MockConfigEntry


@pytest.fixture
def hass_config_dir(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    components = tmp_path / "custom_components"
    components.mkdir()
    (components / "assist_voice").symlink_to(
        Path(__file__).resolve().parents[1] / "custom_components" / "assist_voice",
        target_is_directory=True,
    )
    if source := os.environ.get("ASSIST_SPEAKER_SOURCE"):
        (components / "speaker_id").symlink_to(
            Path(source) / "custom_components" / "speaker_id", target_is_directory=True
        )
    return str(tmp_path)


@pytest.fixture(autouse=True)
async def custom_integrations(hass, enable_custom_integrations):
    assert await async_setup_component(hass, "homeassistant", {})
    yield


@pytest.fixture
def port(socket_enabled):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def entry(port):
    return MockConfigEntry(
        domain="assist_voice",
        data={
            "stt_entity": "stt.test",
            "backends": ["agent_a", "agent_b"],
            "listen_host": "127.0.0.1",
            "listen_port": port,
        },
    )
