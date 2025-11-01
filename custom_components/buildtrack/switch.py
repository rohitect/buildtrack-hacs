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
    """Set up the Demo config entry."""
    # await async_setup_platform(hass, config_entry, async_add_entities)
    # username = config['username']
    # password = config['password']
    api: BuildTrackAPI = hass.data[DOMAIN][config_entry.entry_id]
    # if not await hass.async_add_executor_job(api.authenticate_user):
    #     _LOGGER.error("Invalid Buildtrack credentials")
    #     return
    async_add_entities(
        BuildtrackSwitch(hass, api, switch)
        for switch in await hass.async_add_executor_job(api.get_devices_of_type, "switch")
    )


class BuildtrackSwitch(SwitchEntity):
    """Representation of Buildtrack switch."""

    hub: BuildTrackAPI
    is_device_on = False

    def __init__(self, hass, hub, switch) -> None:
        """Initialize the Buildtrack switch."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.room_name = switch["room_name"]
        self.room_id = switch["room_id"]
        self.id = switch["ID"]
        self.switch_name = switch["label"]
        self.switch_pin_type = switch["pin_type"]
        self.hub.listen_device_state(self.id)
        # self.async_schedule_update_ha_state()

    @property
    def name(self) -> str:
        """Formulates the device name."""
        return f"{self.room_name} {self.switch_name}"

    @property
    def is_on(self) -> bool:
        """States whether the device is on or off."""
        return self.hub.is_device_on(self.id)

    async def async_turn_on(self, **kwargs) -> None:
        """Switche on the device."""
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
        """Switche off the device."""
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
        """Toggles the device state."""
        return await self.hub.toggle_device(self.id)

    # async def async_update(self):
    #     self.is_device_on = await self.hub.refresh_device_state(self.id)
    #     print(self.is_device_on)
