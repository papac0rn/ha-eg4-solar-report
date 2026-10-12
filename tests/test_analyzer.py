"""Analyzer tests. Loads analyzer.py by path so Home Assistant isn't needed."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "custom_components" / "eg4_solar_report" / "analyzer.py"
_spec = importlib.util.spec_from_file_location("eg4_analyzer", _PATH)
analyzer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyzer)

Check = analyzer.Check


def test_catalog_has_21_unique_checks():
    ids = [rid for rid, _group, _name in analyzer.RULE_CATALOG]
    assert len(ids) == 21
    assert len(set(ids)) == 21


def test_verdict_uses_worst_severity():
    assert analyzer.verdict_for([]) == "healthy"
    assert analyzer.verdict_for([Check("grid_outages", "ok", "x"), Check("data_gaps", "info", "y")]) == "healthy"
    assert analyzer.verdict_for([Check("grid_high_voltage", "watch", "x")]) == "watch"
    assert analyzer.verdict_for([Check("grid_high_voltage", "watch", "x"), Check("inverter_faults", "act", "y")]) == "act"


def test_known_issues_downgrade_to_info():
    checks = [Check("grid_high_voltage", "act", "Peak 266 V"), Check("data_gaps", "watch", "1 gap")]
    analyzer.apply_known_issues(checks, {"grid_high_voltage"})
    assert checks[0].severity == "info"
    assert checks[1].severity == "watch"


def test_table_row_and_finding_use_catalog_names():
    c = Check("grid_high_voltage", "watch", "Peak 261.6 V", title="Grid voltage high", facts=[("Peak", "261.6 V")])
    assert c.table_row() == {
        "id": "grid_high_voltage", "group": "Grid", "check": "High grid voltage",
        "result": "Peak 261.6 V", "status": "watch",
    }
    assert c.finding()["group"] == "Grid"
    assert c.finding()["facts"] == [["Peak", "261.6 V"]]


def test_build_report_refuses_until_rules_are_ported():
    if analyzer.RULES:
        pytest.skip("rules are ported; covered by the fixture tests")
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.build_report({}, {}, date(2026, 10, 4), date(2026, 10, 11))


# Fixture tests for the 21 rules (anonymized logs in tests/fixtures/, including the prototype's
# injected faults, outage and data gap) are added when eg4_report.py is ported.
