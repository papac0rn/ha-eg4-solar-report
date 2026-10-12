"""Report analyzer: turns Monitor Center exports into checks and findings.

Pure Python with no Home Assistant imports, so the rules can be unit tested on their own.
The 21 rules from the eg4_report.py prototype are ported into RULES (SPEC-022). RULE_CATALOG fixes their
ids, groups and names, taken from the prototype's published report.

Report shape (the sensor attributes and the dashboard read these keys):
- verdict: healthy / watch / act
- summary: one-line headline
- range: {start, end}; samples; interval_min
- counts: {ok, info, watch, act} over all checks
- checks: every check, as {id, group, check, result, status}
- findings: the checks that aren't OK, as {id, group, severity, title, detail, action, facts}
- numbers: the readout strip (NUMBER_KEYS)
- daily: one row per day (DAILY_KEYS)
- series: downsampled chart data (SERIES_KEYS)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

SEVERITY_ORDER = {"ok": 0, "info": 1, "watch": 2, "act": 3}

# Export columns the rules use (EG4 Monitor Center field names)
COL_PV_DAY = ("ePv1Day", "ePv2Day", "ePv3Day")
COL_PV_POWER = ("ppv1", "ppv2", "ppv3")
COL_LOAD = "pLoad"
COL_SOC = "SOC(%)"
COL_GRID_V = "vacr"

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

NUMBER_KEYS = (
    "pv_kwh", "pv_kwh_by_array", "home_kwh", "home_kwh_per_day", "self_sufficiency_pct",
    "export_kwh", "export_credit", "import_kwh", "import_cost", "battery_in_kwh",
    "battery_out_kwh", "round_trip_pct", "soc_min", "soc_max", "battery_kwh", "solar_value",
)
DAILY_KEYS = ("day", "pv_by_array", "pv", "home", "sent", "bought", "soc_min", "soc_max")
# t0 ISO start; t hours since t0 per sample; pv/load kW, soc %, v volts (None = gap);
# bars {"cats": [day labels], "arrays": [{"name", "values": kWh per day}]}. charts.py draws these.
SERIES_KEYS = ("t0", "t", "pv", "load", "soc", "v", "bars")


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

    def table_row(self) -> dict[str, Any]:
        group, name = _CATALOG_INDEX.get(self.id, ("Other", self.id))
        return {"id": self.id, "group": group, "check": name, "result": self.result, "status": self.severity}

    def finding(self) -> dict[str, Any]:
        group, _name = _CATALOG_INDEX.get(self.id, ("Other", self.id))
        data = asdict(self)
        data["group"] = group
        data["facts"] = [list(f) for f in self.facts]
        return data


_CATALOG_INDEX = {rid: (group, name) for rid, group, name in RULE_CATALOG}


@dataclass
class LogData:
    """Parsed export rows for the report range, merged across inverters."""

    start: date
    end: date
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


# A rule takes the parsed log and the user's settings, and returns its Check
Rule = Callable[[LogData, dict[str, Any]], Check]
RULES: list[Rule] = []


def parse_export(content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse one .xls export into its header and rows."""
    import xlrd  # imported here so the module loads before HA installs requirements

    try:
        book = xlrd.open_workbook(file_contents=content)
    except xlrd.XLRDError as err:
        raise AnalyzerError(f"Export is not a readable .xls file: {err}") from err
    sheet = book.sheet_by_index(0)
    if sheet.nrows == 0:
        return [], []
    header = [str(v).strip() for v in sheet.row_values(0)]
    rows = [dict(zip(header, sheet.row_values(i))) for i in range(1, sheet.nrows)]
    return header, rows


def verdict_for(checks: list[Check]) -> str:
    worst = max((SEVERITY_ORDER.get(c.severity, 0) for c in checks), default=0)
    if worst >= SEVERITY_ORDER["act"]:
        return "act"
    if worst >= SEVERITY_ORDER["watch"]:
        return "watch"
    return "healthy"


def apply_known_issues(checks: list[Check], known_ids: set[str]) -> list[Check]:
    """Checks the user marked as known are reported as Info instead of Act or Watch."""
    for c in checks:
        if c.id in known_ids and SEVERITY_ORDER.get(c.severity, 0) > SEVERITY_ORDER["info"]:
            c.severity = "info"
            c.result = (c.result + " (known issue)").strip()
    return checks


def build_report(
    exports: dict[str, list[bytes]],
    settings: dict[str, Any],
    start: date,
    end: date,
) -> dict[str, Any]:
    """Analyze the exports (serial -> one file per day) and return the report dict."""
    if not RULES:
        raise AnalyzerError("Analyzer rules not ported yet (waiting for the eg4_report.py prototype)")

    log = LogData(start=start, end=end)
    for files in exports.values():
        for content in files:
            header, rows = parse_export(content)
            if header and not log.columns:
                log.columns = header
            log.rows.extend(rows)
    if not log.rows:
        raise AnalyzerError("The exports for this range contain no data")

    checks = [rule(log, settings) for rule in RULES]
    known = {s.strip() for s in settings.get("known_issues", "").split(",") if s.strip()}
    apply_known_issues(checks, known)

    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for c in checks:
        counts[c.severity] = counts.get(c.severity, 0) + 1

    return {
        "verdict": verdict_for(checks),
        "summary": "",
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "samples": len(log.rows),
        "counts": counts,
        "checks": [c.table_row() for c in checks],
        "findings": [c.finding() for c in checks if c.severity != "ok"],
        "numbers": {},
        "daily": [],
        "series": {},
        "generated_at": datetime.now().astimezone().isoformat(),
    }
