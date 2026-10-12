from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, VERDICT_ACT, VERDICT_ERROR, VERDICT_HEALTHY, VERDICT_WATCH
from .coordinator import ReportManager
from .entity import ReportEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ReportSensor(manager, entry), LastGeneratedSensor(manager, entry)])


class ReportSensor(ReportEntity, SensorEntity):
    """State is the verdict; the full report is in the attributes."""

    _attr_name = "Report"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [VERDICT_HEALTHY, VERDICT_WATCH, VERDICT_ACT, VERDICT_ERROR]
    # Keep the big attributes out of the recorder database
    _unrecorded_attributes = frozenset({"checks", "findings", "numbers", "daily", "series"})

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "report")

    @property
    def icon(self) -> str:
        return {
            VERDICT_HEALTHY: "mdi:solar-power-variant",
            VERDICT_WATCH: "mdi:eye-outline",
            VERDICT_ACT: "mdi:alert",
            VERDICT_ERROR: "mdi:alert-circle-outline",
        }.get(self.native_value or "", "mdi:file-chart-outline")

    @property
    def native_value(self) -> str | None:
        return self._manager.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        report = self._manager.report or {}
        return {
            "running": self._manager.running,
            "error": self._manager.error,
            "period": report.get("period"),
            "range": report.get("range"),
            "trigger": report.get("trigger"),
            "generated_at": report.get("generated_at"),
            "summary": report.get("summary"),
            "samples": report.get("samples"),
            "counts": report.get("counts"),
            "checks": report.get("checks", []),
            "findings": report.get("findings", []),
            "numbers": report.get("numbers", {}),
            "daily": report.get("daily", []),
            "series": report.get("series", {}),
        }


class LastGeneratedSensor(ReportEntity, SensorEntity):
    _attr_name = "Last Generated"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, manager: ReportManager, entry: ConfigEntry) -> None:
        super().__init__(manager, entry, "last_generated")

    @property
    def native_value(self) -> datetime | None:
        return self._manager.last_generated
