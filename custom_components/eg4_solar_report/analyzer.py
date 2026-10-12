"""Report analyzer: turns Monitor Center exports into findings.

Pure Python with no Home Assistant imports, so the rules can be unit tested on their own.
The 21 rules from the eg4_report.py prototype are ported into RULES (SPEC-022, pending the prototype files).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

SEVERITY_ORDER = {"ok": 0, "info": 1, "watch": 2, "act": 3}


class AnalyzerError(Exception):
    """The exports could not be analyzed."""


@dataclass
class Finding:
    id: str
    severity: str
    title: str
    detail: str = ""
    value: Any = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LogData:
    """Parsed export rows for the report range, merged across inverters."""

    start: date
    end: date
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


# A rule takes the parsed log and the user's settings, and returns its findings
Rule = Callable[[LogData, dict[str, Any]], list[Finding]]
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


def verdict_for(findings: list[Finding]) -> str:
    worst = max((SEVERITY_ORDER.get(f.severity, 0) for f in findings), default=0)
    if worst >= SEVERITY_ORDER["act"]:
        return "act"
    if worst >= SEVERITY_ORDER["watch"]:
        return "watch"
    return "healthy"


def apply_known_issues(findings: list[Finding], known_ids: set[str]) -> list[Finding]:
    """Findings the user marked as known are reported as Info instead of Act or Watch."""
    for f in findings:
        if f.id in known_ids and SEVERITY_ORDER.get(f.severity, 0) > SEVERITY_ORDER["info"]:
            f.severity = "info"
            f.detail = (f.detail + " (marked as a known issue)").strip()
    return findings


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

    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(log, settings))
    known = {s.strip() for s in settings.get("known_issues", "").split(",") if s.strip()}
    apply_known_issues(findings, known)

    counts = {sev: 0 for sev in SEVERITY_ORDER}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    return {
        "verdict": verdict_for(findings),
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "counts": counts,
        "findings": [f.as_dict() for f in findings],
        "numbers": {},
        "series": {},
        "generated_at": datetime.now().astimezone().isoformat(),
    }
