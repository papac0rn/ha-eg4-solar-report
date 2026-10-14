from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import persistent_notification
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, PERIODS, SERVICE_GENERATE
from .coordinator import ReportManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "select", "date", "button", "image"]

GENERATE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Optional("period"): vol.In(PERIODS),
        vol.Optional("end_date"): cv.date,
    }
)


CARD_URL = "/eg4_solar_report_static"


class _CardPingView(HomeAssistantView):
    """TEMPORARY diagnostic: the report card reports that it loaded (or failed), and on which browser."""

    url = "/api/eg4_solar_report/card_ping"
    name = "api:eg4_solar_report:card_ping"
    requires_auth = False

    async def get(self, request):
        q = request.query
        _LOGGER.warning("Report card %s on %s: %s", q.get("e", "?")[:20], q.get("ua", "?")[:200], q.get("m", "")[:300])
        return self.json({})


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the report card and load it in every browser, so no HACS frontend install is needed."""
    if hass.data.get(f"{DOMAIN}_card"):
        return
    hass.data[f"{DOMAIN}_card"] = True
    from pathlib import Path

    from homeassistant.components import frontend
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.loader import async_get_integration

    folder = Path(__file__).parent / "frontend"
    hass.http.register_view(_CardPingView())
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(folder), False)])
    version = (await async_get_integration(hass, DOMAIN)).version
    url = f"{CARD_URL}/eg4-solar-report-card.js?v={version}"
    # Load it as a dashboard resource, the way HACS cards load. An extra script on the main page as well
    # defined the card where some Android app WebViews' dashboards never saw it ("Custom element doesn't
    # exist"), so the extra script is only the fallback when resources are managed in YAML.
    try:
        added = await _async_ensure_resource(hass, url)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not add the report card as a dashboard resource: %s", err)
        added = False
    if not added:
        frontend.add_extra_js_url(hass, url)


async def _async_ensure_resource(hass: HomeAssistant, url: str) -> None:
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None or not hasattr(resources, "async_create_item"):
        return  # YAML-mode resources are managed by the owner
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    base = url.split("?")[0]
    for item in resources.async_items():
        if str(item.get("url", "")).split("?")[0] == base:
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_register_card(hass)
    manager = ReportManager(hass, entry)
    await manager.async_load()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.async_start()

    # Put the report where the owner chose (a new dashboard by default). Done when the choice changes,
    # not on every restart, so a dashboard or tab the owner removed isn't brought back.
    from .button import async_place_report, report_location

    target = report_location(entry)
    if entry.data.get("report_placed_at") != target:
        try:
            where = await async_place_report(hass, entry, target)
        except Exception as err:  # noqa: BLE001 - setup must not fail over the dashboard
            _LOGGER.warning("Could not add the Solar Report to the chosen dashboard: %s", err)
            persistent_notification.async_create(
                hass, f"EG4 Solar Report couldn't add the report to the dashboard you picked: {err}",
                title="EG4 Solar Report", notification_id=f"{DOMAIN}_placement",
            )
        else:
            hass.config_entries.async_update_entry(entry, data={**entry.data, "report_placed_at": target})
            if target != "none":
                persistent_notification.async_create(
                    hass, f"Your report is on {where}. Press **Generate Report** there to run it.",
                    title="EG4 Solar Report is ready", notification_id=f"{DOMAIN}_placement",
                )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    if not hass.services.has_service(DOMAIN, SERVICE_GENERATE):
        hass.services.async_register(
            DOMAIN, SERVICE_GENERATE, _make_generate_handler(hass), schema=GENERATE_SCHEMA
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager: ReportManager = hass.data[DOMAIN][entry.entry_id]
    manager.async_stop()
    await manager.client.async_close()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_GENERATE)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the saved report when the integration is removed."""
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()


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
