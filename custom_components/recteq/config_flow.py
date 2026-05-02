"""UI flow: login → list devices via cloud → discover IP → write entry.

Discovery now happens via the cloud API: `thing.m.user.email.password.login`
followed by `tuya.m.my.group.device.list` (with `gid` as a URL param, one
call per location). This works for every user, every network setup. The
LAN UDP scan is now used only to look up a device's *current local IP*
once we already know its devId — which still works perfectly on
HAOS/Linux/Pi installs but fails inside Docker Desktop on macOS where
broadcast traffic doesn't traverse the bridge. For that case we fall
through to a manual IP entry step.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_EMAIL,
    CONF_HOST,
    CONF_LOCAL_KEY,
    DOMAIN,
    PRODUCT_DP_MAPS,
)
from .oem_api import (
    CloudDevice,
    OemApiClient,
    OemApiError,
    OemAuthError,
    discover_lan_ip,
)

_LOGGER = logging.getLogger(__name__)


class RecTeqConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        self._client: OemApiClient | None = None
        self._supported: list[CloudDevice] = []
        self._chosen: CloudDevice | None = None

    # ── Step 1: credentials ─────────────────────────────────────────────

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = user_input[CONF_PASSWORD]

            session = async_get_clientsession(self.hass)
            self._client = OemApiClient(session)

            try:
                await self._client.login(self._email, self._password)
                devices = await self._client.list_devices()
            except OemAuthError:
                errors["base"] = "invalid_auth"
            except OemApiError as exc:
                _LOGGER.warning("RecTeq API error during login/list: %s", exc)
                errors["base"] = "api_error"
            except ClientError as exc:
                _LOGGER.warning("Network error during login: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                supported = [d for d in devices if d.product_id in PRODUCT_DP_MAPS]
                if not supported:
                    return self.async_abort(reason="no_supported_devices")
                self._supported = supported
                if len(supported) == 1:
                    self._chosen = supported[0]
                    return await self.async_step_resolve_ip()
                return await self.async_step_pick_device()

        schema = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    # ── Step 2: device picker (only when multiple) ─────────────────────

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._chosen = next(
                d for d in self._supported if d.dev_id == user_input[CONF_DEVICE_ID]
            )
            return await self.async_step_resolve_ip()

        options = {
            d.dev_id: f"{d.name or 'RecTeq'} ({d.dev_id[-8:]})" for d in self._supported
        }
        schema = vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(options)})
        return self.async_show_form(step_id="pick_device", data_schema=schema)

    # ── Step 3: resolve LAN IP via UDP scan, or fall back to manual ────

    async def async_step_resolve_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        # Same-device guard.
        await self.async_set_unique_id(self._chosen.dev_id)
        self._abort_if_unique_id_configured()

        ip = await discover_lan_ip(self._chosen.dev_id, timeout=4.0)
        if ip:
            return self._create(ip)
        return await self.async_step_manual_ip()

    async def async_step_manual_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            ip = user_input[CONF_HOST].strip()
            if not ip or any(c not in "0123456789." for c in ip):
                errors[CONF_HOST] = "invalid_host"
            else:
                return self._create(ip)

        schema = vol.Schema({vol.Required(CONF_HOST): str})
        return self.async_show_form(
            step_id="manual_ip",
            data_schema=schema,
            errors=errors,
            description_placeholders={"device_name": self._chosen.name or "RecTeq"},
        )

    # ── Finalize ────────────────────────────────────────────────────────

    def _create(self, ip: str) -> FlowResult:
        d = self._chosen
        return self.async_create_entry(
            title=d.name or "RecTeq",
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_DEVICE_ID: d.dev_id,
                CONF_LOCAL_KEY: d.local_key,
                CONF_HOST: ip,
                CONF_DEVICE_NAME: d.name or "RecTeq",
            },
        )
