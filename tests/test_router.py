import asyncio

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component


class Agent(conversation.AbstractConversationAgent):
    def __init__(self, name):
        self.name = name
        self.inputs = []

    @property
    def supported_languages(self):
        return ["fr"]

    async def async_process(self, user_input):
        self.inputs.append(user_input)
        response = intent.IntentResponse(language="fr")
        response.async_set_speech(self.name)
        return conversation.ConversationResult(
            response, user_input.conversation_id or f"{self.name}-private"
        )


async def test_rotation_sessions_and_prompt(hass, entry, socket_enabled):
    assert await async_setup_component(hass, "conversation", {})
    agents = [Agent("a"), Agent("b")]
    manager = conversation.get_agent_manager(hass)
    manager.async_set_agent("agent_a", agents[0])
    manager.async_set_agent("agent_b", agents[1])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    router = entry.runtime_data.router
    context = Context()
    first = await conversation.async_converse(
        hass,
        "bonjour",
        None,
        context,
        language="fr",
        agent_id=router.entity_id,
        extra_system_prompt="Grégoire parle",
    )
    assert first.conversation_id != "a-private"
    assert agents[0].inputs[0].extra_system_prompt == "Grégoire parle"
    await hass.services.async_call("assist_voice", "rotate", {}, blocking=True)
    assert router.current == "agent_b"
    second = await conversation.async_converse(
        hass,
        "suite",
        first.conversation_id,
        context,
        language="fr",
        agent_id=router.entity_id,
    )
    assert second.conversation_id == first.conversation_id
    assert agents[0].inputs[-1].conversation_id == "a-private"
    fresh = await conversation.async_converse(
        hass, "nouveau", None, context, language="fr", agent_id=router.entity_id
    )
    assert fresh.conversation_id and agents[1].inputs[-1].conversation_id is None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.router.current == "agent_b"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_concurrent_first_turns_cannot_rotate_session(
    hass, entry, socket_enabled
):
    assert await async_setup_component(hass, "conversation", {})
    started, release = asyncio.Event(), asyncio.Event()

    class SlowAgent(Agent):
        async def async_process(self, user_input):
            started.set()
            await release.wait()
            return await super().async_process(user_input)

    first, second = SlowAgent("a"), Agent("b")
    manager = conversation.get_agent_manager(hass)
    manager.async_set_agent("agent_a", first)
    manager.async_set_agent("agent_b", second)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    router = entry.runtime_data.router
    kwargs = {"language": "fr", "agent_id": router.entity_id}
    task1 = asyncio.create_task(
        conversation.async_converse(
            hass, "one", "external-session", Context(), **kwargs
        )
    )
    await started.wait()
    await hass.services.async_call("assist_voice", "rotate", {}, blocking=True)
    task2 = asyncio.create_task(
        conversation.async_converse(
            hass, "two", "external-session", Context(), **kwargs
        )
    )
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(task1, task2)
    assert [item.text for item in first.inputs] == ["one", "two"]
    assert not second.inputs
    assert await hass.config_entries.async_unload(entry.entry_id)
