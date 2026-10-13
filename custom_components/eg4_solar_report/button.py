from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ReportManager
from .dashboard import build_dashboard
from .entity import ReportEntity

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL = "eg4-solar-report"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([GenerateReportButton(manager, entry), CreateDashboardButton(manager, entry)])


class GenerateReportButton(ReportEntity, ButtonEntity):
    _attr_name = "Generate Report"
    _attr_icon = "mdi:file-chart"

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "generate_report")

    async def async_press(self) -> None:
        # Downloads can take a while; don't hold the button press open
        self.hass.async_create_task(self._manager.async_generate())


class CreateDashboardButton(ReportEntity, ButtonEntity):
    """Creates the "Solar Report" dashboard, or rewrites it. It only ever touches its own dashboard."""

    _attr_name = "Create Dashboard"
    _attr_icon = "mdi:view-dashboard-edit"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "create_dashboard")

    async def async_press(self) -> None:
        lovelace = self.hass.data.get("lovelace")
        if lovelace is None or lovelace.dashboard_collection is None:
            raise HomeAssistantError("Dashboards aren't available")
        title = f"Solar Report · {self._entry.title}"
        if DASHBOARD_URL not in lovelace.dashboards:
            await lovelace.dashboard_collection.async_create_item({
                "url_path": DASHBOARD_URL,
                "title": "Solar Report",
                "icon": "mdi:solar-power-variant",
                "require_admin": False,
                "show_in_sidebar": True,
            })
        dashboard = lovelace.dashboards.get(DASHBOARD_URL)
        if dashboard is None:
            raise HomeAssistantError("The Solar Report dashboard could not be created")
        config = build_dashboard(er.async_get(self.hass), self._entry.entry_id, title)
        await dashboard.async_save(config)
        _LOGGER.info("Saved the Solar Report dashboard (%d cards)", len(config["views"][0]["cards"]))
