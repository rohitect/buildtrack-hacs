"""Config flow for Buildtrack integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .buildtrack_api import BuildTrackAPI
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# adjust the data schema to the data that you need
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        # vol.Required("host"): str,
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


# class BuildtrackHub:
#     """Placeholder class to make tests pass."""

#     def __init__(self, username: str, password: str) -> None:
#         """Initialize."""
#         self.username = username
#         self.password = password

#     def authenticate(self, hass: HomeAssistant, username: str, password: str):
#         """Test if we can authenticate with the host."""
#         try:
#             response = requests.post(
#                 "http://ezcentral.buildtrack.in/btadmin/index.php/commonrestappservice/login/format/json",
#                 data=f"useremail={username}&userpassword={password}&rememberme=true&type=authenticate",
#                 headers={
#                     'content-type': 'application/x-www-form-urlencoded'
#                 }
#             )
#             data = response.json()
#             return data
#         except:
#             raise CannotConnect


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    # validate the data can be used to set up a connection.

    # If your PyPI package is not built with async, pass your methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     your_validate_func, data["username"], data["password"]
    # )

    hub = BuildTrackAPI()
    hub.set_credentials(data["username"], data["password"])
    # hub = BuildTrackAPI('rohitranjan','Rt64juVFDFmqE2S')

    # if not await hass.async_add_executor_job(hub.authenticate,hass,data["username"], data["password"]):
    is_authenticated = await hass.async_add_executor_job(hub.authenticate_user)

    if not is_authenticated:
        # api = BuildTrackAPI(data['username'],data['password'])
        # api = BuildTrackAPI('rohitranjan','Rt64juVFDFmqE2S')
        # if not await hass.async_add_executor_job(api.authenticate_user)):
        raise InvalidAuth

    # If you cannot connect:
    # throw CannotConnect
    # If the authentication is wrong:
    # InvalidAuth

    # Return info that you want to store in the config entry.
    return {
        "title": f"{hub.get_first_name()}'s Buildtrack",
        "username": data["username"],
        "password": data["password"],
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Buildtrack."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=info["title"],
                data=user_input,
            )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
