"""This is a wrapper class to interact with the build track curtain."""
import logging
from os import pread
from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_CLOSED, STATE_PAUSED
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
        BuildTrackCurtainEntity(hass, api, curtain)
        for curtain in await hass.async_add_executor_job(api.get_devices_of_type, "curtain")
    )


class BuildTrackCurtainEntity(CoverEntity):

    percentage: int = 0
    selected_preset_mode = "Low"
    preset_modes = ["Very Low", "Low", "Medium", "High", "Very High"]

    def __init__(self, hass, hub, curtain) -> None:
        """Initialize the Buildtrack curtain."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.room_name = curtain["room_name"]
        self.room_id = curtain["room_id"]
        self.id = curtain["ID"]
        self.curtain_name = curtain["label"]
        self.curtain_pin_type = curtain["pin_type"]
        self.hub.listen_device_state(self.id)
        # self.async_schedule_update_ha_state()

    @property
    def name(self) -> str:
        """Formulates the device name."""
        return f"{self.room_name} {self.curtain_name}"

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def state(self) -> str :
        return STATE_PAUSED

    @property
    def device_class(self) -> CoverDeviceClass:
        return CoverDeviceClass.CURTAIN

    def open_cover(self, **kwargs: Any) -> None:
        self.hub.open_cover(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_cover_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "open_cover",
            },
        )

    def close_cover(self, **kwargs: Any) -> None:
        self.hub.close_cover(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_cover_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "close_cover",
            },
        )

    def stop_cover(self, **kwargs):
        self.hub.stop_cover(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_cover_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "stop_cover",
            },
        )
