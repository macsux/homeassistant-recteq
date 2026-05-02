"""Base class shared by all four platforms — keeps the device-info, name,
and unique_id logic in one place so the per-platform files stay tiny.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_NAME, DOMAIN
from .coordinator import RecTeqCoordinator


class RecTeqEntity(CoordinatorEntity[RecTeqCoordinator]):
    """All RecTeq entities share device-info anchored to the BBQ as a single device.

    Uses HA's standard `has_entity_name=True` so entity_ids land at
    `<platform>.<device_slug>_<entity_slug>` — e.g. `switch.dualfire_1200_bbq_left_burner`.
    The device-name prefix disambiguates multiple grills automatically.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RecTeqCoordinator,
        entry: ConfigEntry,
        dp: int,
        slug: str,
        friendly_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._dp = dp
        self._slug = slug
        # HA prefixes this with the device name in the entity_id; the visible
        # name here is just the entity portion, e.g. "BBQ Left Burner".
        self._attr_name = f"BBQ {friendly_name}"
        self._attr_unique_id = f"{entry.data['device_id']}_{dp}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["device_id"])},
            name=entry.data.get(CONF_DEVICE_NAME) or "RecTeq",
            manufacturer="RecTeq",
            model=entry.data.get(CONF_DEVICE_NAME) or "DualFire",
            configuration_url=f"http://{entry.data['host']}",
        )

    @property
    def _dp_value(self) -> Any:
        return (self.coordinator.data or {}).get(self._dp)

    @property
    def available(self) -> bool:
        return super().available and self._dp_value is not None
