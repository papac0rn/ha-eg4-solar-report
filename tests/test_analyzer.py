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

Finding = analyzer.Finding


def test_verdict_uses_worst_severity():
    assert analyzer.verdict_for([]) == "healthy"
    assert analyzer.verdict_for([Finding("a", "ok", "A"), Finding("b", "info", "B")]) == "healthy"
    assert analyzer.verdict_for([Finding("a", "watch", "A")]) == "watch"
    assert analyzer.verdict_for([Finding("a", "watch", "A"), Finding("b", "act", "B")]) == "act"


def test_known_issues_downgrade_to_info():
    findings = [Finding("hv_grid", "act", "High grid voltage"), Finding("gap", "watch", "Data gap")]
    analyzer.apply_known_issues(findings, {"hv_grid"})
    assert findings[0].severity == "info"
    assert findings[1].severity == "watch"


def test_build_report_refuses_until_rules_are_ported():
    if analyzer.RULES:
        pytest.skip("rules are ported; covered by the fixture tests")
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.build_report({}, {}, date(2026, 10, 4), date(2026, 10, 11))


# Fixture tests for the 21 rules (anonymized logs in tests/fixtures/, including the prototype's
# injected faults, outage and data gap) are added when eg4_report.py is ported.
