from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_INVERTERS,
    CONF_PASSWORD,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_USERNAME,
    CONF_UTILITY_NAME,
    DOMAIN,
)
from .coordinator import ReportManager

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, CONF_PLANT_ID, CONF_PLANT_NAME, CONF_INVERTERS, CONF_UTILITY_NAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    report = manager.report or {}
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "state": {
            "verdict": manager.state,
            "error": manager.error,
            "period": manager.period,
            "end_date": manager.end_date.isoformat(),
            "last_generated": manager.last_generated.isoformat() if manager.last_generated else None,
        },
        "report": {
            "range": report.get("range"),
            "counts": report.get("counts"),
            "findings": report.get("findings", []),
        },
    }
