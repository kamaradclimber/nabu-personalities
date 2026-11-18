"""Route actual ConversationEntity instances and their Home Assistant chat logs."""

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component


class ChatAgent(conversation.ConversationEntity):
    _attr_should_poll = False

    def __init__(self, name):
        self._attr_name = name
        self.seen = []
        self.inputs = []

    @property
    def supported_languages(self):
        return ["fr"]

    async def _async_handle_message(self, user_input, chat_log):
        self.inputs.append(user_input)
        self.seen.append(
            (
                user_input.extra_system_prompt,
                [item.content for item in chat_log.content if item.role == "user"],
            )
        )
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=self.entity_id, content="réponse")
        )
        response = intent.IntentResponse(language="fr")
        response.async_set_speech("réponse")
        return conversation.ConversationResult(response, chat_log.conversation_id)


async def test_entities_keep_chat_history_through_rotation(hass, entry, socket_enabled):
    assert await async_setup_component(hass, "conversation", {})
    first, second = ChatAgent("Personality One"), ChatAgent("Personality Two")
    await hass.data[conversation.DATA_COMPONENT].async_add_entities([first, second])
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "backends": [first.entity_id, second.entity_id]}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    router = entry.runtime_data.router
    first_result = await conversation.async_converse(
        hass,
        "bonjour",
        None,
        Context(),
        language="fr",
        agent_id=router.entity_id,
        extra_system_prompt="Grégoire parle",
    )
    await hass.services.async_call("assist_voice", "rotate", {}, blocking=True)
    await conversation.async_converse(
        hass,
        "suite",
        first_result.conversation_id,
        Context(),
        language="fr",
        agent_id=router.entity_id,
    )
    assert first.seen == [("Grégoire parle", ["bonjour"]), (None, ["bonjour", "suite"])]
    assert not second.seen
    await conversation.async_converse(
        hass, "nouveau", None, Context(), language="fr", agent_id=router.entity_id
    )
    assert second.seen == [(None, ["nouveau"])]
    assert await hass.config_entries.async_unload(entry.entry_id)
