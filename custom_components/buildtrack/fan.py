"""This is a wrapper class to interact with the build track switch."""
import logging
from os import pread
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import ToggleEntity
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
    api: BuildTrackAPI = hass.data[DOMAIN][config_entry.entry_id]
    # if not await hass.async_add_executor_job(api.authenticate_user):
    #     _LOGGER.error("Invalid Buildtrack credentials")
    #     return
    async_add_entities(
        BuildTrackFanEntity(hass, api, fan)
        for fan in await hass.async_add_executor_job(api.get_devices_of_type, "fan")
    )


class BuildTrackFanEntity(ToggleEntity):

    percentage: int = 0
    selected_preset_mode = "Low"
    preset_modes = ["Very Low", "Low", "Medium", "High", "Very High"]

    def __init__(self, hass, hub, fan) -> None:
        """Initialize the Buildtrack fan."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.room_name = fan["room_name"]
        self.room_id = fan["room_id"]
        self.id = fan["ID"]
        self.fan_name = fan["label"]
        self.fan_pin_type = fan["pin_type"]
        self.hub.listen_device_state(self.id)
        # self.async_schedule_update_ha_state()

    @property
    def name(self) -> str:
        """Formulates the device name."""
        return f"{self.room_name} {self.fan_name}"

    @property
    def current_direction(self) -> str:
        return 'Clockwise'

    @property
    def is_on(self) -> bool :
        return False

    @property
    def oscillating(self) -> bool:
        return False

    @property
    def percentage(self) -> int:
        return self.percentage

    @property
    def speed_count(self) -> int:
        return 100
    
    @property
    def should_poll(self) -> bool:
        return False
    
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


    @property
    def preset_mode(self) -> str:
        if self.percentage > 0 and self.percentage <= 10:
            self.selected_preset_mode = self.preset_modes[0]
        elif self.percentage > 11 and self.percentage <= 30:
            self.selected_preset_mode = self.preset_modes[1]
        elif self.percentage > 31 and self.percentage <= 70:
            self.selected_preset_mode = self.preset_modes[2]
        elif self.percentage > 71 and self.percentage <= 90:
            self.selected_preset_mode = self.preset_modes[3]
        elif self.percentage > 90:
            self.selected_preset_mode = self.preset_modes[4]
        return self.selected_preset_mode

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        pass
