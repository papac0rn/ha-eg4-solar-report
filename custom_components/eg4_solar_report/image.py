from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .charts import CHARTS
from .const import DOMAIN
from .coordinator import ReportManager
from .entity import ReportEntity

CHART_NAMES = {
    "harvest": "Chart Harvest",
    "energy": "Chart Energy",
    "pv_ac": "Chart PV AC",
    "grid_voltage": "Chart Grid Voltage",
    "soc": "Chart SOC",
    "cell_voltage": "Chart Cell Voltage",
    "temperatures": "Chart Temperatures",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReportChartImage(hass, manager, entry, key) for key in CHARTS])


class ReportChartImage(ReportEntity, ImageEntity):
    """One report chart as an SVG, served behind login through the image proxy."""

    _attr_content_type = "image/svg+xml"
    _attr_icon = "mdi:chart-line"

    def __init__(
        self, hass: HomeAssistant, manager: ReportManager, entry: ConfigEntry, key: str
    ) -> None:
        ReportEntity.__init__(self, manager, entry, f"chart_{key}")
        ImageEntity.__init__(self, hass)
        self._key = key
        self._attr_name = CHART_NAMES[key]
        self._attr_image_last_updated = manager.charts_updated

    async def async_image(self) -> bytes | None:
        return self._manager.charts.get(self._key)

    @callback
    def _handle_update(self) -> None:
        # A new image_last_updated changes the entity's access URL, so the frontend fetches the new chart
        self._attr_image_last_updated = self._manager.charts_updated
        super()._handle_update()
