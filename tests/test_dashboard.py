"""The Create Dashboard layout renders against a real report (plain Jinja stands in for HA's templates)."""
from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import jinja2

analyzer = importlib.import_module("eg4sr.analyzer")
dashboard = importlib.import_module("eg4sr.dashboard")

FIXTURES = Path(__file__).parent / "fixtures"


class _Registry:
    def async_get_entity_id(self, platform: str, domain: str, unique_id: str) -> str:
        return f"{platform}.station_{unique_id.removeprefix('entry_')}"


def _render_all(report: dict | None, state: str) -> list[str]:
    cards = dashboard._cards(_Registry(), "entry")
    env = jinja2.Environment()
    env.globals["states"] = lambda _eid: state
    env.globals["state_attr"] = lambda _eid, key: (report or {}).get(key)
    out = []
    for card in cards:
        if card["type"] == "markdown":
            out.append(env.from_string(card["content"]).render())
    return out


def test_view_is_one_full_width_report_card():
    view = dashboard.build_dashboard(_Registry(), "entry", "Solar Report · Station")["views"][0]
    assert view["panel"] is True and view["path"] == "solar-report"
    assert view["cards"] == [{"type": "custom:eg4-solar-report-card", "entity": "sensor.station_report"}]


def test_built_in_cards_layout():
    cards = dashboard._cards(_Registry(), "entry")
    assert cards[0]["type"] == "markdown"  # verdict first
    images = [c["entity"] for c in cards if c["type"] == "picture-entity"]
    assert len(images) == 7 and images[0] == "image.station_chart_harvest"


def test_cards_render_with_a_report():
    from test_analyzer import SETTINGS

    content = (FIXTURES / "day-2026-09-26.xls").read_bytes()
    report = analyzer.build_report({"anon": [content]}, SETTINGS, date(2026, 9, 26), date(2026, 9, 26))
    text = "\n".join(_render_all(report, report["verdict"]))
    assert 'alert-type="warning"' in text
    assert "MPPT1" in text and "116.6" in text
    assert "Airflow/fan" not in text and "Peak 259.9 V · 4.1 V below the 264 V trip (assumed)" in text
    assert "Packs (4/4 online)" in text


def test_cards_render_before_the_first_report():
    text = "\n".join(_render_all(None, "unknown"))
    assert "No report yet" in text
    assert "Nothing to report." in text
