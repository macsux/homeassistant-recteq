"""Binary sensors — error flags (DP 115–120)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
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
        RecTeqBinarySensor(coord, entry, dp, slug, friendly, extras)
        for dp, plat, slug, friendly, extras in dps
        if plat == "binary_sensor"
    )


class RecTeqBinarySensor(RecTeqEntity, BinarySensorEntity):
    def __init__(self, coord, entry, dp, slug, friendly, extras: dict[str, Any]) -> None:
        super().__init__(coord, entry, dp, slug, friendly)
        if extras.get("device_class") == "problem":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        v = self._dp_value
        return None if v is None else bool(v)
