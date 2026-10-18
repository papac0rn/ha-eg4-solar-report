"""Chart SVG tests (charts.py is loaded through conftest's eg4sr package, so Home Assistant isn't needed).

Set EG4_CHART_OUT=<folder> to also write the SVGs there for a visual check.
"""
from __future__ import annotations

import importlib
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

charts = importlib.import_module("eg4sr.charts")

SETTINGS = {"hv_watch": 260, "hv_act": 264, "output_ceiling_kw": 16, "cell_v_max": 3.65}


def _week_series() -> dict:
    # 8 days of synthetic 4-minute samples
    t = [i * 4 / 60 for i in range(8 * 360)]
    pv, ac, soc, v, cmax, cmin, rad = [], [], [], [], [], [], []
    for h in t:
        hod = h % 24
        sun = max(0.0, math.sin((hod - 7) / 12 * math.pi))
        pv.append(round(19 * sun, 2))
        ac.append(round(min(16.0, 17 * sun), 2))
        soc.append(round(80 + 20 * math.sin((hod - 10) / 24 * 2 * math.pi), 1))
        v.append(round(248 + 13 * sun, 1))
        cmax.append(round(3.33 + 0.25 * sun, 3))
        cmin.append(round(3.31 + 0.22 * sun, 3))
        rad.append(round(40 + 30 * sun, 1))
    v[500] = None  # a logger gap
    cmin[1200] = 3.404  # the one-sample blip
    cats = [f"Oct {d}" for d in range(1, 9)]
    return {
        "t0": "2026-10-01T00:02:00-04:00",
        "t": t, "pv": pv, "ac": ac, "soc": soc, "v": v, "cell_max": cmax, "cell_min": cmin,
        "rad1": [r + 3 for r in rad], "rad2": rad, "rad3": [r - 1 for r in rad], "tbat": [22.0] * len(t),
        "soc_floor": 20,
        "bars": {
            "cats": cats,
            "arrays": [
                {"name": "South", "values": [28.8, 34.3, 61.6, 61.9, 62.9, 60.1, 58.5, 61.5]},
                {"name": "East", "values": [14.5, 13.9, 27.6, 26.6, 27.3, 25.5, 24.6, 25.5]},
                {"name": "West & <roof>", "values": [16.1, 21.5, 28.6, 28.2, 28.5, 26.6, 25.8, 26.9]},
            ],
            "load": [55.0, 48.8, 72.4, 53.4, 43.1, 43.0, 75.7, 44.2],
            "export": [1.5, 0.2, 30.1, 56.5, 68.5, 61.9, 29.2, 53.8],
            "import": [1.4, 0.1, 0.5, 0.0, 0.1, 0.0, 0.5, 0.1],
        },
        "notes": {"soc": [{"t": 9, "v": 30, "text": "cloudy stretch, hit the floor"}]},
    }


def _check_svg(data: bytes) -> ET.Element:
    text = data.decode("utf-8")
    # Old tablet WebViews: presentation attributes only
    assert "<style" not in text and "var(" not in text and "filter" not in text
    root = ET.fromstring(data)
    assert root.tag.endswith("svg")
    assert root.get("viewBox") == f"0 0 {charts.W} {charts.H}"
    return root


def test_all_seven_charts_render_well_formed():
    out = os.environ.get("EG4_CHART_OUT")
    rendered = charts.render_all(_week_series(), SETTINGS)
    assert list(rendered) == list(charts.CHARTS)
    assert len(rendered) == 7
    for name, data in rendered.items():
        _check_svg(data)
        assert b"No data" not in data, name
        if out:
            Path(out, f"{name}.svg").write_bytes(data)


def test_thresholds_are_drawn():
    rendered = charts.render_all(_week_series(), SETTINGS)
    assert b"16 kW AC ceiling" in rendered["pv_ac"]
    assert b"260 V" in rendered["grid_voltage"] and b"264 V typical trip" in rendered["grid_voltage"]
    assert b"254 V ANSI" in rendered["grid_voltage"]
    assert b"20 % floor" in rendered["soc"]
    assert b"3.65 V cell limit" in rendered["cell_voltage"]


def test_single_day_and_empty_ranges():
    s = _week_series()
    day = {k: s[k][:360] for k in ("t", "pv", "ac", "soc", "v", "cell_max", "cell_min")}
    day["t0"] = s["t0"]
    for data in charts.render_all(day, SETTINGS).values():
        _check_svg(data)
    for data in charts.render_all({}, {}).values():
        assert b"No data" in data
        _check_svg(data)
    for data in charts.render_placeholders().values():
        _check_svg(data)


def test_names_are_escaped():
    data = charts.render_harvest(_week_series())
    assert b"West &amp; &lt;roof&gt;" in data


def test_nice_ticks_cover_the_range():
    ticks = charts.nice_ticks(0, 133.2)
    assert ticks[0] == 0 and ticks[-1] >= 133.2
    ticks = charts.nice_ticks(234, 265.6)
    assert ticks[0] <= 234 and ticks[-1] >= 265.6
