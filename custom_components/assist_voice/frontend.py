"""Serve the optional Assist Voice Lovelace card module."""

from pathlib import Path

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView

CARD_PATH = Path(__file__).parent / "www" / "assist-voice-pipeline-card.js"


class AssistVoicePipelineCardView(HomeAssistantView):
    """Expose the frontend module as a same-origin static resource."""

    url = "/api/assist_voice/pipeline-card.js"
    name = "api:assist_voice:pipeline-card"
    requires_auth = False

    async def get(self, request: web.Request) -> web.FileResponse:
        """Return the custom Lovelace card module."""
        return web.FileResponse(CARD_PATH)


async def async_setup(hass: HomeAssistant) -> None:
    """Register the card resource endpoint."""
    hass.http.register_view(AssistVoicePipelineCardView)
