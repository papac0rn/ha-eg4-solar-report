"""Analyzer tests. Loads analyzer.py by path so Home Assistant isn't needed.

The day fixture is a real Monitor Center export with the serial removed. The expected values come from the
prototype's published review of that same day.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

_PATH = Path(__file__).parents[1] / "custom_components" / "eg4_solar_report" / "analyzer.py"
_spec = importlib.util.spec_from_file_location("eg4_analyzer", _PATH)
analyzer = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = analyzer  # dataclasses need the module registered
_spec.loader.exec_module(analyzer)

Check = analyzer.Check
FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 9, 26)

SETTINGS = {
    "array_names": ["South", "East", "West"],
    "mppt_limits_a": [26, 26, 15],
    "pv_max_v": 600,
    "output_ceiling_kw": 16,
    "pack_count": 4,
    "pack_discharge_a": 200,
    "cell_v_max": 3.65,
    "import_rate": 0.086,
    "export_credit": 0.049,
    "nominal_voltage": 240,
    "hv_watch": 254,
    "hv_act": 264,
    "utility_name": "the utility",
    "battery_kwh": 0,
    "known_issues": "",
}


@pytest.fixture(scope="module")
def day_report() -> dict:
    content = (FIXTURES / "day-2026-09-26.xls").read_bytes()
    return analyzer.build_report({"anon": [content]}, SETTINGS, DAY, DAY)


def _check(report: dict, check_id: str) -> dict:
    return next(c for c in report["checks"] if c["id"] == check_id)


def _finding(report: dict, check_id: str) -> dict:
    return next(f for f in report["findings"] if f["id"] == check_id)


def test_catalog_has_21_unique_checks():
    ids = [rid for rid, _group, _name in analyzer.RULE_CATALOG]
    assert len(ids) == len(set(ids)) == 21
    assert [r.__name__.removeprefix("rule_") for r in analyzer.RULES] == ids


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


def test_parse_values():
    assert analyzer._num("70%") == 70
    assert analyzer._num("") is None
    assert analyzer._code("0x2F04") == 0x2F04
    assert analyzer._bits(1 << 4 | 1 << 27) == [4, 27]


def test_day_shape(day_report):
    assert day_report["samples"] == 260
    assert day_report["interval_min"] == 4.0
    assert len(day_report["checks"]) == 21
    assert sum(day_report["counts"].values()) == 21
    assert len(day_report["stats"]) == 12
    assert "_chart_series" in day_report


def test_day_pv_matches_answer_key(day_report):
    row = day_report["daily"][0]
    assert row["pv"] == pytest.approx(116.6, abs=0.05)
    assert row["arrays"] == [60.3, 29.4, 26.9]


def test_day_grid_voltage_matches_answer_key(day_report):
    f = _finding(day_report, "grid_high_voltage")
    facts = dict(f["facts"])
    assert facts["Peak"] == "259.9 V at Sep 26 14:46"
    assert facts["Peak export"] == "14.4 kW at 13:58"
    assert float(facts["V vs export"].split("=")[1]) == pytest.approx(0.96, abs=0.01)
    assert "between 12:53 and 15:5" in f["detail"]
    assert f["severity"] == "watch"


def test_day_clean_inverter_and_battery(day_report):
    for check_id in ("inverter_faults", "inverter_warnings", "grid_outages", "battery_packs_online",
                     "battery_pack_dropout", "battery_soh", "data_gaps", "data_counter_crosscheck"):
        assert _check(day_report, check_id)["status"] == "ok", check_id
    assert "800 A" in _check(day_report, "battery_packs_online")["result"]
    assert _check(day_report, "battery_soh")["result"] == "SOH 99%"
    assert _check(day_report, "grid_low_voltage")["result"] == "Low of 245.6 V"


def test_day_cell_spread_matches_answer_key(day_report):
    result = _check(day_report, "battery_cell_balance")["result"]
    typical = int(result.split("Spread ")[1].split(" mV")[0])
    assert 12 <= typical <= 17
    assert "44 mV peak" in result


def test_day_heatsink_imbalance_matches_answer_key(day_report):
    f = _finding(day_report, "inverter_heatsink")
    facts = dict(f["facts"])
    assert facts["Heatsink 1"] == "peak 73 °C at 12:13"
    gap = float(facts["Heatsink 1 vs others, PV off"].removesuffix(" °C"))
    assert gap == pytest.approx(3.3, abs=0.3)
    assert "airflow" in f["detail"]


def test_charts_render_from_the_day(day_report):
    charts_path = _PATH.with_name("charts.py")
    spec = importlib.util.spec_from_file_location("eg4_charts_day", charts_path)
    charts = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = charts
    spec.loader.exec_module(charts)
    rendered = charts.render_all(day_report["_chart_series"], SETTINGS)
    for name, data in rendered.items():
        assert b"No data" not in data, name


def test_downsampled_series_is_small(day_report):
    assert len(day_report["series"]["t"]) <= analyzer.MAX_ATTR_POINTS


def test_empty_range_raises():
    content = (FIXTURES / "day-2026-09-26.xls").read_bytes()
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.build_report({"anon": [content]}, SETTINGS, date(2026, 9, 27), date(2026, 9, 27))
