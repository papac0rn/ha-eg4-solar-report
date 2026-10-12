from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, VERDICT_ACT, VERDICT_ERROR
from .coordinator import ReportManager
from .entity import ReportEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ActionNeededBinarySensor(manager, entry)])


class ActionNeededBinarySensor(ReportEntity, BinarySensorEntity):
    _attr_name = "Action Needed"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "action_needed")

    @property
    def is_on(self) -> bool | None:
        state = self._manager.state
        if state is None:
            return None
        return state in (VERDICT_ACT, VERDICT_ERROR)
