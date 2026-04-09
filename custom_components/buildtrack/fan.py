"""Platform for fan integration."""
from __future__ import annotations

import logging

from homeassistant.components.fan import FanEntity, FanEntityFeature
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
    """Set up Buildtrack fan entities."""
    api: BuildTrackAPI = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        BuildTrackFanEntity(hass, api, fan)
        for fan in api.get_devices_of_type("fan")
    )


class BuildTrackFanEntity(FanEntity):

    selected_preset_mode = "Low"
    preset_modes = [ "Low", "Medium", "High", "Very High"]

    def __init__(self, hass, hub, fan) -> None:
        """Initialize the Buildtrack fan."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.room_name = fan["room_name"]
        self.room_id = fan["room_id"]
        self.id = fan["ID"]
        self._attr_unique_id = f"buildtrack_fan_{fan['ID']}"
        self.fan_name = fan["label"]
        self.fan_pin_type = fan["pin_type"]
        self._parent_device = self.hub.get_parent_device_details(self.id)
        self.hub.listen_device_state(self.id)

    async def async_added_to_hass(self) -> None:
        """Register state update callback when entity is added."""
        _LOGGER.debug("Fan '%s' added to hass, registering state callback", self.name)
        self.hub.register_state_callback(self.id, self._handle_state_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister state update callback when entity is removed."""
        _LOGGER.debug("Fan '%s' removed from hass, unregistering state callback", self.name)
        self.hub.remove_state_callback(self.id, self._handle_state_update)

    def _handle_state_update(self) -> None:
        """Handle state update from MQTT/WS (called from background thread)."""
        _LOGGER.debug("Fan '%s' received state update: %s", self.name, self.hub.get_device_state(self.id))
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

    @property
    def name(self) -> str:
        """Return the entity name."""
        return f"{self.room_name} {self.fan_name}"

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
    def current_direction(self) -> str:
        return 'Clockwise'

    @property
    def is_on(self):
        return self.hub.is_device_on(self.id)

    @property
    def supported_features(self) -> int:
        return FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE | FanEntityFeature.TURN_OFF | FanEntityFeature.TURN_ON

    @property
    def oscillating(self) -> bool:
        return False

    @property
    def percentage(self) -> int:
        return self.hub.get_device_state(self.id)["speed"]

    @property
    def speed_count(self) -> int:
        return len(self.preset_modes)

    _attr_should_poll = False


    @property
    def preset_mode(self) -> str:
        if self.percentage > 0 and self.percentage <= 25:
            self.selected_preset_mode = self.preset_modes[0]
        elif self.percentage > 25 and self.percentage <= 50:
            self.selected_preset_mode = self.preset_modes[1]
        elif self.percentage > 50 and self.percentage <= 75:
            self.selected_preset_mode = self.preset_modes[2]
        elif self.percentage > 75 and self.percentage <= 100:
            self.selected_preset_mode = self.preset_modes[3]
        return self.selected_preset_mode

    async def async_increase_speed(self, percentage_step) -> None:
        current_speed = self.percentage
        if current_speed + percentage_step > 100:
            return
        await self.async_set_percentage(current_speed + percentage_step)

    async def async_decrease_speed(self, percentage_step) -> None:
        current_speed = self.percentage
        if current_speed - percentage_step < 0:
            return
        await self.async_set_percentage(current_speed - percentage_step)

    async def async_set_percentage(self, percentage: int) -> None:
        _LOGGER.info("Setting fan '%s' speed to %d%% (id=%s)", self.name, percentage, self.id)
        await self.hub.switch_on(self.id, percentage)
        self.hass.bus.fire(
            event_type="buildtrack_fan_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "percentage",
            },
        )

    async def async_turn_on(self,
                            percentage: int | None = None,
                            preset_mode: str | None = None, **kwargs) -> None:
        """Turn on the fan."""
        _LOGGER.info("Turning on fan '%s' (id=%s, percentage=%s, preset=%s)", self.name, self.id, percentage, preset_mode)
        if percentage is not None:
            await self.async_set_percentage( percentage)
        elif preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        else:
            await self.hub.switch_on(self.id, speed=percentage)
            
        self.hass.bus.fire(
            event_type="buildtrack_fan_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "on",
                "percentage": percentage,
                "preset_mode": preset_mode
            },
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the fan."""
        _LOGGER.info("Turning off fan '%s' (id=%s)", self.name, self.id)
        await self.hub.switch_off(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_fan_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "off",
            },
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        _LOGGER.info("Setting fan '%s' preset mode to '%s' (id=%s)", self.name, preset_mode, self.id)
        index = self.preset_modes.index(preset_mode)
        if index == 0:
            await self.async_set_percentage(25)
        elif index == 1:
            await self.async_set_percentage(50)
        elif index == 2:
            await self.async_set_percentage(75)
        elif index == 3:
            await self.async_set_percentage(100)

