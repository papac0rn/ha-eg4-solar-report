"""Report analyzer: turns Monitor Center exports into checks, findings and chart data.

Pure Python with no Home Assistant imports, so the rules can be unit tested on their own.
Rebuilt for SPEC-022 from real Monitor Center exports and the prototype's published reports (the
original eg4_report.py was lost). RULE_CATALOG fixes the 21 check ids, groups and names.

Report shape (the sensor attributes and the dashboard read these keys):
- verdict (healthy / watch / act), summary (one-sentence answer), detail (a short paragraph), chips
- range {start, end}, samples, interval_min, through (last sample time)
- counts {ok, info, watch, act} over the 21 checks
- checks: every check as {id, group, check, result, status}
- findings: the checks that aren't OK, then notes, as {id, group, severity, title, detail, action, facts}
- stats: the stat grid; daily: the day-by-day table; totals: the table's total row
- actions: the numbered "What to do" list
- series: downsampled chart data (the full-resolution copy goes to the charts only)
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Sequence

from . import codes
from .const import ANSI_SERVICE_LIMIT_V, DEFAULT_HV_ACT, DEFAULT_HV_WATCH, TEMP_THRESHOLDS

SEVERITY_ORDER = {"ok": 0, "info": 1, "watch": 2, "act": 3}

# id, group, check name: the "All checks" table, in report order
RULE_CATALOG: list[tuple[str, str, str]] = [
    ("grid_outages", "Grid", "Outages and blips"),
    ("grid_transient", "Grid", "Transient-failure signature (W016-W018)"),
    ("grid_high_voltage", "Grid", "High grid voltage"),
    ("grid_low_voltage", "Grid", "Low grid voltage"),
    ("grid_frequency", "Grid", "Grid frequency"),
    ("battery_pack_dropout", "Battery", "Pack-dropout signature (W004 + W027)"),
    ("battery_packs_online", "Battery", "All packs online"),
    ("battery_cell_balance", "Battery", "Cell balance"),
    ("battery_cell_voltage", "Battery", "Cell voltage limits"),
    ("battery_cell_temperature", "Battery", "Cell temperature"),
    ("battery_soh", "Battery", "State of health"),
    ("battery_grid_carrying_load", "Battery", "Grid carrying load while the battery sits out"),
    ("inverter_faults", "Inverter", "Fault codes"),
    ("inverter_warnings", "Inverter", "Warning codes"),
    ("inverter_heatsink", "Inverter", "Heatsink temperature"),
    ("inverter_output_ceiling", "Inverter", "Output ceiling"),
    ("inverter_mppt_current", "Inverter", "MPPT current"),
    ("inverter_pv_voltage", "Inverter", "PV string voltage"),
    ("arrays_balance", "Arrays", "Array balance"),
    ("data_gaps", "Data", "Logger gaps"),
    ("data_counter_crosscheck", "Data", "Energy counter cross-check"),
]
_CATALOG_INDEX = {rid: (group, name) for rid, group, name in RULE_CATALOG}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TIME_FORMATS = ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M")
MAX_ATTR_POINTS = 400

# Warning bits (W###) that make up the known failure signatures
TRANSIENT_BITS = (16, 17, 18)
PACK_DROPOUT_BITS = (4, 27)


class AnalyzerError(Exception):
    """The exports could not be analyzed."""


@dataclass
class Check:
    """One rule's result. Every rule returns exactly one Check."""

    id: str
    severity: str
    result: str
    title: str = ""
    detail: str = ""
    action: str = ""
    facts: list[tuple[str, str]] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def table_row(self) -> dict[str, Any]:
        group, name = _CATALOG_INDEX.get(self.id, ("Other", self.id))
        return {"id": self.id, "group": group, "check": name, "result": self.result, "status": self.severity}

    def finding(self) -> dict[str, Any]:
        group, _name = _CATALOG_INDEX.get(self.id, ("Note", self.id))
        data = asdict(self)
        data["group"] = group
        data["facts"] = [list(f) for f in self.facts]
        data.pop("actions")
        return data


# Parsing


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("%").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _code(v: Any) -> int:
    s = str(v).strip()
    if not s:
        return 0
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(float(s))
    except ValueError:
        return 0


def _parse_time(v: Any, datemode: int) -> datetime | None:
    if isinstance(v, float):
        import xlrd

        try:
            return xlrd.xldate_as_datetime(v, datemode)
        except Exception:  # noqa: BLE001
            return None
    s = str(v).strip()
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_export(content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse one .xls export (one sheet per day) into its header and rows; each row gets a parsed `_t`.

    Uses pylxpweb's parser, the same one the EG4 Web Monitor integration ships with. Cells come back as text.
    """
    # Imported here so the module loads before HA installs requirements
    from pylxpweb.endpoints.export import parse_export as lxp_parse_export
    from pylxpweb.exceptions import LuxpowerAPIError

    try:
        sheets = lxp_parse_export(content)
    except LuxpowerAPIError as err:
        raise AnalyzerError(str(err)) from err
    header: list[str] = []
    rows: list[dict[str, Any]] = []
    for sheet in sheets:
        if not sheet.rows or "Time" not in sheet.rows[0]:
            continue
        header = header or list(sheet.rows[0])
        for row in sheet.rows:
            t = _parse_time(row["Time"], 0)
            if t is None:
                continue
            parsed: dict[str, Any] = dict(row)
            parsed["_t"] = t
            rows.append(parsed)
    return header, rows

class Log:
    """Time-ordered samples from one inverter, with numeric column access."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        seen: set[datetime] = set()
        ordered = []
        for row in sorted(rows, key=lambda r: r["_t"]):
            if row["_t"] not in seen:
                seen.add(row["_t"])
                ordered.append(row)
        self.rows = ordered
        self.t: list[datetime] = [r["_t"] for r in ordered]
        self._cache: dict[str, list[float | None]] = {}
        diffs = [(b - a).total_seconds() / 60 for a, b in zip(self.t, self.t[1:])]
        self.interval = statistics.median(diffs) if diffs else 4.0
        self.diffs = diffs

    def __len__(self) -> int:
        return len(self.rows)

    def has(self, col: str) -> bool:
        return bool(self.rows) and col in self.rows[0]

    def f(self, col: str) -> list[float | None]:
        if col not in self._cache:
            self._cache[col] = [_num(r.get(col)) for r in self.rows]
        return self._cache[col]

    def kw(self, col: str) -> list[float | None]:
        return [None if v is None else v / 1000 for v in self.f(col)]

    def codes(self, col: str) -> list[int]:
        return [_code(r.get(col, "")) for r in self.rows]

    def text(self, col: str) -> list[str]:
        return [str(r.get(col, "")) for r in self.rows]


# Small helpers


def _vals(xs: Sequence[float | None]) -> list[float]:
    return [x for x in xs if x is not None]


def _max_at(t: Sequence[datetime], xs: Sequence[float | None], idx: Sequence[int] | None = None):
    best = None
    for i in idx if idx is not None else range(len(xs)):
        v = xs[i]
        if v is not None and (best is None or v > xs[best]):
            best = i
    return (xs[best], t[best], best) if best is not None else (None, None, None)


def _min_at(t: Sequence[datetime], xs: Sequence[float | None], idx: Sequence[int] | None = None):
    best = None
    for i in idx if idx is not None else range(len(xs)):
        v = xs[i]
        if v is not None and (best is None or v < xs[best]):
            best = i
    return (xs[best], t[best], best) if best is not None else (None, None, None)


def _day(d: date | datetime) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}"


def _hm(t: datetime) -> str:
    return f"{t:%H:%M}"


def _hours(minutes: float) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h} h {m:02d} m" if h else f"{m} min"


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def _fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float] | None:
    """Least-squares line y = a + b x; returns (a, b)."""
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def _runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    """Index ranges [start, end] where flags is True."""
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(flags) - 1))
    return out


def _fahrenheit(c: "Ctx") -> bool:
    return str(c.settings.get("temp_unit") or "C").upper().startswith("F")


def _t(c: "Ctx", v: float, unit: bool = True) -> str:
    """A temperature (stored in °C) in the report's unit."""
    if _fahrenheit(c):
        s = f"{v * 9 / 5 + 32:.0f}"
        return f"{s} °F" if unit else s
    return f"{v:g} °C" if unit else f"{v:g}"


def _dt(c: "Ctx", delta: float, signed: bool = False) -> str:
    """A temperature difference in the report's unit."""
    d = delta * 9 / 5 if _fahrenheit(c) else delta
    return f"{d:+.1f} {'°F' if _fahrenheit(c) else '°C'}" if signed else f"{d:.1f} {'°F' if _fahrenheit(c) else '°C'}"


def _bits(code: int) -> list[int]:
    return [b for b in range(32) if code >> b & 1]


# Derived context shared by the rules


@dataclass
class Ctx:
    log: Log
    settings: dict[str, Any]
    start: date
    end: date
    days: list[date] = field(default_factory=list)
    day_idx: dict[date, list[int]] = field(default_factory=dict)
    partial: dict[date, bool] = field(default_factory=dict)
    array_names: list[str] = field(default_factory=list)
    daily: list[dict[str, Any]] = field(default_factory=list)
    grid_ok: list[bool] = field(default_factory=list)
    pv_kw: list[float | None] = field(default_factory=list)
    export_kw: list[float | None] = field(default_factory=list)
    import_kw: list[float | None] = field(default_factory=list)
    nominal_v: float = 240.0
    nominal_f: float = 60.0
    hv_watch: float = float(DEFAULT_HV_WATCH)
    hv_act: float = float(DEFAULT_HV_ACT)
    battery_kwh: float | None = None
    soc_floor: float | None = None
    notes: list[Check] = field(default_factory=list)
    chart_notes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _build_ctx(log: Log, settings: dict[str, Any], start: date, end: date) -> Ctx:
    ctx = Ctx(log=log, settings=settings, start=start, end=end)
    t = log.t
    for i, ts in enumerate(t):
        ctx.day_idx.setdefault(ts.date(), []).append(i)
    ctx.days = sorted(ctx.day_idx)
    for d, idx in ctx.day_idx.items():
        first, last = t[idx[0]], t[idx[-1]]
        ctx.partial[d] = (last - first).total_seconds() < 20 * 3600

    ctx.nominal_v = float(settings.get("nominal_voltage") or 240)
    ctx.hv_watch = float(settings.get("hv_watch") or DEFAULT_HV_WATCH)
    ctx.hv_act = float(settings.get("hv_act") or DEFAULT_HV_ACT)
    fac = _vals(log.f("fac"))
    ctx.nominal_f = 50.0 if fac and statistics.median(fac) < 55 else 60.0

    vacr, freq = log.f("vacr"), log.f("fac")
    status = [s.lower() for s in log.text("Status")]
    ctx.grid_ok = [
        v is not None and v > 0.75 * ctx.nominal_v and (f is None or f > 0.9 * ctx.nominal_f)
        and not ("off" in s and "grid" in s)
        for v, f, s in zip(vacr, freq, status)
    ]
    ppv = [log.f(f"ppv{k}") for k in (1, 2, 3)]
    ctx.pv_kw = [
        None if all(p[i] is None for p in ppv) else sum((p[i] or 0) for p in ppv) / 1000
        for i in range(len(log))
    ]
    ctx.export_kw = log.kw("pToGrid")
    ctx.import_kw = log.kw("pToUser")

    # Arrays: one per MPPT input that produced anything, named from settings
    active = [k for k in (1, 2, 3) if any((v or 0) > 0 for v in log.f(f"ePv{k}Day"))] or [1]
    names = list(settings.get("array_names") or [])
    # The named arrays always show, even before sunrise when none has produced yet
    count = min(max(max(active), len(names)), 3)
    ctx.array_names = [names[k] if k < len(names) else f"Array {k + 1}" for k in range(count)]

    # Day-by-day table (day counters reset at midnight, so each day's value is its maximum)
    ceiling = settings.get("output_ceiling_kw")
    pinv = log.kw("pinv")
    soc = log.f("SOC(%)")
    for d in ctx.days:
        idx = ctx.day_idx[d]

        def day_max(col: str) -> float:
            return max(_vals(log.f(col)[i] for i in idx) or [0.0])

        arrays = [day_max(f"ePv{k + 1}Day") for k in range(count)]
        export, imp, inv = day_max("eToGridDay"), day_max("eToUserDay"), day_max("eInvDay")
        socs = _vals(soc[i] for i in idx)
        volts = _vals(vacr[i] for i in idx)
        over = sum(1 for i in idx if (vacr[i] or 0) > ANSI_SERVICE_LIMIT_V)
        clip = sum(1 for i in idx if ceiling and (pinv[i] or 0) >= ceiling - 0.5)
        ctx.daily.append({
            "day": _day(d),
            "date": d.isoformat(),
            "partial": ctx.partial[d],
            "through": _hm(t[idx[-1]]) if ctx.partial[d] else None,
            "pv": round(sum(arrays), 1),
            "arrays": [round(a, 1) for a in arrays],
            "peak_kw": round(max(_vals(ctx.pv_kw[i] for i in idx) or [0]), 1),
            "load": round(inv + imp - export, 1),
            "export": round(export, 1),
            "import": round(imp, 1),
            "charge": round(day_max("eChgDay"), 1),
            "discharge": round(day_max("eDisChgDay"), 1),
            "soc_min": min(socs) if socs else None,
            "soc_max": max(socs) if socs else None,
            "v_max": max(volts) if volts else None,
            "h_over": round(over * log.interval / 60, 1),
            "clip_min": int(round(clip * log.interval)),
        })

    ctx.battery_kwh = float(settings["battery_kwh"]) if settings.get("battery_kwh") else _infer_capacity(log)
    ctx.soc_floor = float(settings["soc_floor"]) if settings.get("soc_floor") else _infer_soc_floor(log)
    return ctx


def _infer_capacity(log: Log) -> float | None:
    """kWh per % of SOC while purely charging, scaled to 100 %."""
    soc, chg, dis = log.f("SOC(%)"), log.f("eChgDay"), log.f("pDisCharge")
    d_e = d_s = 0.0
    for i in range(1, len(log)):
        if log.t[i].date() != log.t[i - 1].date():
            continue
        if None in (soc[i], soc[i - 1], chg[i], chg[i - 1]) or (dis[i] or 0) > 0:
            continue
        ds, de = soc[i] - soc[i - 1], chg[i] - chg[i - 1]
        if ds > 0 and de > 0:
            d_s += ds
            d_e += de
    return round(d_e / d_s * 100, 1) if d_s >= 15 else None


def _infer_soc_floor(log: Log) -> float | None:
    """The discharge floor shows as a minimum SOC the bank sits at for half an hour or more."""
    soc = log.f("SOC(%)")
    vals = _vals(soc)
    if not vals:
        return None
    low = min(vals)
    held = sum(1 for v in vals if v is not None and v <= low)
    return low if low <= 30 and held * log.interval >= 30 else None


# The 21 rules


def rule_grid_outages(c: Ctx) -> Check:
    events = _runs([not ok for ok in c.grid_ok])
    n = len(c.log)
    if not events:
        return Check("grid_outages", "ok", f"Grid present in all {n:,} samples")
    blips = [e for e in events if e[0] == e[1]]
    longest = max(((c.log.t[b] - c.log.t[a]).total_seconds() / 60 + c.log.interval) for a, b in events)
    facts = [(f"{_day(c.log.t[a])} {_hm(c.log.t[a])}", _hours((c.log.t[b] - c.log.t[a]).total_seconds() / 60 + c.log.interval))
             for a, b in events[:6]]
    return Check(
        "grid_outages", "watch",
        f"{len(events)} grid loss(es), {len(blips)} single-sample blip(s)",
        title=f"{len(events)} grid outage(s) or blip(s)",
        detail=f"The grid was missing in {len(events)} stretch(es); the longest lasted about {_hours(longest)}. "
               "Short single-sample losses are blips, like recloser operations on the line.",
        action="If blips repeat, log the times and ask your utility about recloser operations on your line.",
        facts=facts,
    )


def _bit_samples(c: Ctx, bits: Sequence[int], need_all: bool) -> list[int]:
    codes = c.log.codes("warningCode")
    test = all if need_all else any
    return [i for i, code in enumerate(codes) if test(code >> b & 1 for b in bits)]


def rule_grid_transient(c: Ctx) -> Check:
    hits = _bit_samples(c, TRANSIENT_BITS, need_all=False)
    if not hits:
        return Check("grid_transient", "ok", "No W016, W017 or W018 warnings")
    first = c.log.t[hits[0]]
    return Check(
        "grid_transient", "act", f"{len(hits)} sample(s) with W016-W018",
        title="Transient-failure warnings (W016-W018)",
        detail=f"Warnings W016-W018 appeared in {len(hits)} sample(s), first at {_day(first)} {_hm(first)}. "
               "This is the signature seen before an earlier transient failure.",
        action="Check the inverter's event log and contact EG4 support with the times.",
    )


def rule_grid_high_voltage(c: Ctx) -> Check:
    log, vacr = c.log, c.log.f("vacr")
    peak, peak_t, peak_i = _max_at(log.t, vacr)
    if peak is None:
        return Check("grid_high_voltage", "ok", "No grid voltage logged")
    days_over = [d for d in c.daily if d["h_over"] > 0]
    hours = sum(d["h_over"] for d in c.daily)
    exp = c.export_kw
    pairs = [(e, v) for e, v, ok in zip(exp, vacr, c.grid_ok) if ok and e is not None and v is not None]
    r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
    fit = _fit([p[0] for p in pairs], [p[1] for p in pairs])
    slopes = []
    for d in c.days:
        idx = c.day_idx[d]
        dp = [(exp[i], vacr[i]) for i in idx if exp[i] is not None and vacr[i] is not None and c.grid_ok[i]]
        if dp and max(e for e, _v in dp) >= 3:
            f = _fit([e for e, _v in dp], [v for _e, v in dp])
            if f:
                slopes.append(f[1])
    export_at_peak = exp[peak_i] if peak_i is not None else None
    legs = [log.f(col)[peak_i] for col in ("epsVoltL1N", "epsVoltL2N")] if peak_i is not None else []
    facts = [("Peak", f"{peak:.1f} V at {_day(peak_t)} {_hm(peak_t)}")]
    if export_at_peak is not None:
        facts.append(("Export at peak", f"{export_at_peak:.1f} kW"))
    ex_pk, ex_t, _ei = _max_at(log.t, exp)
    if ex_pk:
        facts.append(("Peak export", f"{ex_pk:.1f} kW at {_hm(ex_t)}"))
    if all(v is not None for v in legs) and legs:
        facts.append(("Per leg at peak", " / ".join(f"{v:.1f}" for v in legs) + " V"))
    facts.append((f"Time > {ANSI_SERVICE_LIMIT_V} V (ANSI service limit)", f"{hours:.1f} h on {len(days_over)} day(s)"))
    if r is not None:
        facts.append(("V vs export", f"r = {r:.2f}"))
    if fit:
        facts.append(("Fit", f"{fit[0]:.1f} V + {fit[1]:.2f} V per kW exported"))

    # An inverter grid over-voltage code: W017 while the line is on the high side of nominal
    ov_hits = [i for i in _bit_samples(c, [17], need_all=False)
               if vacr[i] is not None and vacr[i] >= 1.05 * c.nominal_v]
    margin = c.hv_act - peak
    result = (f"Peak {peak:.1f} V · {margin:.1f} V below the {c.hv_act:g} V trip" if margin > 0
              else f"Peak {peak:.1f} V · at or above the {c.hv_act:g} V trip")
    context = (" Volt-watt curtailment, if enabled in the inverter, can trim export at high voltage."
               if peak > ANSI_SERVICE_LIMIT_V else "")
    if peak >= c.hv_act or ov_hits:
        severity = "act"
    elif peak >= c.hv_watch:
        severity = "watch"
    else:
        detail = (f"The highest line voltage was {peak:.1f} V on {_day(peak_t)} at {_hm(peak_t)}, {margin:.1f} V below "
                  f"the {c.hv_act:g} V point where the inverter disconnects." + context)
        return Check("grid_high_voltage", "ok", result, detail=detail, facts=facts)

    slope_txt = ""
    if slopes and fit:
        lo, hi = min(slopes), max(slopes)
        rng = f"{lo:.2f}" if round(lo, 2) == round(hi, 2) else f"{lo:.2f}–{hi:.2f}"
        slope_txt = f" Voltage rises {rng} V per kW exported from a no-export baseline of about {fit[0]:.0f} V."
    if ov_hits:
        first = log.t[ov_hits[0]]
        title = "Grid over-voltage code (W017)"
        detail = (f"The inverter logged W017 (grid voltage out of range) on the high side in {len(ov_hits)} sample(s), "
                  f"first at {_day(first)} {_hm(first)}. The peak was {peak:.1f} V.")
    elif severity == "act":
        title = f"Grid voltage reached the {c.hv_act:g} V trip"
        detail = (f"Line voltage reached {peak:.1f} V on {_day(peak_t)} at {_hm(peak_t)}"
                  + (f" with {export_at_peak:.1f} kW of export" if export_at_peak else "")
                  + f". At {c.hv_act:g} V the inverter disconnects from the grid after about 2 seconds.")
    else:
        title = f"Grid voltage within {margin:.1f} V of the inverter trip"
        detail = (f"Line voltage peaked at {peak:.1f} V on {_day(peak_t)} at {_hm(peak_t)}"
                  + (f" with {export_at_peak:.1f} kW of export" if export_at_peak else "")
                  + f", {margin:.1f} V below the {c.hv_act:g} V trip.")
    detail += slope_txt + context
    actions = [
        f"Check the inverter's grid over-voltage setting: confirm the trip is at {c.hv_act:g} V and how long it waits "
        "before disconnecting.",
        "Measure at the meter during peak export. Comparing it with the inverter reading shows how much of the rise is "
        "in your own wiring.",
    ]
    return Check(
        "grid_high_voltage", severity, result,
        title=title, detail=detail, action=actions[0], facts=facts, actions=actions,
    )


def rule_grid_low_voltage(c: Ctx) -> Check:
    vals = [v for v, ok in zip(c.log.f("vacr"), c.grid_ok) if ok and v is not None]
    if not vals:
        return Check("grid_low_voltage", "ok", "No grid voltage logged")
    low, low_t, _i = _min_at(c.log.t, [v if ok else None for v, ok in zip(c.log.f("vacr"), c.grid_ok)])
    if low >= 0.92 * c.nominal_v:
        return Check("grid_low_voltage", "ok", f"Low of {low:.1f} V")
    severity = "act" if low < 0.88 * c.nominal_v else "watch"
    return Check(
        "grid_low_voltage", severity, f"Low of {low:.1f} V",
        title=f"Grid voltage fell to {low:.1f} V",
        detail=f"The lowest grid reading was {low:.1f} V at {_day(low_t)} {_hm(low_t)}, "
               f"{(1 - low / c.nominal_v) * 100:.0f} % under the {c.nominal_v:g} V nominal.",
        action="If low readings repeat, note the times and ask your utility about the line.",
    )


def rule_grid_frequency(c: Ctx) -> Check:
    vals = [f for f, ok in zip(c.log.f("fac"), c.grid_ok) if ok and f is not None]
    if not vals:
        return Check("grid_frequency", "ok", "No frequency logged")
    lo, hi = min(vals), max(vals)
    dev = max(c.nominal_f - lo, hi - c.nominal_f)
    result = f"{lo:.2f}-{hi:.2f} Hz"
    if dev <= 0.5:
        return Check("grid_frequency", "ok", result)
    severity = "act" if dev > 0.7 else "watch"
    return Check(
        "grid_frequency", severity, result, title=f"Grid frequency strayed to {lo if c.nominal_f - lo > hi - c.nominal_f else hi:.2f} Hz",
        detail=f"Grid frequency ranged {result} against {c.nominal_f:g} Hz nominal.",
        action="Frequency excursions are a utility-side event. Note the time if the inverter disconnected.",
    )


def rule_battery_pack_dropout(c: Ctx) -> Check:
    hits = _bit_samples(c, PACK_DROPOUT_BITS, need_all=True)
    if not hits:
        return Check("battery_pack_dropout", "ok", "No W004 + W027 warnings")
    first = c.log.t[hits[0]]
    return Check(
        "battery_pack_dropout", "act", f"W004 + W027 in {len(hits)} sample(s)",
        title="Battery pack-dropout warnings (W004 + W027)",
        detail=f"Warnings W004 and W027 appeared together in {len(hits)} sample(s), first at {_day(first)} {_hm(first)}. "
               "This pair is the signature of a pack dropping off the bus.",
        action="Check each pack's status lights and the battery communication cable, then the per-pack view in the app.",
    )


def _per_pack_limit(c: Ctx, packs: int) -> float:
    """BMS discharge limit per pack: from setup, or learned as the highest limit seen divided by the pack count."""
    per = float(c.settings.get("pack_discharge_a") or 0)
    if not per and packs:
        seen = _vals(c.log.f("maxDischgCurr"))
        per = max(seen) / packs if seen else 0.0
    return per


def rule_battery_packs_online(c: Ctx) -> Check:
    packs = int(c.settings.get("pack_count") or 0)
    per = _per_pack_limit(c, packs)
    limit = c.log.f("maxDischgCurr")
    vals = _vals(limit)
    if not vals:
        return Check("battery_packs_online", "ok", "No discharge limit logged")
    expected = packs * per if packs and per else max(vals)
    low = [i for i, v in enumerate(limit) if v is not None and v < expected * 0.97]
    if not low:
        return Check("battery_packs_online", "ok",
                     f"Discharge limit {expected:g} A all {'week' if len(c.days) > 1 else 'day'}"
                     + (f": all {packs} packs reporting" if packs else ""))
    first, last, worst = c.log.t[low[0]], c.log.t[low[-1]], min(limit[i] for i in low)
    online = int(round(worst / per)) if per else None
    recovered = low[-1] + 1 < len(limit)
    packs_txt = f"{online} of {packs} packs" if online is not None and packs else f"{worst:g} A"
    when = ("from the start of the range" if low[0] == 0 else f"from {_day(first)} {_hm(first)}")
    detail = (f"The BMS discharge limit should read {expected:g} A with all {packs or ''} packs online. It read "
              f"{worst:g} A ({packs_txt}) {when}"
              + (f" until {_day(last)} {_hm(last)}, when the missing pack rejoined" if recovered else ", and it had not recovered")
              + f": {_hours(len(low) * c.log.interval)} in all.")
    soc = c.log.f("SOC(%)")
    if recovered and soc[low[-1]] is not None and soc[low[-1] + 1] is not None and soc[low[-1] + 1] < soc[low[-1]] - 2:
        detail += (f" SOC stepped from {soc[low[-1]]:.0f}% to {soc[low[-1] + 1]:.0f}% at that moment, as the BMS "
                   "re-counted capacity with the pack back.")
    return Check(
        "battery_packs_online", "act",
        f"Discharge limit {worst:g} A ({packs_txt}) for {_hours(len(low) * c.log.interval)}"
        + (", recovered" if recovered else ""),
        title=f"Battery pack offline: {packs_txt}" if online is not None and packs else f"Discharge limit dropped to {worst:g} A",
        detail=detail,
        action="Check which pack dropped out in the per-pack view, then its breaker, communication cable and "
               "terminal torque. A pack that drops and rejoins is the start of the August failure pattern.",
        facts=[("Limit", f"{worst:g} A of {expected:g} A"), ("First", f"{_day(first)} {_hm(first)}"),
               ("Last", f"{_day(last)} {_hm(last)}")],
    )

def rule_battery_cell_balance(c: Ctx) -> Check:
    cmax, cmin = c.log.f("MaxCellVoltage"), c.log.f("MinCellVoltage")
    n = len(c.log)
    blips = []
    for i in range(1, n - 1):
        a, b, d = cmin[i - 1], cmin[i], cmin[i + 1]
        if None not in (a, b, d) and b < a - 0.05 and b < d - 0.05:
            blips.append(i)
    spread = [(hi - lo) * 1000 for i, (hi, lo) in enumerate(zip(cmax, cmin))
              if hi is not None and lo is not None and i not in blips]
    if not spread:
        return Check("battery_cell_balance", "ok", "No cell voltages logged")
    typical, peak = statistics.median(spread), max(spread)
    facts = [("Typical spread", f"{typical:.0f} mV"), ("Peak spread", f"{peak:.0f} mV")]
    for i in blips[:4]:
        before = (cmin[i - 1] + cmin[i + 1]) / 2
        facts.append((f"Dip {_day(c.log.t[i])} {_hm(c.log.t[i])}",
                      f"min cell {cmin[i]:.3f} V, {(before - cmin[i]) * 1000:.0f} mV below the samples either side"))
    if blips:
        i = blips[0]
        current = _num(c.log.rows[i].get("BatCurrent"))
        detail = (f"On {_day(c.log.t[i])} at {_hm(c.log.t[i])} the lowest-cell reading dropped from {cmin[i - 1]:.3f} V "
                  f"to {cmin[i]:.3f} V for a single sample, then came back to {cmin[i + 1]:.3f} V"
                  + (f" with the bank at {abs(current):.0f} A" if current is not None else "") + ". "
                  "A real cell can't move that far and back in one sample, so this is a bad reading from one pack's BMS. "
                  f"Otherwise the spread stayed at {peak:.0f} mV or less.")
        return Check(
            "battery_cell_balance", "watch", f"{len(blips)} single-sample low-cell reading(s); balance otherwise normal",
            title="One cell-voltage blip" if len(blips) == 1 else f"{len(blips)} cell-voltage blips",
            detail=detail, facts=facts,
            action="Watch for another cell-voltage blip. One bad reading is nothing; a repeat on the same pack is worth "
                   "catching early, so check the per-pack cell view if it shows up again.",
        )
    if peak > 200:
        severity = "act"
    elif peak > 100:
        severity = "watch"
    else:
        return Check("battery_cell_balance", "ok", f"Spread {typical:.0f} mV typical, {peak:.0f} mV peak", facts=facts)
    return Check(
        "battery_cell_balance", severity, f"Spread up to {peak:.0f} mV",
        title=f"Cell spread reached {peak:.0f} mV", facts=facts,
        detail=f"The gap between the highest and lowest cell reached {peak:.0f} mV (typical {typical:.0f} mV).",
        action="Let the bank sit at full charge so the BMS can balance; check the per-pack view if it persists.",
    )


def rule_battery_cell_voltage(c: Ctx) -> Check:
    limit = float(c.settings.get("cell_v_max") or 3.65)
    hi = _vals(c.log.f("MaxCellVoltage"))
    lo = _vals(c.log.f("MinCellVoltage"))
    if not hi:
        return Check("battery_cell_voltage", "ok", "No cell voltages logged")
    top, bottom = max(hi), min(lo) if lo else None
    result = f"Cells {bottom:.3f}-{top:.3f} V, {(limit - top) * 1000:.0f} mV under the {limit:g} V limit"
    if top >= limit:
        return Check("battery_cell_voltage", "act", result, title=f"A cell reached {top:.3f} V",
                     detail=f"The highest cell reached {top:.3f} V, at or over the {limit:g} V limit.",
                     action="Check the charge voltage settings and the pack that reports the high cell.")
    if bottom is not None and bottom < 2.9:
        return Check("battery_cell_voltage", "act" if bottom < 2.8 else "watch", result,
                     title=f"A cell fell to {bottom:.3f} V",
                     detail=f"The lowest cell fell to {bottom:.3f} V, near the bottom of its safe range.",
                     action="Raise the discharge cut-off and check the pack that reports the low cell.")
    if limit - top < 0.02:
        return Check("battery_cell_voltage", "watch", result, title=f"Cells came within {(limit - top) * 1000:.0f} mV of the limit",
                     detail=f"The highest cell reached {top:.3f} V against the {limit:g} V limit.",
                     action="Check the charge voltage setting; the BMS is close to cutting charge.")
    return Check("battery_cell_voltage", "ok", result)


def rule_battery_cell_temperature(c: Ctx) -> Check:
    hi = _vals(c.log.f("MaxCellTemp"))
    lo = _vals(c.log.f("MinCellTemp"))
    if not hi:
        return Check("battery_cell_temperature", "ok", "No cell temperatures logged")
    top, bottom = max(hi), min(lo) if lo else min(hi)
    result = f"Cells {_t(c, bottom, unit=False)}-{_t(c, top)}"
    charging_cold = any((t or 99) < 0 and (p or 0) > 0 for t, p in zip(c.log.f("MinCellTemp"), c.log.f("pCharge")))
    watch, act = _temp_limits(c, "cell")
    if top > act:
        sev = "act"
    elif top > watch or charging_cold:
        sev = "watch"
    else:
        return Check("battery_cell_temperature", "ok", result)
    return Check("battery_cell_temperature", sev, result,
                 title="Battery charged below freezing" if charging_cold and top <= watch else f"Cells reached {_t(c, top)}",
                 detail=f"Cell temperatures ranged {_t(c, bottom, unit=False)}-{_t(c, top)}.",
                 action="Improve airflow around the battery, or check the BMS low-temperature charge limit.")


def rule_battery_soh(c: Ctx) -> Check:
    soh = _vals(c.log.f("SOH"))
    if not soh:
        return Check("battery_soh", "ok", "No SOH logged")
    lo, hi = min(soh), max(soh)
    result = f"SOH {lo:g}%" if lo == hi else f"SOH {lo:g}-{hi:g}%"
    if lo >= 90 and hi - lo <= 2:
        return Check("battery_soh", "ok", result)
    sev = "act" if lo < 80 else "watch"
    return Check("battery_soh", sev, result, title=f"Battery state of health {lo:g}%",
                 detail=f"The BMS reports state of health {result}.",
                 action="Compare with earlier reports; a falling SOH on one pack is a warranty question for EG4.")


def rule_battery_grid_carrying_load(c: Ctx) -> Check:
    log = c.log
    load, dis, soc = log.kw("pLoad"), log.kw("pDisCharge"), log.f("SOC(%)")
    blocks = []
    for a, b in _runs([(v or 0) >= 9 for v in load]):
        minutes = (log.t[b] - log.t[a]).total_seconds() / 60 + log.interval
        if minutes < 10:
            continue
        bought = sum((c.import_kw[i] or 0) for i in range(a, b + 1)) * log.interval / 60
        batt = max((dis[i] or 0) for i in range(a, b + 1))
        socs = _vals(soc[i] for i in range(a, b + 1))
        blocks.append({
            "start": log.t[a], "end": log.t[b], "peak": max(load[i] or 0 for i in range(a, b + 1)),
            "bought": bought, "battery_kw": batt, "soc": min(socs) if socs else None,
        })
    if not blocks:
        return Check("battery_grid_carrying_load", "ok", "No large loads carried by the grid")
    bought = sum(b["bought"] for b in blocks)
    held_out = all(b["battery_kw"] < 0.3 for b in blocks)
    rate = float(c.settings.get("import_rate") or 0)
    facts = [(f"{_day(b['start'])} {_hm(b['start'])}-{_hm(b['end'])}",
              f"load up to {b['peak']:.1f} kW, battery at {b['soc']:.0f}%, {b['bought']:.1f} kWh bought"
              if b["soc"] is not None else f"load up to {b['peak']:.1f} kW, {b['bought']:.1f} kWh bought")
             for b in blocks]
    result = f"{len(blocks)} period(s), {bought:.1f} kWh bought" + (f" (${bought * rate:.2f})" if rate else "")
    summary = (f"{len(blocks)} load block(s) of 9 kW or more, about the draw of an EV charger. "
               + ("Battery discharge stayed at 0 W through all of them, so a solar-and-grid-only charging rule is working. "
                  if held_out else ""))
    if bought <= 1.5 * len(blocks):
        return Check("battery_grid_carrying_load", "ok", result, facts=facts)
    return Check(
        "battery_grid_carrying_load", "info", result,
        title="The grid carried big loads while the battery sat out",
        detail=summary + f"The grid supplied {bought:.1f} kWh during them.",
        action="None, unless you'd rather let the battery help with EV charging on cloudy days"
               + (f"; that would have saved about ${bought * rate:.2f}." if rate else "."),
        facts=facts,
    )


def _context(c: Ctx, a: int, b: int) -> str | None:
    """What else was happening around samples a..b: a grid event, a voltage excursion or a sunrise mode change."""
    lo, hi = max(a - 2, 0), min(b + 2, len(c.log) - 1)
    if any(not c.grid_ok[i] for i in range(lo, hi + 1)):
        return "a grid event"
    volts = [c.log.f("vacr")[i] for i in range(lo, hi + 1)]
    if any(v is not None and (v >= c.hv_act - 2 or v < 0.9 * c.nominal_v) for v in volts):
        return "a grid voltage excursion"
    status = c.log.text("Status")
    pv = c.pv_kw
    for i in range(max(lo, 1), hi + 1):
        if status[i] != status[i - 1] and 4 <= c.log.t[i].hour <= 10 and (pv[i] or 0) > (pv[i - 1] or 0):
            return "the sunrise mode change"
    return None


def code_occurrences(c: Ctx, kind: str) -> list[dict[str, Any]]:
    """Decode every fault or warning bit seen, and judge each one transient or persistent, with the reason."""
    col = "warningCode" if kind == "warning" else "faultCode"
    values = c.log.codes(col)
    out = []
    for bit in sorted({b for v in values if v for b in _bits(v)}):
        runs = _runs([bool(v >> bit & 1) for v in values])
        minutes = [(c.log.t[b] - c.log.t[a]).total_seconds() / 60 + c.log.interval for a, b in runs]
        contexts = [_context(c, a, b) for a, b in runs]
        info = codes.lookup(kind, bit)
        label = codes.label(kind, bit)
        transient = len(runs) <= 2 and max(minutes) <= 10
        persistent = len(runs) >= 3 or max(minutes) > 30
        context = next((x for x in contexts if x), None)
        if info is None:
            verdict = "watch"
            why = f"Unknown code {label} (bit {bit}, 0x{1 << bit:08X}), not in the table."
        elif transient and context:
            verdict = "ok"
            why = f"{label} for {_hours(sum(minutes))} during {context}, cleared on its own."
        elif transient:
            verdict = "info"
            why = f"{label} for {_hours(sum(minutes))}, cleared on its own with no grid event around it."
        elif persistent:
            verdict = info.severity
            why = (f"{label} {len(runs)} times this {'week' if len(c.days) >= 6 else 'period'}" if len(runs) >= 3
                   else f"{label} lasted {_hours(max(minutes))}") + ", so it is not a one-off."
        else:
            verdict = "info" if info.severity == "watch" else "watch"
            why = f"{label} {len(runs)} time(s), up to {_hours(max(minutes))}."
        first, last = c.log.t[runs[0][0]], c.log.t[runs[-1][1]]
        out.append({
            "code": label, "kind": kind, "bit": bit,
            "name": info.name if info else f"Unknown code {label}",
            "meaning": info.meaning if info else "Not in the code table.",
            "causes": info.causes if info else "",
            "action": info.action if info else "Note the time and ask EG4 support what this code means.",
            "source": info.source if info else "unknown",
            "count": len(runs), "minutes": round(sum(minutes)),
            "first": first.isoformat(), "last": last.isoformat(),
            "classification": "transient" if transient else "persistent" if persistent else "recurring",
            "verdict": verdict, "why": why,
        })
    return out


def _code_check(c: Ctx, check_id: str, kind: str) -> Check:
    occ = code_occurrences(c, kind)
    word = "warning" if kind == "warning" else "fault"
    if not occ:
        return Check(check_id, "ok", f"Every {word} code 0x0")
    worst = max(occ, key=lambda o: SEVERITY_ORDER[o["verdict"]])
    result = "; ".join(f"{o['code']} ×{o['count']} {o['classification']}" for o in occ)
    if worst["verdict"] == "ok":
        return Check(check_id, "ok", result, facts=[(o["code"], o["why"]) for o in occ])
    return Check(
        check_id, worst["verdict"], result,
        title=f"{worst['code']} {worst['name']}" if len(occ) == 1 else f"{len(occ)} {word} codes, worst {worst['code']}",
        detail=" ".join(f"{o['code']} {o['name']}: {o['why']} {o['meaning']}" for o in occ),
        action=worst["action"],
        facts=[(o["code"], f"{o['name']} · {o['count']}× · {_hours(o['minutes'])} · {o['verdict']}") for o in occ],
    )


def rule_inverter_faults(c: Ctx) -> Check:
    return _code_check(c, "inverter_faults", "fault")


def rule_inverter_warnings(c: Ctx) -> Check:
    return _code_check(c, "inverter_warnings", "warning")


TEMP_DEFAULTS = TEMP_THRESHOLDS


def _temp_limits(c: Ctx, cls: str) -> tuple[float, float]:
    watch, act = TEMP_DEFAULTS[cls]
    return float(c.settings.get(f"temp_{cls}_watch") or watch), float(c.settings.get(f"temp_{cls}_act") or act)


def radiator_gap(c: Ctx) -> float | None:
    """Heatsink 1's overnight baseline minus heatsinks 2 and 3, with no PV flowing (so not a load effect)."""
    log = c.log
    rads = {k: log.f(f"tradiator{k}") for k in (1, 2, 3) if log.has(f"tradiator{k}")}
    night = [i for i, p in enumerate(c.pv_kw) if p is not None and p < 0.02]
    if 1 not in rads or len(rads) < 2 or len(night) < 10:
        return None
    r1 = statistics.fmean(_vals(rads[1][i] for i in night))
    others = [statistics.fmean(_vals(rads[k][i] for i in night)) for k in rads if k != 1]
    return r1 - statistics.fmean(others)


HEATSINK_CODES = (("warning", 13), ("fault", 25))  # W013 radiator temperature, E025 heatsink temperature


def _heatsink_code_hits(c: Ctx) -> list[tuple[str, int]]:
    hits = []
    for kind, bit in HEATSINK_CODES:
        col = "warningCode" if kind == "warning" else "faultCode"
        if c.log.has(col):
            prefix = "W" if kind == "warning" else "E"
            hits += [(f"{prefix}{bit:03d}", i) for i, code in enumerate(c.log.codes(col)) if code >> bit & 1]
    return hits


def rule_inverter_heatsink(c: Ctx) -> Check:
    log = c.log
    rads = {k: log.f(f"tradiator{k}") for k in (1, 2, 3) if log.has(f"tradiator{k}")}
    if not rads:
        return Check("inverter_heatsink", "ok", "No heatsink temperatures logged")
    peaks = {k: _max_at(log.t, v) for k, v in rads.items()}
    k_hot = max(peaks, key=lambda k: peaks[k][0] if peaks[k][0] is not None else -99)
    peak, peak_t, peak_i = peaks[k_hot]
    facts = [(f"Heatsink {k}", f"peak {_t(c, p[0])} at {_hm(p[1])}") for k, p in peaks.items() if p[0] is not None]
    gap = radiator_gap(c)
    if gap is not None:
        # Informational only: heatsink 1 sits on the stage that carries battery current, so it runs warmer, overnight too
        facts.append(("Heatsink 1 vs others, overnight",
                      _dt(c, gap, signed=True) + " (normal: heatsink 1 carries battery current)"))
    watch, act = _temp_limits(c, "heatsink")
    hits = _heatsink_code_hits(c)
    result = f"Peak {_t(c, peak)} (heatsink {k_hot})"
    if hits or peak >= act:
        sev = "act"
    elif peak >= watch:
        sev = "watch"
    else:
        return Check("inverter_heatsink", "ok", result, facts=facts)
    charge = log.kw("pCharge")[peak_i] if peak_i is not None else None
    detail = (f"Heatsink {k_hot} peaked at {_t(c, peak)} on {_day(peak_t)} at {_hm(peak_t)}"
              + (f" with the battery charging at {charge:.1f} kW" if charge else "") + ".")
    seen = sorted({code for code, _i in hits})
    if hits:
        first = log.t[hits[0][1]]
        detail += (f" The inverter logged {', '.join(seen)} (heatsink temperature out of range) in {len(hits)} "
                   f"sample(s), first at {_day(first)} {_hm(first)}.")
    return Check(
        "inverter_heatsink", sev, result,
        title=f"Inverter temperature code {', '.join(seen)}" if hits else f"Heatsink {k_hot} runs hot",
        detail=detail, facts=facts,
        action="Check the inverter's fans and clear its air path.",
    )

def rule_inverter_output_ceiling(c: Ctx) -> Check:
    ceiling = c.settings.get("output_ceiling_kw")
    if not ceiling:
        return Check("inverter_output_ceiling", "ok", "No output ceiling configured")
    days = [d for d in c.daily if d["clip_min"] > 0]
    total = sum(d["clip_min"] for d in c.daily)
    peak = max(_vals(c.log.kw("pinv")) or [0])
    if not days:
        return Check("inverter_output_ceiling", "ok", f"Peak output {peak:.1f} kW, under the {ceiling:g} kW ceiling")
    rate = float(c.settings.get("export_credit") or 0)
    loss = 0.5 * len(days)
    result = f"At the {ceiling:g} kW ceiling about {_hours(total)} on {len(days)} day(s)"
    names = ", ".join(d["day"] for d in days)
    return Check(
        "inverter_output_ceiling", "watch" if total >= 60 else "info", result,
        title=f"{ceiling:g} kW AC clipping",
        detail=f"The inverter sat at its output ceiling on {names}, {_hours(total)} in total. The surplus could not "
               "go to storage once the battery was tapering. Estimated loss is around half a kWh per clipped day.",
        action=f"Leave the clipping alone. About {loss:.1f} kWh"
               + (f" at {rate * 100:.1f}¢ is roughly ${loss * rate:.2f}." if rate else " is a small loss."),
        facts=[("Clipped", _hours(total)), ("Peak output", f"{peak:.2f} kW")],
    )


def _mppt_currents(c: Ctx) -> list[list[float | None]]:
    out = []
    for k in range(1, len(c.array_names) + 1):
        p, v = c.log.f(f"ppv{k}"), c.log.f(f"vpv{k}")
        out.append([pp / vv if pp is not None and vv and vv > 50 else None for pp, vv in zip(p, v)])
    return out


def rule_inverter_mppt_current(c: Ctx) -> Check:
    limits = list(c.settings.get("mppt_limits_a") or [])
    currents = _mppt_currents(c)
    facts, worst, hit = [], 0.0, "A string"
    for k, (name, cur) in enumerate(zip(c.array_names, currents)):
        top, top_t, _i = _max_at(c.log.t, cur)
        if top is None:
            continue
        lim = limits[k] if k < len(limits) else None
        facts.append((f"MPPT{k + 1} · {name}", f"max {top:.1f} A" + (f" of {lim:g} A" if lim else "")))
        if lim and top / lim > worst:
            worst, hit = top / lim, f"MPPT{k + 1} · {name}"
    if not limits:
        return Check("inverter_mppt_current", "ok", "No MPPT limits configured", facts=facts)
    if worst > 1.05:
        return Check("inverter_mppt_current", "watch", f"{hit} ran over its current limit", facts=facts,
                     title=f"{hit} over its current limit",
                     detail="One string drew more current than its MPPT input is rated for.",
                     action="Check the string's panel count and wiring against the inverter's input rating.")
    if worst >= 0.98:
        return Check("inverter_mppt_current", "info", f"{hit} touched its MPPT current limit", facts=facts,
                     title=f"{hit} at its input limit at times",
                     detail="On bright, cold days the string flat-tops slightly at the input limit. That costs a few "
                            "percent of an hour and harms nothing.",
                     action="None.")
    return Check("inverter_mppt_current", "ok", "All strings under their MPPT limits", facts=facts)


def rule_inverter_pv_voltage(c: Ctx) -> Check:
    vmax = c.settings.get("pv_max_v")
    peaks = [max(_vals(c.log.f(f"vpv{k}")) or [0]) for k in range(1, len(c.array_names) + 1)]
    top = max(peaks) if peaks else 0
    if not vmax:
        return Check("inverter_pv_voltage", "ok", f"Highest {top:.0f} V")
    result = f"Highest {top:.0f} V against the {vmax:g} V limit"
    if top >= vmax:
        sev = "act"
    elif top >= 0.95 * vmax:
        sev = "watch"
    else:
        return Check("inverter_pv_voltage", "ok", result)
    return Check("inverter_pv_voltage", sev, result, title=f"PV string voltage reached {top:.0f} V",
                 detail=f"A string reached {top:.0f} V against the inverter's {vmax:g} V input limit. Cold mornings raise "
                        "string voltage.",
                 action="Check the string's panel count against the cold-weather voltage rating.")


def rule_arrays_balance(c: Ctx) -> Check:
    labels = mppt_labels(c)
    full = [d for d in c.daily if not d["partial"] and d["pv"] > 0]
    if len(full) < 2:
        return Check("arrays_balance", "ok", "Not enough full days to compare")
    best = max(d["pv"] for d in full)
    best_by_array = [max(d["arrays"][k] for d in full) or 1 for k in range(len(labels))]
    low = [d for d in full if d["pv"] < 0.7 * best]
    weird = []
    for d in low:
        ratios = [d["arrays"][k] / best_by_array[k] for k in range(len(labels))]
        if max(ratios) - min(ratios) > 0.25:
            weird.append((d, ratios))
    facts = [(d["day"], " · ".join(f"{n} {d['arrays'][k] / best_by_array[k] * 100:.0f}%"
                                   for k, n in enumerate(labels))) for d in low]
    if weird:
        d, ratios = weird[0]
        k = ratios.index(min(ratios))
        return Check("arrays_balance", "watch", f"{labels[k]} fell behind on {d['day']}",
                     title=f"{labels[k]} underperformed on {d['day']}",
                     detail=f"On {d['day']} {labels[k]} made {ratios[k] * 100:.0f}% of its best day while the "
                            "others did not drop as much. Cloud lowers all arrays together, so this points at that array.",
                     action=f"Look for shading, snow, dirt or a tripped breaker on {labels[k]}.", facts=facts)
    if low:
        names = ", ".join(f"{d['day']} ({d['pv']:.0f} kWh)" for d in low)
        return Check("arrays_balance", "info", f"Low days explained by weather: {names}",
                     title="Weather explains the low days",
                     detail="All arrays dropped together on those days, which is the signature of cloud, not of an "
                            "array problem.",
                     action="None.", facts=facts)
    return Check("arrays_balance", "ok", "All arrays tracked each other every day")


def rule_data_gaps(c: Ctx) -> Check:
    log = c.log
    gaps = [(i, d) for i, d in enumerate(log.diffs) if d > 3 * log.interval]
    if not gaps:
        return Check("data_gaps", "ok", f"No gaps; samples every {log.interval:.0f} min")
    total = sum(d for _i, d in gaps)
    longest = max(d for _i, d in gaps)
    i, d = max(gaps, key=lambda g: g[1])
    a, b = log.t[i], log.t[i + 1]
    pv_a, pv_b = log.f("ePv1All")[i], log.f("ePv1All")[i + 1]
    ran = pv_a is not None and pv_b is not None and pv_b > pv_a
    sev = "watch" if total >= 360 or longest >= 180 else "info"
    return Check(
        "data_gaps", sev, f"{len(gaps)} gap(s), longest {_hours(longest)}",
        title=f"Logging gap, {_day(a)}" if len(gaps) == 1 else f"{len(gaps)} logging gaps",
        detail=f"No samples between {_hm(a)} and {_hm(b)} on {_day(a)}."
               + (" Energy counters kept advancing across the gap, so the inverter ran normally and only the data "
                  "upload dropped out." if ran else ""),
        action="Check the inverter's Wi-Fi dongle signal if gaps repeat.",
        facts=[(f"{_day(log.t[i])} {_hm(log.t[i])}", _hours(d)) for i, d in gaps[:6]],
    )


def rule_data_counter_crosscheck(c: Ctx) -> Check:
    log = c.log
    day_sum = sum(d["pv"] for d in c.daily)
    first = 0.0
    for k in range(1, len(c.array_names) + 1):
        v = log.f(f"ePv{k}Day")[0]
        first += v or 0
    life = 0.0
    for k in range(1, len(c.array_names) + 1):
        vals = _vals(log.f(f"ePv{k}All"))
        if len(vals) >= 2:
            life += vals[-1] - vals[0]
    if life <= 0:
        return Check("data_counter_crosscheck", "ok", "No lifetime counters to compare")
    day_energy = day_sum - first
    diff = abs(day_energy - life)
    pct = diff / life * 100
    result = f"Daily counters match lifetime counters within {pct:.1f}%"
    if pct <= 0.5 or diff <= 0.3:
        return Check("data_counter_crosscheck", "ok", result)
    return Check("data_counter_crosscheck", "watch" if pct > 2 else "info",
                 f"Daily and lifetime counters differ by {pct:.1f}%",
                 title="Energy counters disagree",
                 detail=f"Day counters add up to {day_energy:.1f} kWh but the lifetime counters moved {life:.1f} kWh. "
                        "Missing days in the export or a counter reset can cause this.",
                 action="Re-download the export for the range and check for missing days.")


RULES: list[Callable[[Ctx], Check]] = [
    rule_grid_outages, rule_grid_transient, rule_grid_high_voltage, rule_grid_low_voltage, rule_grid_frequency,
    rule_battery_pack_dropout, rule_battery_packs_online, rule_battery_cell_balance, rule_battery_cell_voltage,
    rule_battery_cell_temperature, rule_battery_soh, rule_battery_grid_carrying_load,
    rule_inverter_faults, rule_inverter_warnings, rule_inverter_heatsink, rule_inverter_output_ceiling,
    rule_inverter_mppt_current, rule_inverter_pv_voltage,
    rule_arrays_balance, rule_data_gaps, rule_data_counter_crosscheck,
]


# Notes: things worth knowing that aren't one of the 21 checks


def _notes(c: Ctx) -> list[Check]:
    log, notes = c.log, []
    load = log.kw("pLoad")
    nightly = []
    for d in c.days:
        night = [load[i] for i in c.day_idx[d] if log.t[i].hour < 5 and load[i] is not None]
        if len(night) >= 10:
            nightly.append(statistics.median(night))
    if nightly:
        lo, hi = min(nightly), max(nightly)
        notes.append(Check("note_baseload", "info", "",
                           title="Overnight baseload",
                           detail=f"The house draws a steady {lo:.2f}"
                                  + (f"–{hi:.2f}" if round(hi, 2) != round(lo, 2) else "")
                                  + f" kW at night, about {statistics.fmean(nightly) * 24:.0f} kWh a day if it ran all "
                                  "day. It is the largest single lever on how deep the battery cycles."))
    if c.soc_floor is not None:
        soc = log.f("SOC(%)")
        hits = [i for i, v in enumerate(soc) if v is not None and v <= c.soc_floor]
        if hits:
            i = hits[0]
            notes.append(Check("note_low_soc", "info", "",
                               title=f"Low-SOC morning, {_day(log.t[i])}",
                               detail=f"The bank reached its {c.soc_floor:g}% floor at {_hm(log.t[i])} on "
                                      f"{_day(log.t[i])} and the grid covered the shortfall. It did what it is set to do."))
            c.chart_notes.setdefault("soc", []).append(
                {"t": (log.t[i] - log.t[0]).total_seconds() / 3600, "v": c.soc_floor + 12,
                 "text": f"hit the {c.soc_floor:g}% floor {_day(log.t[i])}"})
    full = [d for d in c.daily if not d["partial"] and d["pv"] > 0]
    if len(c.array_names) >= 3 and len(full) >= 3:
        shares = [d["arrays"][0] / d["pv"] * 100 for d in full]
        steps = [b - a for a, b in zip(shares, shares[1:])]
        if all(s > 0 for s in steps[-3:]) and shares[-1] - shares[0] >= 0.8:
            notes.append(Check("note_share_drift", "info", "",
                               title=f"{c.array_names[0]} share rising",
                               detail=f"{c.array_names[0]}'s share of harvest rose "
                                      + " → ".join(f"{s:.1f}" for s in shares[-4:])
                                      + " %, as expected while the sun gets lower."))
    return notes


# Panels: temperatures, alarms, MPPT


def mppt_labels(c: Ctx) -> list[str]:
    return [f"MPPT{k + 1} · {name}" for k, name in enumerate(c.array_names)]


TEMP_SENSORS = (
    ("tradiator1", "Heatsink 1", "heatsink"),
    ("tradiator2", "Heatsink 2", "heatsink"),
    ("tradiator3", "Heatsink 3", "heatsink"),
    ("tinner", "Inverter internal", "internal"),
    ("tBat", "Battery (BT)", "battery"),
    ("MinCellTemp", "Cells, lowest", "cell"),
    ("MaxCellTemp", "Cells, highest", "cell"),
)


def temperatures(c: Ctx) -> list[dict[str, Any]]:
    rows = []
    gap = radiator_gap(c)
    for col, name, cls in TEMP_SENSORS:
        if not c.log.has(col):
            continue
        vals = c.log.f(col)
        v = _vals(vals)
        if not v:
            continue
        top, top_t, _i = _max_at(c.log.t, vals)
        watch, act = _temp_limits(c, cls)
        status = "act" if top >= act else "watch" if top >= watch else "ok"
        note = ""
        if len(v) > 50 and min(v) == top:
            note = f"the export reads {_t(c, top)} the whole period, so this column may not carry the live reading"
        if cls == "cell" and min(v) < 0:
            status, note = "act", "below freezing; the BMS limits charging"
        if col == "tradiator1" and gap is not None:
            note = f"{_dt(c, gap, signed=True)} vs heatsinks 2/3 overnight (normal: heatsink 1 carries battery current)"
        conv = (lambda x: round(x * 9 / 5 + 32, 1)) if _fahrenheit(c) else (lambda x: x)
        rows.append({
            "sensor": name, "column": col, "unit": "°F" if _fahrenheit(c) else "°C",
            "min": conv(min(v)), "max": conv(top), "typical": conv(round(statistics.median(v), 1)),
            "max_at": top_t.isoformat(), "watch": conv(watch), "act": conv(act), "status": status, "note": note,
        })
    return rows


def bms_occurrences(c: Ctx) -> list[dict[str, Any]]:
    out = []
    for col in ("BMSEvent1", "BMSEvent2"):
        if not c.log.has(col):
            continue
        values = c.log.codes(col)
        for value in sorted({v for v in values if v}):
            runs = _runs([v == value for v in values])
            name = codes.BMS_CODES.get(value)
            out.append({
                "code": f"{col} 0x{value:02X}", "name": name or f"Unknown code 0x{value:02X}, not in the table",
                "count": len(runs), "first": c.log.t[runs[0][0]].isoformat(), "last": c.log.t[runs[-1][1]].isoformat(),
                "verdict": "act" if len(runs) >= 3 else "watch",
                "source": "pylxpweb" if name else "unknown",
            })
    return out


RECONNECT_HOLD_S = 300


def _grid_events(c: Ctx) -> list[dict[str, Any]]:
    """Grid losses with the inverter's 300 s reconnect hold taken off the logged duration."""
    out = []
    for a, b in _runs([not ok for ok in c.grid_ok]):
        logged = (c.log.t[b] - c.log.t[a]).total_seconds() + c.log.interval * 60
        out.append({"start": c.log.t[a], "end": c.log.t[b], "logged_s": logged,
                    "real_s": max(logged - RECONNECT_HOLD_S, 0), "blip": a == b})
    return out


def alarms(c: Ctx, checks: Sequence[Check], occ: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by = {x.id: x for x in checks}

    def row(name: str, count: int, first: Any, last: Any, verdict: str, detail: str) -> dict[str, Any]:
        iso = lambda v: v.isoformat() if isinstance(v, datetime) else v  # noqa: E731
        return {"alarm": name, "count": count, "first": iso(first), "last": iso(last), "verdict": verdict, "detail": detail}

    rows = []
    for kind, check_id, name in (("fault", "inverter_faults", "Fault codes"), ("warning", "inverter_warnings", "Warning codes")):
        o = occ[kind]
        rows.append(row(name, sum(x["count"] for x in o), min((x["first"] for x in o), default=None),
                        max((x["last"] for x in o), default=None), by[check_id].severity,
                        "; ".join(x["why"] for x in o) if o else "none"))
    b = occ["bms"]
    rows.append(row("BMS alarms", sum(x["count"] for x in b), min((x["first"] for x in b), default=None),
                    max((x["last"] for x in b), default=None),
                    max((x["verdict"] for x in b), key=SEVERITY_ORDER.get, default="ok"),
                    "; ".join(f"{x['name']} ×{x['count']}" for x in b) if b else "none"))
    packs = int(c.settings.get("pack_count") or 0)
    per = _per_pack_limit(c, packs)
    limit = c.log.f("maxDischgCurr")
    lows = [i for i, v in enumerate(limit) if v is not None and packs and per and v < packs * per * 0.97]
    if packs and per:
        worst = min((limit[i] for i in lows), default=packs * per)
        online = int(round(worst / per))
        text = f"{packs}/{packs} online" if not lows else f"{packs - online} pack{'s' if packs - online != 1 else ''} out"
        rows.append(row(f"Packs ({text})", len(_runs([i in set(lows) for i in range(len(limit))])) if lows else 0,
                        c.log.t[lows[0]] if lows else None, c.log.t[lows[-1]] if lows else None,
                        by["battery_packs_online"].severity, f"discharge limit {worst:g} A of {packs * per:g} A"))
    events = _grid_events(c)
    rows.append(row("Grid events", len(events), events[0]["start"] if events else None,
                    events[-1]["end"] if events else None, by["grid_outages"].severity,
                    "; ".join(f"{_day(e['start'])} {_hm(e['start'])} {'blip' if e['blip'] else _hours(e['real_s'] / 60)}"
                              for e in events[:6]) if events else "grid present throughout"))
    over = [i for i, v in enumerate(c.log.f("vacr")) if (v or 0) > ANSI_SERVICE_LIMIT_V]
    hours = sum(d["h_over"] for d in c.daily)
    rows.append(row(f"Hours over {ANSI_SERVICE_LIMIT_V} V (ANSI service limit)", len({c.log.t[i].date() for i in over}),
                    c.log.t[over[0]] if over else None, c.log.t[over[-1]] if over else None,
                    by["grid_high_voltage"].severity, f"{hours:.1f} h"))
    return rows


def mppt_rows(c: Ctx) -> list[dict[str, Any]]:
    total = sum(d["pv"] for d in c.daily) or 1
    limits = list(c.settings.get("mppt_limits_a") or [])
    currents = _mppt_currents(c)
    rows = []
    for k, label in enumerate(mppt_labels(c)):
        kwh = sum(d["arrays"][k] for d in c.daily)
        p = c.log.kw(f"ppv{k + 1}")
        v = c.log.f(f"vpv{k + 1}")
        pk, pk_t, _i = _max_at(c.log.t, p)
        amps, amps_t, _j = _max_at(c.log.t, currents[k]) if k < len(currents) else (None, None, None)
        # Operating voltage while the string is working hard (at least half its peak)
        working = [v[i] for i in range(len(p)) if pk and (p[i] or 0) >= 0.5 * pk and v[i] is not None]
        lim = limits[k] if k < len(limits) else None
        rows.append({
            "label": label, "name": c.array_names[k], "kwh": round(kwh, 1), "share_pct": round(kwh / total * 100, 1),
            "peak_kw": round(pk, 2) if pk is not None else None, "peak_at": pk_t.isoformat() if pk_t else None,
            "peak_a": round(amps, 1) if amps is not None else None, "limit_a": lim,
            "v_min": min(working) if working else None, "v_max": max(working) if working else None,
            "status": "info" if lim and amps and amps >= 0.98 * lim else "ok",
        })
    return rows


# Report assembly


def _verdict(checks: Sequence[Check]) -> str:
    worst = max((SEVERITY_ORDER.get(x.severity, 0) for x in checks), default=0)
    return "act" if worst >= 3 else "watch" if worst >= 2 else "healthy"


def verdict_for(checks: list[Check]) -> str:
    return _verdict(checks)


def apply_known_issues(checks: list[Check], known_ids: set[str]) -> list[Check]:
    """Checks the user marked as known are reported as Info instead of Act or Watch."""
    for x in checks:
        if x.id in known_ids and SEVERITY_ORDER.get(x.severity, 0) > SEVERITY_ORDER["info"]:
            x.severity = "info"
            x.result = (x.result + " (known issue)").strip()
    return checks


def _stats(c: Ctx) -> list[dict[str, str]]:
    log, daily = c.log, c.daily
    pv = sum(d["pv"] for d in daily)
    load = sum(d["load"] for d in daily)
    export = sum(d["export"] for d in daily)
    imp = sum(d["import"] for d in daily)
    chg = sum(d["charge"] for d in daily)
    dis = sum(d["discharge"] for d in daily)
    best = max(daily, key=lambda d: d["pv"])
    rate = float(c.settings.get("import_rate") or 0)
    credit = float(c.settings.get("export_credit") or 0)
    stats = [{"label": "PV harvest", "value": f"{pv:.0f} kWh",
              "sub": f"best day {best['pv']:.1f} on {best['day']}" if len(daily) > 1 else f"peak {best['peak_kw']:.1f} kW"}]
    for k, name in enumerate(c.array_names):
        p = log.kw(f"ppv{k + 1}")
        top, top_t, _i = _max_at(log.t, p)
        stats.append({"label": f"MPPT{k + 1} · {name}", "value": f"{sum(d['arrays'][k] for d in daily):.0f} kWh",
                      "sub": f"peak {top:.2f} kW on {_day(top_t)}" if top is not None else ""})
    loads = [d["load"] for d in daily if not d["partial"]] or [d["load"] for d in daily]
    stats.append({"label": "House load", "value": f"{load:.0f} kWh",
                  "sub": f"{min(loads):.0f}–{max(loads):.0f} kWh per day" if len(loads) > 1 else ""})
    stats.append({"label": "Exported", "value": f"{export:.0f} kWh",
                  "sub": f"{export / pv * 100:.0f} % of harvest" if pv else ""})
    stats.append({"label": "Imported", "value": f"{imp:.1f} kWh",
                  "sub": f"{(1 - imp / load) * 100:.1f} % self-supplied" if load else ""})
    avoided, credit_v = (load - imp) * rate, export * credit
    stats.append({"label": "Value", "value": f"≈ ${avoided + credit_v:.0f}",
                  "sub": f"${avoided:.0f} avoided + ${credit_v:.0f} export credit"})
    socs = _vals(log.f("SOC(%)"))
    stats.append({"label": "Battery SOC", "value": f"{min(socs):.0f} → {max(socs):.0f} %" if socs else "–",
                  "sub": f"{chg:.0f} kWh in · {dis:.0f} out"})
    rt = None
    if chg and c.battery_kwh and socs:
        gained = (socs[-1] - socs[0]) / 100 * c.battery_kwh
        rt = (dis + gained) / chg * 100
    stats.append({"label": "Round trip", "value": f"≈ {rt:.0f} %" if rt else "–",
                  "sub": "adjusted for SOC gained" if rt else "needs battery capacity"})
    vpk, vpk_t, vpk_i = _max_at(log.t, log.f("vacr"))
    legs = [log.f(col)[vpk_i] for col in ("epsVoltL1N", "epsVoltL2N")] if vpk_i is not None else []
    stats.append({"label": "Grid volts max", "value": f"{vpk:.1f} V" if vpk else "–",
                  "sub": " / ".join(f"{v:.1f}" for v in legs) + " V per leg" if legs and None not in legs else ""})
    rad = [log.f(f"tradiator{k}") for k in (1, 2, 3) if log.has(f"tradiator{k}")]
    best_r = max(((_max_at(log.t, r), k) for k, r in enumerate(rad, 1)), key=lambda x: x[0][0] or -99, default=None)
    if best_r and best_r[0][0] is not None:
        (val, when, idx), _k = best_r
        charge = log.kw("pCharge")[idx]
        stats.append({"label": "Heatsink max", "value": _t(c, val),
                      "sub": f"{_day(when)}" + (f", {charge:.0f} kW battery charge" if charge and charge >= 1 else "")})
    return stats


def _summary(c: Ctx, checks: Sequence[Check], verdict: str) -> tuple[str, str]:
    pv = sum(d["pv"] for d in c.daily)
    load = sum(d["load"] for d in c.daily)
    imp = sum(d["import"] for d in c.daily)
    faults = next(x for x in checks if x.id == "inverter_faults")
    span = "week" if len(c.days) >= 6 else "day" if len(c.days) == 1 else "stretch"
    lead = {"healthy": "Good", "watch": "Mostly good", "act": "Needs attention this"}[verdict]
    first = (f"{lead} {span}. {pv:.0f} kWh harvested"
             + (f", {(1 - imp / load) * 100:.1f} % self-supplied" if load else "")
             + (", zero faults." if faults.severity == "ok" else ", with inverter faults."))
    worst = sorted((x for x in checks if x.severity in ("act", "watch")),
                   key=lambda x: -SEVERITY_ORDER[x.severity])
    if worst:
        first += f" {worst[0].title}."
    return first, worst[0].detail if worst else ""


def _chips(checks: Sequence[Check], alarm_rows: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    """Verdict chips: the alarm panel's rows first, so the headline and the panel always agree."""
    short = {"Fault codes": "Fault codes", "Warning codes": "Warning codes", "BMS alarms": "BMS events",
             "Grid events": "Grid outages"}
    chips = [{"label": f"{short[r['alarm']]} {r['count']}", "status": r["verdict"]}
             for r in alarm_rows if r["alarm"] in short]
    covered = {"inverter_faults", "inverter_warnings", "grid_outages"}
    for x in sorted(checks, key=lambda x: -SEVERITY_ORDER[x.severity]):
        if x.severity != "ok" and x.id not in covered:
            chips.append({"label": x.title, "status": x.severity})
    return chips[:9]

def _series(c: Ctx) -> dict[str, Any]:
    log = c.log
    t0 = log.t[0]
    series: dict[str, Any] = {
        "t0": t0.isoformat(),
        "t": [round((ts - t0).total_seconds() / 3600, 3) for ts in log.t],
        "pv": [None if v is None else round(v, 2) for v in c.pv_kw],
        "ac": [None if v is None else round(v, 2) for v in log.kw("pinv")],
        "v": log.f("vacr"),
        "soc": log.f("SOC(%)"),
        "cell_max": log.f("MaxCellVoltage"),
        "cell_min": log.f("MinCellVoltage"),
        "rad1": log.f("tradiator1"),
        "rad2": log.f("tradiator2"),
        "rad3": log.f("tradiator3"),
        "tbat": log.f("tBat"),
        "soc_floor": c.soc_floor,
        "bars": {
            "cats": [d["day"] for d in c.daily],
            "arrays": [{"name": n, "values": [d["arrays"][k] for d in c.daily]} for k, n in enumerate(mppt_labels(c))],
            "load": [d["load"] for d in c.daily],
            "export": [d["export"] for d in c.daily],
            "import": [d["import"] for d in c.daily],
        },
        "notes": c.chart_notes,
    }
    # Logger gaps break the lines
    for i, d in reversed(list(enumerate(log.diffs))):
        if d > 3 * log.interval:
            for key in ("pv", "ac", "v", "soc", "cell_max", "cell_min", "rad1", "rad2", "rad3", "tbat"):
                series[key].insert(i + 1, None)
            series["t"].insert(i + 1, round(series["t"][i] + log.interval / 60, 3))
    return series


def _downsample(series: dict[str, Any], limit: int = MAX_ATTR_POINTS) -> dict[str, Any]:
    n = len(series.get("t") or [])
    if n <= limit:
        return series
    step = math.ceil(n / limit)
    out = dict(series)
    for key in ("t", "pv", "ac", "v", "soc", "cell_max", "cell_min", "rad1", "rad2", "rad3", "tbat"):
        out[key] = series[key][::step]
    return out


def build_report(
    exports: dict[str, list[bytes]],
    settings: dict[str, Any],
    start: date,
    end: date,
) -> dict[str, Any]:
    """Analyze the exports (serial -> files) and return the report dict.

    The full-resolution chart series is returned under "_chart_series" for the chart renderer; the caller
    removes it before storing the report.
    """
    if not exports:
        raise AnalyzerError("No exports to analyze")
    # Per-sample checks run on the first inverter; parallel systems are a later addition
    serial = next(iter(exports))
    rows: list[dict[str, Any]] = []
    for content in exports[serial]:
        _header, file_rows = parse_export(content)
        rows.extend(r for r in file_rows if start <= r["_t"].date() <= end)
    log = Log(rows)
    if len(log) < 10:
        raise AnalyzerError("The exports for this range contain no data")
    for col in ("vacr", "SOC(%)", "ppv1", "ePv1Day"):
        if not log.has(col):
            raise AnalyzerError(f"The export is missing the {col} column")

    c = _build_ctx(log, settings, start, end)
    checks = [rule(c) for rule in RULES]
    occ = {"fault": code_occurrences(c, "fault"), "warning": code_occurrences(c, "warning"), "bms": bms_occurrences(c)}
    known = {s.strip() for s in settings.get("known_issues", "").split(",") if s.strip()}
    apply_known_issues(checks, known)
    notes = _notes(c)

    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for x in checks:
        counts[x.severity] += 1
    verdict = _verdict(checks)
    summary, detail = _summary(c, checks, verdict)

    ordered = sorted((x for x in checks if x.severity != "ok"), key=lambda x: -SEVERITY_ORDER[x.severity])
    actions: list[str] = []
    for x in ordered:
        for a in x.actions or ([x.action] if x.action else []):
            if a and not a.startswith("None") and a not in actions:
                actions.append(a)

    totals = {
        "pv": round(sum(d["pv"] for d in c.daily), 1),
        "arrays": [round(sum(d["arrays"][k] for d in c.daily), 1) for k in range(len(c.array_names))],
        "load": round(sum(d["load"] for d in c.daily), 1),
        "export": round(sum(d["export"] for d in c.daily), 1),
        "import": round(sum(d["import"] for d in c.daily), 1),
        "h_over": round(sum(d["h_over"] for d in c.daily), 1),
        "clip_min": sum(d["clip_min"] for d in c.daily),
    }
    full_series = _series(c)
    alarm_rows = alarms(c, checks, occ)
    return {
        "verdict": verdict,
        "summary": summary,
        "detail": detail,
        "chips": _chips(checks, alarm_rows),
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "through": log.t[-1].isoformat(),
        "samples": len(log),
        "interval_min": round(log.interval, 1),
        "array_names": c.array_names,
        "array_labels": mppt_labels(c),
        "temp_unit": "°F" if _fahrenheit(c) else "°C",
        "temperatures": temperatures(c),
        "alarms": alarm_rows,
        "codes": occ["fault"] + occ["warning"] + occ["bms"],
        "mppt": mppt_rows(c),
        "battery_kwh": c.battery_kwh,
        "counts": counts,
        "checks": [x.table_row() for x in checks],
        "findings": [x.finding() for x in ordered] + [x.finding() for x in notes],
        "stats": _stats(c),
        "daily": c.daily,
        "totals": totals,
        "actions": actions,
        "series": _downsample(full_series),
        "_chart_series": full_series,
        "generated_at": datetime.now().astimezone().isoformat(),
    }
