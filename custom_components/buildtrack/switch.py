"""Platform for switch integration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
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
        BuildtrackSwitch(hass, api, switch)
        for switch in api.get_devices_of_type("switch")
    )


class BuildtrackSwitch(SwitchEntity):
    """Representation of Buildtrack switch."""

    _attr_should_poll = False
    hub: BuildTrackAPI

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
        self._parent_device = self.hub.get_parent_device_details(self.id)
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
        """Handle state update from MQTT/WS (called from background thread)."""
        _LOGGER.debug("Switch '%s' received state update, is_on=%s", self.name, self.hub.is_device_on(self.id))
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

    @property
    def name(self) -> str:
        """Formulates the device name."""
        return f"{self.room_name} {self.switch_name}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info for device grouping."""
        if not self._parent_device:
            return None
        mac_id = self._parent_device.get("mac_id", "")
        return DeviceInfo(
            identifiers={(DOMAIN, mac_id)},
            name=self._parent_device.get("label", f"Buildtrack {mac_id}"),
            manufacturer="Buildtrack",
            model=self._parent_device.get("model", None),
        )

    @property
    def is_on(self) -> bool:
        """States whether the device is on or off."""
        return self.hub.is_device_on(self.id)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the device."""
        _LOGGER.info("Turning on switch '%s' (id=%s)", self.name, self.id)
        await self.hub.switch_on(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_switch_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "on",
            },
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the device."""
        _LOGGER.info("Turning off switch '%s' (id=%s)", self.name, self.id)
        await self.hub.switch_off(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_switch_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "off",
            },
        )

    async def async_toggle(self, **kwargs) -> None:
        """Toggle the device state."""
        _LOGGER.info("Toggling switch '%s' (id=%s)", self.name, self.id)
        return await self.hub.toggle_device(self.id)
