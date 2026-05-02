"""Single-device polling coordinator using tinytuya in an executor.

tinytuya is a sync library, so each poll runs in HA's executor pool. With
DEFAULT_SCAN_INTERVAL=1s this is well under what one thread can sustain — we
deliberately keep one connection open and reuse it (`device.set_socketPersistent`)
so we don't pay TCP+handshake every second.

If the device's localKey rotates (rare but happens), the local connection
fails authentication. The coordinator catches that, runs the OEM API path
once to fetch the new key, and reconnects.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PASSWORD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PROTOCOL_VERSION,
)
from .oem_api import OemApiClient, OemApiError, discover_lan_ip

_LOGGER = logging.getLogger(__name__)


class RecTeqCoordinator(DataUpdateCoordinator[dict[int, Any]]):
    """Coordinator for one RecTeq grill — owns one tinytuya socket."""

    # Tolerate this many consecutive transient failures before escalating to
    # the heavy "rescan LAN / refresh local key" recovery path. tinytuya's
    # `status()` will occasionally return an error-dict instead of raising
    # (e.g. when a packet collides with a phone-app poll); silently riding
    # over those keeps the dashboard from flashing "unavailable".
    _CONSECUTIVE_FAILS_BEFORE_RECOVERY = 5

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"recteq[{entry.data[CONF_DEVICE_ID]}]",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._entry = entry
        self._device = None  # tinytuya.OutletDevice — created lazily on first poll
        self._lock = asyncio.Lock()  # serialize set_dp + status calls
        self._key_refreshed_once = False  # avoid infinite refresh loops
        self._consecutive_fails = 0

    @property
    def host(self) -> str:
        return self._entry.data[CONF_HOST]

    @property
    def device_id(self) -> str:
        return self._entry.data[CONF_DEVICE_ID]

    @property
    def local_key(self) -> str:
        return self._entry.data[CONF_LOCAL_KEY]

    # ── Polling ────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[int, Any]:
        async with self._lock:
            try:
                data = await self.hass.async_add_executor_job(self._poll_once)
                self._consecutive_fails = 0
                self._key_refreshed_once = False
                return data
            except _AuthFailed:
                if self._key_refreshed_once:
                    raise UpdateFailed("local key rejected after refresh")
                self._key_refreshed_once = True
                _LOGGER.info("local key rejected — refreshing via OEM API")
                await self._refresh_local_key()
                self._device = None  # force reconnect with new key
                return await self.hass.async_add_executor_job(self._poll_once)
            except _Transient as exc:
                # Single transient hiccup — keep last-good data so entities
                # don't flash unavailable. Only escalate to a full LAN
                # rescan after several in a row (real outage).
                self._consecutive_fails += 1
                if self._consecutive_fails < self._CONSECUTIVE_FAILS_BEFORE_RECOVERY:
                    _LOGGER.debug(
                        "transient poll failure %d/%d (%s)",
                        self._consecutive_fails,
                        self._CONSECUTIVE_FAILS_BEFORE_RECOVERY,
                        exc,
                    )
                    return self.data or {}
                _LOGGER.info("device quiet for %ds — re-scanning LAN", self._consecutive_fails)
                new_ip = await discover_lan_ip(self.device_id, timeout=4.0)
                if new_ip and new_ip != self.host:
                    self.hass.config_entries.async_update_entry(
                        self._entry,
                        data={**self._entry.data, CONF_HOST: new_ip},
                    )
                    self._device = None
                    return await self.hass.async_add_executor_job(self._poll_once)
                raise UpdateFailed(f"device unreachable at {self.host}")

    def _poll_once(self) -> dict[int, Any]:
        """Sync — runs in executor. Returns {dp_id: value}."""
        import tinytuya

        if self._device is None:
            self._device = tinytuya.OutletDevice(
                self.device_id, self.host, self.local_key, version=PROTOCOL_VERSION
            )
            # NON-persistent socket: each status() call opens a fresh TCP
            # connection + handshake (~150ms overhead), then closes. Trades a
            # bit of latency for guaranteed fresh state. Persistent sockets
            # were occasionally returning stale switch states when the phone
            # app evicted our session — a half-dead socket would keep merging
            # cached values, making HA report OFF while the grill was actually
            # ON. With short-lived connections each poll re-establishes from
            # scratch and can't get stuck.
            self._device.set_socketPersistent(False)
            self._device.set_socketTimeout(3)

        try:
            data = self._device.status()
        except Exception as exc:  # tinytuya raises bare Exception; map by message
            msg = str(exc).lower()
            if "key" in msg or "login" in msg or "auth" in msg:
                raise _AuthFailed(str(exc)) from exc
            raise _Transient(str(exc)) from exc

        # tinytuya often returns {Err, Error} dicts on transient hiccups
        # (collisions with the phone app, brief disconnects). Treat as
        # transient — coordinator caches last-good data through these.
        if not data or "Err" in data or "Error" in data or "dps" not in data:
            raise _Transient(f"status returned no dps: {data}")
        # tinytuya keys DPs as strings — normalize to ints for downstream lookup.
        new_dps = {int(k): v for k, v in data["dps"].items()}
        # MERGE into prior state instead of replacing. Tuya devices commonly
        # respond with just the DPs that changed (delta semantics), not the
        # full 20-DP state. Replacing would zero out every other entity each
        # poll → entity._dp_value is None → "unavailable" flicker on the UI.
        merged = dict(self.data or {})
        merged.update(new_dps)
        return merged

    # ── Commands ───────────────────────────────────────────────────────

    async def async_set_dp(self, dp: int, value: Any) -> None:
        """Send a write to one DP, then trigger an immediate refresh."""
        async with self._lock:
            await self.hass.async_add_executor_job(self._set_dp_sync, dp, value)
        await self.async_request_refresh()

    def _set_dp_sync(self, dp: int, value: Any) -> None:
        if self._device is None:
            # Trigger lazy connect via a status call before the write.
            self._poll_once()
        self._device.set_value(dp, value, nowait=False)

    # ── Local key refresh ──────────────────────────────────────────────

    async def _refresh_local_key(self) -> None:
        """Re-auth against OEM API and pull the current localKey."""
        session = async_get_clientsession(self.hass)
        client = OemApiClient(session)
        try:
            await client.login(
                self._entry.data[CONF_EMAIL], self._entry.data[CONF_PASSWORD]
            )
            dev = await client.get_device(self.device_id)
        except (OemApiError, ClientError) as exc:
            raise UpdateFailed(f"key refresh failed: {exc}") from exc

        if dev.local_key and dev.local_key != self.local_key:
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, CONF_LOCAL_KEY: dev.local_key},
            )
        # Reset the latch — we just successfully refreshed.
        self._key_refreshed_once = False


class _AuthFailed(Exception):
    pass


class _Transient(Exception):
    """Brief failure tolerated by the coordinator's consecutive-fails latch."""
