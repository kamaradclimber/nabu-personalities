"""Shared device metadata for the integration's entities."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN


def assist_voice_device_info(entry_id: str) -> DeviceInfo:
    """Represent this integration's logical service as one HA device."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="Assist Voice",
        entry_type=DeviceEntryType.SERVICE,
    )
