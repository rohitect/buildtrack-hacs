"""Platform for cover integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
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
    """Set up Buildtrack cover entities."""
    api: BuildTrackAPI = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities(
        BuildTrackCurtainEntity(hass, api, curtain)
        for curtain in api.get_devices_of_type("curtain")
    )


class BuildTrackCurtainEntity(CoverEntity):

    _attr_is_closed: bool | None = None
    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, hass, hub, curtain) -> None:
        """Initialize the Buildtrack curtain."""
        super().__init__()
        self.hass = hass
        self.hub = hub
        self.room_name = curtain["room_name"]
        self.room_id = curtain["room_id"]
        self.id = curtain["ID"]
        self._attr_unique_id = f"buildtrack_cover_{curtain['ID']}"
        self.curtain_name = curtain["label"]
        self.curtain_pin_type = curtain["pin_type"]
        self.hub.listen_device_state(self.id)

    async def async_added_to_hass(self) -> None:
        """Register state update callback when entity is added."""
        _LOGGER.debug("Cover '%s' added to hass, registering state callback", self.name)
        self.hub.register_state_callback(self.id, self._handle_state_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister state update callback when entity is removed."""
        _LOGGER.debug("Cover '%s' removed from hass, unregistering state callback", self.name)
        self.hub.remove_state_callback(self.id, self._handle_state_update)

    def _handle_state_update(self) -> None:
        """Handle state update from MQTT/WS (called from background thread)."""
        # _LOGGER.debug("Cover '%s' received state update", self.name)
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

    @property
    def name(self) -> str:
        """Return the entity name."""
        return f"{self.room_name} {self.curtain_name}"


    @property
    def device_class(self) -> CoverDeviceClass:
        return CoverDeviceClass.CURTAIN

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        _LOGGER.info("Opening cover '%s' (id=%s)", self.name, self.id)
        await self.hub.open_cover(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_cover_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "open_cover",
            },
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        _LOGGER.info("Closing cover '%s' (id=%s)", self.name, self.id)
        await self.hub.close_cover(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_cover_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "close_cover",
            },
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        _LOGGER.info("Stopping cover '%s' (id=%s)", self.name, self.id)
        await self.hub.stop_cover(self.id)
        self.hass.bus.fire(
            event_type="buildtrack_cover_state_change",
            event_data={
                "integration": "buildtrack",
                "entity_name": self.name,
                "state": "stop_cover",
            },
        )
