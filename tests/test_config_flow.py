"""UI configuration, including the multiple-agent entity selector."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType


async def test_config_flow_selects_conversation_entities(hass, port, socket_enabled):
    result = await hass.config_entries.flow.async_init(
        "assist_voice", context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "stt_entity": "stt.home_assistant_cloud",
            "backends": [
                "conversation.personality_one",
                "conversation.personality_two",
            ],
            "listen_host": "127.0.0.1",
            "listen_port": port,
            "stt_response_timeout": 30,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["backends"] == [
        "conversation.personality_one",
        "conversation.personality_two",
    ]
    entry = result["result"]
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_rejects_obvious_stt_loop(hass, port, socket_enabled):
    result = await hass.config_entries.flow.async_init(
        "assist_voice", context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "stt_entity": "stt.assist_voice_speaker_id",
            "backends": ["conversation.agent"],
            "listen_host": "127.0.0.1",
            "listen_port": port,
            "stt_response_timeout": 30,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "stt_loop"
