"""Switch entities — burner / power on-off (DPs per model in const.py)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, dp_map_for
from .coordinator import RecTeqCoordinator
from .entity import RecTeqEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback
) -> None:
    coord: RecTeqCoordinator = hass.data[DOMAIN][entry.entry_id]
    dps = dp_map_for(entry.data)
    add_entities(
        RecTeqSwitch(coord, entry, dp, slug, friendly)
        for dp, plat, slug, friendly, _extras in dps
        if plat == "switch"
    )


class RecTeqSwitch(RecTeqEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        v = self._dp_value
        return None if v is None else bool(v)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp, False)
