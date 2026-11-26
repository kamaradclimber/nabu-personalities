"""A stable conversation agent that routes to a rotating personality."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Literal
from uuid import uuid4

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import CONF_BACKENDS, DOMAIN
from .device import assist_voice_device_info

IN_ROUTER: ContextVar[bool] = ContextVar("assist_voice_in_router", default=False)
SESSION_TTL = 24 * 60 * 60
MAX_SESSIONS = 1000
ROUTER_SESSION_PREFIX = "assist-voice-"


@dataclass
class Session:
    backend: str
    backend_id: str
    touched: float
    lock: asyncio.Lock
    users: int = 0
    closed: bool = False


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([entry.runtime_data.router])


class PersonalityRouter(conversation.ConversationEntity):
    """Preserve backend identity and private backend conversation IDs per session."""

    _attr_name = "Personality router"
    _attr_should_poll = False
    _attr_supports_streaming = False

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self._attr_unique_id = f"{entry.entry_id}-router"
        self._attr_device_info = assist_voice_device_info(entry.entry_id)
        self.backends = list(entry.data[CONF_BACKENDS])
        self.current: str = self.backends[0]
        self.store: Store = Store(
            hass, 1, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True
        )
        self.sessions: dict[str, Session] = {}
        self.rotate_lock = asyncio.Lock()
        self._personality_listeners: list[Callable[[Context | None], None]] = []

    async def load(self) -> None:
        saved = await self.store.async_load() or {}
        if saved.get("backend") in self.backends:
            self.current = saved["backend"]

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    @property
    def extra_state_attributes(self) -> dict:
        return {"current_backend": self.current, "backends": self.backends}

    @callback
    def async_add_personality_listener(
        self, listener: Callable[[Context | None], None]
    ) -> None:
        """Call the listener whenever the current personality changes."""
        self._personality_listeners.append(listener)

    @callback
    def async_remove_personality_listener(
        self, listener: Callable[[Context | None], None]
    ) -> None:
        self._personality_listeners.remove(listener)

    async def rotate(self, context: Context | None = None) -> None:
        """Select a random alternative personality for new conversations."""
        async with self.rotate_lock:
            choices = [agent for agent in self.backends if agent != self.current]
            if not choices:
                raise HomeAssistantError(
                    "At least two different personalities are required to rotate"
                )
            await self._async_select_personality(secrets.choice(choices), context)

    async def select_personality(
        self, backend: str, context: Context | None = None
    ) -> None:
        """Select a configured backend for new conversations."""
        async with self.rotate_lock:
            if backend not in self.backends:
                raise HomeAssistantError(
                    f"{backend} is not a configured personality backend"
                )
            await self._async_select_personality(backend, context)

    async def _async_select_personality(
        self, backend: str, context: Context | None
    ) -> None:
        """Persist a selection before publishing the change to entities."""
        if backend == self.current:
            return
        # Attribute the resulting state changes to the triggering call, so the
        # logbook and device activity show what caused the personality change.
        if context is not None:
            self.async_set_context(context)
        # Persist first: a write failure must not result in an unrecorded selection.
        await self.store.async_save({"backend": backend})
        self.current = backend
        self.async_write_ha_state()
        for listener in self._personality_listeners:
            listener(context)

    def _prune(self, *, for_insert: bool = False) -> None:
        now = time.monotonic()
        for key, session in list(self.sessions.items()):
            if now - session.touched > SESSION_TTL and not session.users:
                del self.sessions[key]
        while for_insert and len(self.sessions) >= MAX_SESSIONS:
            idle = [
                (key, session)
                for key, session in self.sessions.items()
                if not session.users
            ]
            if not idle:
                raise HomeAssistantError("Too many active conversations")
            del self.sessions[min(idle, key=lambda item: item[1].touched)[0]]

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        if IN_ROUTER.get():
            raise HomeAssistantError("Personality routing loop detected")
        self._prune()
        session_id = user_input.conversation_id
        if session_id is not None:
            session = self.sessions.get(session_id)
            if session is None:
                if session_id.startswith(ROUTER_SESSION_PREFIX):
                    raise HomeAssistantError(
                        "Conversation expired or was reset; start a new conversation"
                    )
                # Assist assigns an ID before the first turn. Reserve the backend
                # before awaiting it, so concurrent first turns cannot diverge.
                self._prune(for_insert=True)
                session = Session(
                    self.current, session_id, time.monotonic(), asyncio.Lock()
                )
                self.sessions[session_id] = session
            session.touched = time.monotonic()
            session.users += 1
            try:
                async with session.lock:
                    if session.closed:
                        raise HomeAssistantError(
                            "Conversation ended; start a new conversation"
                        )
                    result = await self._delegate(
                        user_input, session.backend, session.backend_id
                    )
                    session.touched = time.monotonic()
                    if result.conversation_id is None:
                        session.closed = True
                        return result
                    session.backend_id = result.conversation_id
                    return replace(result, conversation_id=session_id)
            finally:
                session.users -= 1
                if session.closed and not session.users:
                    self.sessions.pop(session_id, None)
        backend = self.current
        result = await self._delegate(user_input, backend, None)
        if result.conversation_id is None:
            return result
        self._prune(for_insert=True)
        session_id = f"{ROUTER_SESSION_PREFIX}{uuid4().hex}"
        self.sessions[session_id] = Session(
            backend, result.conversation_id, time.monotonic(), asyncio.Lock()
        )
        return replace(result, conversation_id=session_id)

    async def _delegate(
        self,
        user_input: conversation.ConversationInput,
        backend: str,
        backend_id: str | None,
    ) -> conversation.ConversationResult:
        if backend == self.entity_id:
            raise HomeAssistantError("Personality routing loop detected")
        target = conversation.async_get_agent(self.hass, backend)
        if target is None or (
            isinstance(target, conversation.ConversationEntity) and not target.available
        ):
            raise HomeAssistantError(f"Personality {backend} is unavailable")
        token = IN_ROUTER.set(True)
        try:
            return await conversation.async_converse(
                self.hass,
                user_input.text,
                backend_id,
                user_input.context,
                language=user_input.language,
                agent_id=backend,
                device_id=user_input.device_id,
                satellite_id=user_input.satellite_id,
                extra_system_prompt=user_input.extra_system_prompt,
            )
        finally:
            IN_ROUTER.reset(token)
