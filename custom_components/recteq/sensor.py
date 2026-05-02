"""Read-only sensors — pit + probe temps (DP 105–110)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
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
        RecTeqSensor(coord, entry, dp, slug, friendly, extras)
        for dp, plat, slug, friendly, extras in dps
        if plat == "sensor"
    )


class RecTeqSensor(RecTeqEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord, entry, dp, slug, friendly, extras: dict[str, Any]) -> None:
        super().__init__(coord, entry, dp, slug, friendly)
        if "unit" in extras:
            self._attr_native_unit_of_measurement = extras["unit"]
            # Lock the suggested-display unit too so HA's metric-system locale
            # doesn't auto-convert °F to °C on the user.
            self._attr_suggested_unit_of_measurement = extras["unit"]
        if extras.get("device_class") == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE

    @property
    def native_value(self) -> Any:
        return self._dp_value
