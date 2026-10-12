"""Analyzer tests (loaded through conftest's eg4sr package, so Home Assistant isn't needed).

The day fixture is a real Monitor Center export with the serial removed. The expected values come from the
prototype's published review of that same day.
"""
from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import pytest

analyzer = importlib.import_module("eg4sr.analyzer")
charts = importlib.import_module("eg4sr.charts")

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
    rendered = charts.render_all(day_report["_chart_series"], SETTINGS)
    for name, data in rendered.items():
        assert b"No data" not in data, name


def test_downsampled_series_is_small(day_report):
    assert len(day_report["series"]["t"]) <= analyzer.MAX_ATTR_POINTS


def test_empty_range_raises():
    content = (FIXTURES / "day-2026-09-26.xls").read_bytes()
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.build_report({"anon": [content]}, SETTINGS, date(2026, 9, 27), date(2026, 9, 27))


@pytest.fixture(scope="module")
def dropout_report() -> dict:
    content = (FIXTURES / "pack-dropout-2026-08-24_27.xls").read_bytes()
    return analyzer.build_report({"anon": [content]}, SETTINGS, date(2026, 8, 24), date(2026, 8, 27))


def test_pack_dropout_is_caught_and_recovery_found(dropout_report):
    """August: one of four packs was offline (600 A limit) until it rejoined at 12:53 on Aug 26."""
    f = _finding(dropout_report, "battery_packs_online")
    assert f["severity"] == "act"
    assert f["title"] == "Battery pack offline: 3 of 4 packs"
    assert "until Aug 26 12:49" in f["detail"]
    assert "SOC stepped from 95% to 88%" in f["detail"]
    assert dropout_report["verdict"] == "act"


def test_multi_day_table(dropout_report):
    days = [d["day"] for d in dropout_report["daily"]]
    assert days == ["Aug 24", "Aug 25", "Aug 26", "Aug 27"]
    assert dropout_report["daily"][0]["pv"] == pytest.approx(135.7, abs=0.05)
    assert dropout_report["totals"]["pv"] == pytest.approx(135.7 + 139.1 + 97.4 + 121.7, abs=0.2)
    assert _check(dropout_report, "data_counter_crosscheck")["status"] == "ok"

def _ctx_with_codes(warnings: dict[int, int]) -> object:
    """The real day with warning codes injected at sample indexes."""
    _header, rows = analyzer.parse_export((FIXTURES / "day-2026-09-26.xls").read_bytes())
    for i, code in warnings.items():
        rows[i]["warningCode"] = f"0x{code:X}"
    log = analyzer.Log(rows)
    return analyzer._build_ctx(log, SETTINGS, DAY, DAY)


def test_code_judgement_transient_persistent_unknown():
    ctx = _ctx_with_codes({
        100: 1 << 17,                                  # W017 once, 1 sample: transient
        **{i: 1 << 27 for i in range(150, 160)},        # W027 for 40 min: persistent
        200: 1 << 19,                                   # bit 19 is not in the table
    })
    occ = {o["code"]: o for o in analyzer.code_occurrences(ctx, "warning")}
    assert occ["W017"]["classification"] == "transient"
    assert occ["W017"]["verdict"] in ("ok", "info")
    assert occ["W027"]["classification"] == "persistent"
    assert occ["W027"]["verdict"] == "act"
    assert occ["W027"]["name"] == "Battery open circuit"
    assert occ["W019"]["verdict"] == "watch"
    assert occ["W019"]["name"].startswith("Unknown code W019")


def test_transient_with_voltage_excursion_is_ok():
    # Sample near the 14:46 peak (259.9 V is within 2 V of nothing, so use a low hv_act to make it an excursion)
    ctx = _ctx_with_codes({200: 1 << 17})
    ctx.hv_act = 255
    occ = analyzer.code_occurrences(ctx, "warning")
    assert occ[0]["verdict"] == "ok"
    assert "cleared on its own" in occ[0]["why"]


def test_panels(day_report):
    temps = {t["sensor"]: t for t in day_report["temperatures"]}
    assert temps["Heatsink 1"]["max"] == 73
    assert temps["Heatsink 1"]["status"] == "watch"
    assert "airflow/fan" in temps["Heatsink 1"]["note"]
    alarms = {a["alarm"].split(" (")[0]: a for a in day_report["alarms"]}
    assert alarms["Fault codes"]["count"] == 0 and alarms["Fault codes"]["verdict"] == "ok"
    assert alarms["Packs"]["verdict"] == "ok"
    assert any(a["alarm"] == "Packs (4/4 online)" for a in day_report["alarms"])
    assert alarms["Over-voltage hours"]["verdict"] == "watch"
    assert day_report["array_labels"] == ["MPPT1 · South", "MPPT2 · East", "MPPT3 · West"]
    south = day_report["mppt"][0]
    assert south["kwh"] == 60.3 and south["limit_a"] == 26
    assert day_report["stats"][1]["label"] == "MPPT1 · South"
    # The headline chips come from the alarm panel
    chips = {c["label"]: c["status"] for c in day_report["chips"]}
    assert chips["Fault codes 0"] == "ok" and chips["Grid outages 0"] == "ok"


def test_heatsink_imbalance_is_watch(day_report):
    f = _finding(day_report, "inverter_heatsink")
    assert f["severity"] == "watch"
    assert f["title"] == "Airflow/fan on heatsink 1"


def test_dropout_alarm_row(dropout_report):
    row = next(a for a in dropout_report["alarms"] if a["alarm"].startswith("Packs"))
    assert row["alarm"] == "Packs (1 pack out)"
    assert row["verdict"] == "act"

def test_fahrenheit_report():
    content = (FIXTURES / "day-2026-09-26.xls").read_bytes()
    r = analyzer.build_report({"anon": [content]}, {**SETTINGS, "temp_unit": "F"}, DAY, DAY)
    assert r["temp_unit"] == "°F"
    temps = {t["sensor"]: t for t in r["temperatures"]}
    assert temps["Heatsink 1"]["max"] == pytest.approx(163.4)
    assert temps["Heatsink 1"]["unit"] == "°F"
    assert temps["Heatsink 1"]["watch"] == pytest.approx(203)
    facts = dict(_finding(r, "inverter_heatsink")["facts"])
    assert facts["Heatsink 1"] == "peak 163 °F at 12:13"
    assert facts["Heatsink 1 vs others, PV off"].endswith("°F")
    assert next(s for s in r["stats"] if s["label"] == "Heatsink max")["value"] == "163 °F"
    assert b"\xc2\xb0F" in charts.render_all(r["_chart_series"], {**SETTINGS, "temp_unit": "F"})["temperatures"]


def test_per_pack_limit_is_learned_when_not_set():
    content = (FIXTURES / "pack-dropout-2026-08-24_27.xls").read_bytes()
    r = analyzer.build_report({"anon": [content]}, {**SETTINGS, "pack_discharge_a": 0}, date(2026, 8, 24), date(2026, 8, 27))
    assert _finding(r, "battery_packs_online")["title"] == "Battery pack offline: 3 of 4 packs"