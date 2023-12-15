"""This is a wrapper class to interact with the build track fan."""
import logging
from os import pread
from typing import Any
from homeassistant.util.percentage import ordered_list_item_to_percentage, percentage_to_ordered_list_item

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import ToggleEntity
from homeassistant.components.fan import SUPPORT_PRESET_MODE, SUPPORT_SET_SPEED, FanEntity
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

# async def async_migrate_entry(hass, config_entry: ConfigEntry):
#     _LOGGER.debug("Migrating from version %s", config_entry.version)

#     if config_entry.version == 3:

#         new = {**config_entry.data}
#         # TODO: modify Config Entry data

#         config_entry.version = 4
#         hass.config_entries.async_update_entry(config_entry, data=new)

#     _LOGGER.info("Migration to version %s successful", config_entry.version)
#     return True


class BuildTrackFanEntity(FanEntity):

    percentage: int = 0
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
        self.fan_name = fan["label"]
        self.fan_pin_type = fan["pin_type"]
        # print(f"[FAN] Register listen to {self.room_name} {self.fan_name}...")
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
    def is_on(self):
        return self.hub.is_device_on(self.id)

    @property
    def supported_features(self) -> int:
        return SUPPORT_SET_SPEED | SUPPORT_PRESET_MODE 

    @property
    def oscillating(self) -> bool:
        return False

    @property
    def percentage(self) -> int:
        return self.hub.get_device_state(self.id)["speed"]
        # return ordered_list_item_to_percentage(self.preset_modes, self.hub.get_device_state(self.id)["speed"])

    @property
    def speed_count(self) -> int:
        # return 4
        return len(self.preset_modes)

    @property
    def should_poll(self) -> bool:
        return True
    

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
        current_speed = await self.percentage
        if current_speed + percentage_step > 100:
            return
        else:
            self.set_percentage(current_speed + percentage_step)

    async def async_decrease_speed(self, percentage_step) -> None:
        current_speed = await self.percentage
        if current_speed + percentage_step < 0:
            return
        else:
            self.set_percentage(current_speed - percentage_step)

    async def async_set_percentage(self, percentage: int) -> None:
        await self.hub.switch_on(self.id, percentage)
        self.hass.bus.fire(
            event_type="buildtrack_fan_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "percentage",
            },
        )

    async def async_turn_on(self, speed, percentage, preset_mode, **kwargs) -> None:
        """Switch on the device."""
        if percentage is not None:
            await self.async_set_percentage( percentage)
        elif preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        else:
            await self.hub.switch_on(self.id, speed=speed)
            
        self.hass.bus.fire(
            event_type="buildtrack_fan_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "on",
                "speed": speed,
                "percentage": percentage,
                "preset_mode": preset_mode
            },
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Switch off the device."""
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
        index = self.preset_modes.index(preset_mode)
        if index == 0:
            await self.async_set_percentage(25)
        elif index == 1:
            await self.async_set_percentage(50)
        elif index == 2:
            await self.async_set_percentage(75)
        elif index == 3:
            await self.async_set_percentage(100)

    async def async_update(self) -> None:
        pass
        # self.percentage = self.hub.get_device_state(self.id)["speed"]
    
    

    # async def async_set_percentage(self, percentage: int) -> None:
    #     await self.hub.switch_on(self.id, percentage)
