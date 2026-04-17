"""Platform for switch integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .buildtrack_api import BuildTrackAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Buildtrack switch entities."""
    api: BuildTrackAPI = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        BuildTrackSwitchEntity(hass, api, switch)
        for switch in api.get_devices_of_type("switch")
    )


class BuildTrackSwitchEntity(SwitchEntity):

    _attr_should_poll = False

    def __init__(self, hass, hub, switch) -> None:
        """Initialize the Buildtrack switch."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.room_name = switch["room_name"]
        self.room_id = switch["room_id"]
        self.id = switch["ID"]
        self._attr_unique_id = f"buildtrack_switch_{switch['ID']}"
        self.switch_name = switch["label"]
        self.switch_pin_type = switch["pin_type"]
        self.hub.listen_device_state(self.id)

    async def async_added_to_hass(self) -> None:
        """Register state update callback when entity is added."""
        _LOGGER.debug("Switch '%s' added to hass, registering state callback", self.name)
        self.hub.register_state_callback(self.id, self._handle_state_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister state update callback when entity is removed."""
        _LOGGER.debug("Switch '%s' removed from hass, unregistering state callback", self.name)
        self.hub.remove_state_callback(self.id, self._handle_state_update)

    def _handle_state_update(self) -> None:
        """Handle state update from MQTT (called from background thread)."""
        # _LOGGER.debug("Switch '%s' received state update", self.name)
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

    @property
    def name(self) -> str:
        """Return the entity name."""
        return f"{self.room_name} {self.switch_name}"

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self.hub.is_device_on(self.id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        _LOGGER.info("Turning on switch '%s' (id=%s)", self.name, self.id)
        await self.hub.switch_on(self.id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        _LOGGER.info("Turning off switch '%s' (id=%s)", self.name, self.id)
        await self.hub.switch_off(self.id)
