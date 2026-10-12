from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PERIODS
from .coordinator import ReportManager
from .entity import ReportEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReportPeriodSelect(manager, entry)])


class ReportPeriodSelect(ReportEntity, SelectEntity):
    _attr_name = "Report Period"
    _attr_icon = "mdi:calendar-range"
    _attr_options = PERIODS

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "report_period")

    @property
    def current_option(self) -> str:
        return self._manager.period

    async def async_select_option(self, option: str) -> None:
        self._manager.period = option
        self._manager._notify_listeners()
