"""The Buildtrack integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .buildtrack_api import BuildTrackAPI
from .const import DOMAIN

# For your initial PR, limit it to 1 platform.
PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.FAN, Platform.COVER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Buildtrack from a config entry."""
    # Store an API object for your platforms to access
    # hass.data[DOMAIN][entry.entry_id] = MyApi(...)
    hub = BuildTrackAPI()
    hub.set_credentials(entry.data["username"], entry.data["password"])
    await hass.async_add_executor_job(hub.authenticate_user)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
