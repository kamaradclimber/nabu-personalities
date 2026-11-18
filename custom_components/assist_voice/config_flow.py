"""Configure the bridge and the personality router."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_BACKENDS,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_RESPONSE_TIMEOUT,
    CONF_SPEAKER_STT,
    CONF_STT_ENTITY,
    DEFAULT_LISTEN_HOST,
    DEFAULT_LISTEN_PORT,
    DEFAULT_RESPONSE_TIMEOUT,
    DEFAULT_SPEAKER_STT,
    DOMAIN,
    GUARDED_STT_ENTITY,
)


def _schema(values: dict[str, Any] | None = None) -> vol.Schema:
    values = values or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_STT_ENTITY,
                default=values.get(CONF_STT_ENTITY, "stt.home_assistant_cloud"),
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="stt")),
            vol.Optional(
                CONF_SPEAKER_STT,
                description={
                    "suggested_value": values.get(CONF_SPEAKER_STT, DEFAULT_SPEAKER_STT)
                },
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="stt", integration="speaker_id")
            ),
            vol.Required(
                CONF_RESPONSE_TIMEOUT,
                default=values.get(CONF_RESPONSE_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=90)),
            vol.Required(
                CONF_BACKENDS, default=values.get(CONF_BACKENDS, [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="conversation", multiple=True)
            ),
            vol.Required(
                CONF_LISTEN_HOST,
                default=values.get(CONF_LISTEN_HOST, DEFAULT_LISTEN_HOST),
            ): str,
            vol.Required(
                CONF_LISTEN_PORT,
                default=values.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        }
    )


def _error(data: dict[str, Any]) -> str | None:
    backends = data[CONF_BACKENDS]
    if not backends or len(backends) != len(set(backends)):
        return "invalid_backends"
    # The runtime guards also catch renamed entities and indirect loops.
    if (
        "conversation.speaker_id_agent" in backends
        or "conversation.assist_voice_personality_router" in backends
    ):
        return "routing_loop"
    if data[CONF_STT_ENTITY] in {
        DEFAULT_SPEAKER_STT,
        GUARDED_STT_ENTITY,
        data.get(CONF_SPEAKER_STT),
    }:
        return "stt_loop"
    return None


class AssistVoiceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """One bridge and one personality router per Home Assistant instance."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        error = _error(user_input) if user_input is not None else None
        if user_input is not None and error is None:
            return self.async_create_entry(title="Assist Voice", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input),
            errors={"base": error} if error else {},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reconfigure_entry()
        error = _error(user_input) if user_input is not None else None
        if user_input is not None and error is None:
            return self.async_update_reload_and_abort(entry, data=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors={"base": error} if error else {},
        )
