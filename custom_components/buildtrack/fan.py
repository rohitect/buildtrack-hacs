"""Platform for fan integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
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
    """Set up Buildtrack fan entities."""
    api: BuildTrackAPI = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        BuildTrackFanEntity(hass, api, fan)
        for fan in api.get_devices_of_type("fan")
    )


class BuildTrackFanEntity(FanEntity):

    _attr_should_poll = False
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    # BuildTrack fans are 4-speed regulators; the cloud expects discrete speed
    # values of 25/50/75/100 (verified: UI level 1 == speed "25"). Advertising
    # 4 speeds makes Home Assistant present four steps and map each slider step
    # to one of those values instead of an arbitrary 1-100 percentage.
    _attr_speed_count = 4

    @staticmethod
    def _snap_speed(percentage: int) -> int:
        """Snap an arbitrary 1-100 percentage to a valid device speed (25/50/75/100)."""
        level = min(4, max(1, round(percentage / 25)))
        return level * 25

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
        """Handle state update from MQTT (called from background thread)."""
        # _LOGGER.debug("Fan '%s' received state update", self.name)
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

    @property
    def name(self) -> str:
        """Return the entity name."""
        return f"{self.room_name} {self.fan_name}"

    @property
    def is_on(self) -> bool:
        """Return true if the fan is on."""
        return self.hub.is_device_on(self.id)

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        state = self.hub.get_device_state(self.id)
        if not state.get("state"):
            return 0
        return int(state.get("speed", 0))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if percentage is None or percentage == 0:
            # Turning on without a requested speed: resume the last known speed
            # (as the BuildTrack app does), or fall back to full speed. Sending
            # speed 0 would turn the relay on but leave the fan not spinning.
            current = int(self.hub.get_device_state(self.id).get("speed", 0) or 0)
            percentage = current if current > 0 else 100
        speed = self._snap_speed(percentage)
        _LOGGER.info("Turning on fan '%s' (id=%s) speed=%s", self.name, self.id, speed)
        await self.hub.switch_on(self.id, speed=speed)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        _LOGGER.info("Turning off fan '%s' (id=%s)", self.name, self.id)
        await self.hub.switch_off(self.id)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the fan speed percentage."""
        if percentage == 0:
            _LOGGER.info("Turning off fan '%s' (id=%s) via 0%%", self.name, self.id)
            await self.hub.switch_off(self.id)
        else:
            speed = self._snap_speed(percentage)
            _LOGGER.info("Setting fan '%s' (id=%s) to speed %s", self.name, self.id, speed)
            await self.hub.switch_on(self.id, speed=speed)
