"""Chart SVG tests. Loads charts.py by path so Home Assistant isn't needed.

Set EG4_CHART_OUT=<folder> to also write the SVGs there for a visual check.
"""
from __future__ import annotations

import importlib.util
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

_PATH = Path(__file__).parents[1] / "custom_components" / "eg4_solar_report" / "charts.py"
_spec = importlib.util.spec_from_file_location("eg4_charts", _PATH)
charts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(charts)


def _week_series() -> dict:
    # 8 days of synthetic 4-minute samples
    t = [i * 4 / 60 for i in range(8 * 360)]
    pv, load, soc, v = [], [], [], []
    for h in t:
        hod = h % 24
        sun = max(0.0, math.sin((hod - 7) / 12 * math.pi))
        pv.append(round(15 * sun, 2))
        load.append(round(1.5 + (9 if 13 <= hod < 14 else 0) + 0.5 * math.sin(h), 2))
        soc.append(round(80 + 20 * math.sin((hod - 10) / 24 * 2 * math.pi), 1))
        v.append(round(245 + 15 * sun, 1))
    v[500] = None  # a logger gap
    return {
        "t0": "2026-10-04T00:01:00-04:00",
        "t": t,
        "pv": pv,
        "load": load,
        "soc": soc,
        "v": v,
        "bars": {
            "cats": ["Sun 10/4", "Mon 10/5", "Tue 10/6", "Wed 10/7", "Thu 10/8", "Fri 10/9", "Sat 10/10", "Sun 10/11"],
            "arrays": [
                {"name": "South", "values": [61.9, 62.9, 60.1, 58.5, 61.5, 29.0, 33.7, 21.6]},
                {"name": "East", "values": [26.6, 27.3, 25.5, 24.6, 25.5, 11.5, 17.5, 9.5]},
                {"name": "West & <roof>", "values": [28.2, 28.5, 26.6, 25.8, 26.9, 18.1, 16.0, 13.8]},
            ],
        },
    }


def _check_svg(data: bytes) -> ET.Element:
    text = data.decode("utf-8")
    # Old tablet WebViews: presentation attributes only
    assert "<style" not in text and "var(" not in text and "filter" not in text
    root = ET.fromstring(data)
    assert root.tag.endswith("svg")
    assert root.get("viewBox") == f"0 0 {charts.W} {charts.H}"
    return root


def test_all_charts_render_well_formed():
    out = os.environ.get("EG4_CHART_OUT")
    rendered = charts.render_all(_week_series(), {"hv_watch": 255, "hv_act": 264})
    assert set(rendered) == set(charts.CHARTS)
    for name, data in rendered.items():
        _check_svg(data)
        if out:
            Path(out, f"{name}.svg").write_bytes(data)


def test_single_day_and_empty_ranges():
    s = _week_series()
    day = {k: s[k][:360] for k in ("t", "pv", "load", "soc", "v")}
    day["t0"] = s["t0"]
    for data in charts.render_all(day, {}).values():
        _check_svg(data)
    for data in charts.render_all({}, {}).values():
        assert b"No data" in data
        _check_svg(data)
    for data in charts.render_placeholders().values():
        _check_svg(data)


def test_names_are_escaped():
    data = charts.render_daily_pv(_week_series()["bars"])
    assert b"WEST &amp; &lt;ROOF&gt;" in data


def test_nice_ticks_cover_the_range():
    ticks = charts.nice_ticks(0, 133.2)
    assert ticks[0] == 0 and ticks[-1] >= 133.2
    ticks = charts.nice_ticks(234, 265.6)
    assert ticks[0] <= 234 and ticks[-1] >= 265.6
