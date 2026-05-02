"""Writable numeric controls — setpoints + feed rate + calibration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PRODUCT_DP_MAPS
from .coordinator import RecTeqCoordinator
from .entity import RecTeqEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coord: RecTeqCoordinator = hass.data[DOMAIN][entry.entry_id]
    dps = PRODUCT_DP_MAPS["q5utybemjsoh72nx"]
    add_entities(
        RecTeqNumber(coord, entry, dp, slug, friendly, extras)
        for dp, plat, slug, friendly, extras in dps
        if plat == "number"
    )


class RecTeqNumber(RecTeqEntity, NumberEntity):
    def __init__(self, coord, entry, dp, slug, friendly, extras: dict[str, Any]) -> None:
        super().__init__(coord, entry, dp, slug, friendly)
        if "min" in extras:
            self._attr_native_min_value = extras["min"]
        if "max" in extras:
            self._attr_native_max_value = extras["max"]
        if "step" in extras:
            self._attr_native_step = extras["step"]
        if "unit" in extras:
            self._attr_native_unit_of_measurement = extras["unit"]
        if "icon" in extras:
            self._attr_icon = extras["icon"]

    @property
    def native_value(self) -> float | None:
        v = self._dp_value
        return None if v is None else float(v)

    async def async_set_native_value(self, value: float) -> None:
        # Tuya numerics are integer DPs — cast on send.
        await self.coordinator.async_set_dp(self._dp, int(value))
