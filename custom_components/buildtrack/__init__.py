"""The Buildtrack integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .buildtrack_api import BuildTrackAPI
from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.FAN, Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Buildtrack from a config entry."""
    hub = BuildTrackAPI()
    hub.set_credentials(entry.data["username"], entry.data["password"])
    hub.set_mqtt_creds(entry.data.get("mqtt_username", ""), entry.data.get("mqtt_password", ""))

    if not await hub.authenticate_user():
        raise ConfigEntryNotReady("Failed to authenticate with Buildtrack")

    # Start MQTT/WebSocket connections off the event loop to avoid blocking
    await hass.async_add_executor_job(hub.start_connections)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hub: BuildTrackAPI = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(hub.shutdown)

    return unload_ok
