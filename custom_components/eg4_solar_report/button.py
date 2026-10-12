from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ReportManager
from .entity import ReportEntity

# The "Create Dashboard" button (ha-mak-grill pattern) is added once the report attributes are final


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GenerateReportButton(manager, entry)])


class GenerateReportButton(ReportEntity, ButtonEntity):
    _attr_name = "Generate Report"
    _attr_icon = "mdi:file-chart"

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "generate_report")

    async def async_press(self) -> None:
        # Downloads can take a while; don't hold the button press open
        self.hass.async_create_task(self._manager.async_generate())
