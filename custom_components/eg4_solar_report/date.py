from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ReportManager
from .entity import ReportEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReportEndDate(manager, entry)])


class ReportEndDate(ReportEntity, DateEntity):
    """Last day of the report. Resets to today at midnight; 7 days ends on this date."""

    _attr_name = "Report End Date"
    _attr_icon = "mdi:calendar-end"

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "report_end_date")

    @property
    def native_value(self) -> date:
        return self._manager.end_date

    async def async_set_value(self, value: date) -> None:
        self._manager.end_date = value
        self._manager._notify_listeners()
