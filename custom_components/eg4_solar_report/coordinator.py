from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, UnitOfTemperature
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from . import analyzer, charts, ha_eg4
from .api import Eg4AuthError, Eg4Error, Eg4MonitorClient
from .const import (
    CONF_ARRAY_NAMES,
    CONF_BATTERY_KWH,
    CONF_CELL_V_MAX,
    CONF_GRIDBOSS,
    CONF_MPPT_LIMITS_A,
    CONF_OUTPUT_CEILING_KW,
    CONF_PACK_COUNT,
    CONF_PACK_DISCHARGE_A,
    CONF_PARALLEL_COUNT,
    CONF_PV_MAX_V,
    CONF_SERVICE_CHARGE,
    CONF_UTILITY_NAME,
    CONF_EXPORT_CREDIT,
    CONF_HV_ACT,
    CONF_HV_WATCH,
    CONF_IMPORT_RATE,
    CONF_INVERTERS,
    CONF_NOMINAL_VOLTAGE,
    CONF_PASSWORD,
    CONF_SERVER,
    CONF_SYSTEM_TYPE,
    CONF_USERNAME,
    DEFAULT_OUTAGE_DELAY,
    DEFAULT_WEEKLY_DAY,
    DEFAULT_WEEKLY_TIME,
    EVENT_REPORT_GENERATED,
    OPT_KNOWN_ISSUES,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_SEVERITIES,
    OPT_OUTAGE_DELAY,
    OPT_OUTAGE_ENABLED,
    OPT_OUTAGE_ENTITY,
    OPT_WEEKLY_DAY,
    OPT_WEEKLY_ENABLED,
    OPT_WEEKLY_TIME,
    PERIOD_7_DAYS,
    PERIOD_TODAY,
    TEMP_THRESHOLDS,
    OPT_TEMP_IMBALANCE,
    OPT_TEMP_UNIT,
    SERVERS,
    SEVERITY_ACT,
    VERDICT_ERROR,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)


class ReportManager:
    """Owns the report controls, runs the analyzer, and schedules the automatic runs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.client = Eg4MonitorClient(
            async_create_clientsession(hass),
            SERVERS[entry.data[CONF_SERVER]],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        self.period: str = PERIOD_TODAY
        self.end_date: date = dt_util.now().date()
        self.report: dict[str, Any] | None = None
        self.error: str | None = None
        self.last_generated: datetime | None = None
        self.charts: dict[str, bytes] = charts.render_placeholders()
        self.charts_updated: datetime = dt_util.utcnow()
        self.running = False
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._outage_timer: Callable[[], None] | None = None

    # Listener plumbing (same pattern as the entities in ha-mak-grill)
    def register_listener(self, cb: Callable[[], None]) -> None:
        self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[], None]) -> None:
        if cb in self._listeners:
            self._listeners.remove(cb)

    @callback
    def _notify_listeners(self) -> None:
        for cb in list(self._listeners):
            cb()

    @callback
    def async_start(self) -> None:
        opts = self.entry.options
        # The end date follows today unless the user picks another day
        self._unsubs.append(
            async_track_time_change(self.hass, self._midnight, hour=0, minute=0, second=5)
        )
        if opts.get(OPT_WEEKLY_ENABLED):
            hh, mm, ss = (int(p) for p in opts.get(OPT_WEEKLY_TIME, DEFAULT_WEEKLY_TIME).split(":"))
            self._unsubs.append(
                async_track_time_change(self.hass, self._weekly, hour=hh, minute=mm, second=ss)
            )
        outage_entity = opts.get(OPT_OUTAGE_ENTITY)
        if opts.get(OPT_OUTAGE_ENABLED) and outage_entity:
            self._unsubs.append(
                async_track_state_change_event(self.hass, [outage_entity], self._outage_changed)
            )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._outage_timer:
            self._outage_timer()
            self._outage_timer = None

    @callback
    def _midnight(self, now: datetime) -> None:
        self.end_date = now.date()
        self._notify_listeners()

    @callback
    def _weekly(self, now: datetime) -> None:
        day = self.entry.options.get(OPT_WEEKLY_DAY, DEFAULT_WEEKLY_DAY)
        if WEEKDAYS[now.weekday()] != day:
            return
        self.hass.async_create_task(
            self.async_generate(PERIOD_7_DAYS, now.date(), trigger="weekly")
        )

    @callback
    def _outage_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        # Run once the grid is back (off-grid sensor on -> off), after EG4's cloud catches up
        if not (old and new and old.state == STATE_ON and new.state == STATE_OFF):
            return
        if self._outage_timer:
            self._outage_timer()
        delay = int(self.entry.options.get(OPT_OUTAGE_DELAY, DEFAULT_OUTAGE_DELAY)) * 60

        @callback
        def _run(_now: datetime) -> None:
            self._outage_timer = None
            self.hass.async_create_task(
                self.async_generate(PERIOD_TODAY, dt_util.now().date(), trigger="outage")
            )

        self._outage_timer = async_call_later(self.hass, delay, _run)

    def report_range(self, period: str, end: date) -> tuple[date, date]:
        if period == PERIOD_7_DAYS:
            return end - timedelta(days=6), end
        return end, end

    def _settings(self) -> dict[str, Any]:
        data, opts = self.entry.data, self.entry.options
        names = [n.strip() for n in data.get(CONF_ARRAY_NAMES, "").split(",") if n.strip()]
        limits = [float(v) for v in data.get(CONF_MPPT_LIMITS_A, "").split(",") if v.strip()]
        return {
            "system_type": data.get(CONF_SYSTEM_TYPE),
            "parallel_count": int(data.get(CONF_PARALLEL_COUNT, 1)),
            "gridboss": data.get(CONF_GRIDBOSS, False),
            "battery_kwh": opts.get(CONF_BATTERY_KWH) or data.get(CONF_BATTERY_KWH),
            "pack_count": int(opts.get(CONF_PACK_COUNT) or data.get(CONF_PACK_COUNT, 0)),
            "pack_discharge_a": opts.get(CONF_PACK_DISCHARGE_A) or data.get(CONF_PACK_DISCHARGE_A),
            "cell_v_max": opts.get(CONF_CELL_V_MAX) or data.get(CONF_CELL_V_MAX),
            "array_names": names,
            "mppt_limits_a": limits,
            "pv_max_v": data.get(CONF_PV_MAX_V) or None,
            "output_ceiling_kw": data.get(CONF_OUTPUT_CEILING_KW) or None,
            "import_rate": data.get(CONF_IMPORT_RATE),
            "export_credit": data.get(CONF_EXPORT_CREDIT),
            "service_charge": data.get(CONF_SERVICE_CHARGE),
            "utility_name": data.get(CONF_UTILITY_NAME) or "your utility",
            "nominal_voltage": data.get(CONF_NOMINAL_VOLTAGE),
            "hv_watch": data.get(CONF_HV_WATCH),
            "hv_act": data.get(CONF_HV_ACT),
            "known_issues": opts.get(OPT_KNOWN_ISSUES, ""),
            # From the EG4 Web Monitor integration when installed; otherwise the analyzer infers it
            "soc_floor": ha_eg4.soc_floor(self.hass, data[CONF_INVERTERS][0]),
            "temp_imbalance": opts.get(OPT_TEMP_IMBALANCE),
            "temp_unit": opts.get(OPT_TEMP_UNIT)
            or ("f" if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else "c"),
            **{
                f"temp_{cls}_{level}": opts.get(f"temp_{cls}_{level}")
                for cls in TEMP_THRESHOLDS
                for level in ("watch", "act")
            },
        }

    async def async_generate(
        self, period: str | None = None, end_date: date | None = None, trigger: str = "manual"
    ) -> None:
        period = period or self.period
        end_date = end_date or self.end_date
        start, end = self.report_range(period, end_date)
        async with self._lock:
            self.running = True
            self._notify_listeners()
            previous = self.report
            had_error = self.error is not None
            try:
                exports: dict[str, list[bytes]] = {}
                for serial in self.entry.data[CONF_INVERTERS]:
                    # One workbook per inverter, one sheet per day
                    exports[serial] = [await self.client.async_download_export(serial, start, end)]
                settings = self._settings()
                report = await self.hass.async_add_executor_job(
                    analyzer.build_report, exports, settings, start, end
                )
                rendered = await self.hass.async_add_executor_job(
                    charts.render_all, report.pop("_chart_series", report.get("series")), settings
                )
            except Exception as err:  # noqa: BLE001 - any failure becomes the red error state
                if isinstance(err, (Eg4Error, analyzer.AnalyzerError)):
                    _LOGGER.warning("EG4 report for %s..%s failed: %s", start, end, err)
                else:
                    _LOGGER.exception("Unexpected error in EG4 report for %s..%s", start, end)
                self.error = str(err) or type(err).__name__
                if isinstance(err, Eg4AuthError):
                    self.entry.async_start_reauth(self.hass)
                self.running = False
                self._notify_listeners()
                # One push when a run starts failing, not on every retry
                if not had_error:
                    await self._async_push("EG4 Solar Report failed", str(err))
                return

            report["period"] = period
            report["trigger"] = trigger
            self.report = report
            self.charts = rendered
            self.charts_updated = dt_util.utcnow()
            self.error = None
            self.last_generated = dt_util.now()
            self.running = False
            self._notify_listeners()

        old_ids = {f["id"] for f in (previous or {}).get("findings", [])}
        new_findings = [f for f in report["findings"] if f["id"] not in old_ids]
        self.hass.bus.async_fire(
            EVENT_REPORT_GENERATED,
            {
                "entry_id": self.entry.entry_id,
                "trigger": trigger,
                "period": period,
                "range": report["range"],
                "verdict": report["verdict"],
                "counts": report["counts"],
                "new_findings": new_findings,
            },
        )
        severities = self.entry.options.get(OPT_NOTIFY_SEVERITIES, [SEVERITY_ACT])
        pushed = [f for f in new_findings if f["severity"] in severities]
        if pushed:
            lines = [f"{f['severity'].upper()}: {f['title']}" for f in pushed]
            await self._async_push(
                f"EG4 Solar Report: {report['verdict']}", "\n".join(lines)
            )

    async def _async_push(self, title: str, message: str) -> None:
        target = (self.entry.options.get(OPT_NOTIFY_SERVICE) or "").strip()
        if not target:
            return
        service = target.split(".", 1)[1] if target.startswith("notify.") else target
        try:
            await self.hass.services.async_call(
                "notify", service, {"title": title, "message": message}, blocking=False
            )
        except Exception as err:  # noqa: BLE001 - a bad notify target must not break the report
            _LOGGER.warning("Could not send EG4 report notification via %s: %s", target, err)

    @property
    def state(self) -> str | None:
        if self.error:
            return VERDICT_ERROR
        return self.report["verdict"] if self.report else None
