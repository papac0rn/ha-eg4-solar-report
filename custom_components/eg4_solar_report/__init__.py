from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, PERIODS, SERVICE_GENERATE
from .coordinator import ReportManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "select", "date", "button"]

GENERATE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("period"): vol.In(PERIODS),
        vol.Optional("end_date"): cv.date,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = ReportManager(hass, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if not hass.services.has_service(DOMAIN, SERVICE_GENERATE):
        hass.services.async_register(
            DOMAIN, SERVICE_GENERATE, _make_generate_handler(hass), schema=GENERATE_SCHEMA
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    manager.async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_GENERATE)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _make_generate_handler(hass: HomeAssistant):
    async def _handle(call: ServiceCall) -> None:
        managers: dict[str, ReportManager] = hass.data.get(DOMAIN, {})
        entry_id = call.data.get("config_entry_id")
        if entry_id:
            if entry_id not in managers:
                raise ServiceValidationError(f"No EG4 Solar Report entry {entry_id}")
            targets = [managers[entry_id]]
        else:
            targets = list(managers.values())
        for manager in targets:
            await manager.async_generate(
                call.data.get("period"), call.data.get("end_date"), trigger="service"
            )

    return _handle
