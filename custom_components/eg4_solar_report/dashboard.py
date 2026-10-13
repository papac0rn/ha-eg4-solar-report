"""Default "Solar Report" dashboard, built by the Create Dashboard button.

Built-in cards only (markdown, entities, picture-entity), so it works without any custom card. The layout follows the
report: verdict first, then the stat grid, alarms, temperatures, day-by-day table, findings, charts, actions and checks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # keeps this module importable without Home Assistant, for tests
    from homeassistant.helpers import entity_registry as er

from .charts import CHARTS, TITLES
from .const import DOMAIN

PILL = "{% set p = {'ok': '🟢', 'info': '🔵', 'watch': '🟡', 'act': '🔴'} %}"


def _eid(registry: er.EntityRegistry, entry_id: str, platform: str, key: str) -> str:
    return registry.async_get_entity_id(platform, DOMAIN, f"{entry_id}_{key}") or f"{platform}.eg4_solar_report_{key}"


def _md(content: str, title: str | None = None) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "markdown", "content": content}
    if title:
        card["title"] = title
    return card


def build_dashboard(registry: er.EntityRegistry, entry_id: str, title: str) -> dict[str, Any]:
    report = _eid(registry, entry_id, "sensor", "report")
    a = f"state_attr('{report}', "

    verdict = _md(
        "{% set s = states('" + report + "') %}"
        "{% set kind = {'healthy': 'success', 'watch': 'warning', 'act': 'error', 'error': 'error'}.get(s, 'info') %}"
        "<ha-alert alert-type=\"{{ kind }}\" title=\"{{ s | upper }}\">"
        "{% if s == 'error' %}{{ " + a + "'error') }}{% else %}{{ " + a + "'summary') or 'No report yet. Press Generate.' }}{% endif %}"
        "</ha-alert>\n"
        + PILL +
        "{% for c in " + a + "'chips') or [] %}{{ p.get(c.status, '⚪') }} {{ c.label }}{% if not loop.last %} · {% endif %}{% endfor %}\n\n"
        "{{ " + a + "'detail') or '' }}\n\n"
        "{% set n = " + a + "'counts') %}{% if n %}`{{ n.ok + n.info + n.watch + n.act }} checks · "
        "{{ n.act }} act · {{ n.watch }} watch · {{ n.info }} info · {{ n.ok }} ok`{% endif %}"
        " {% set r = " + a + "'range') %}{% if r %}`{{ r.start }} → {{ r.end }}`{% endif %}"
    )
    controls = {
        "type": "entities",
        "title": "Report",
        "entities": [
            _eid(registry, entry_id, "select", "report_period"),
            _eid(registry, entry_id, "date", "report_end_date"),
            _eid(registry, entry_id, "button", "generate_report"),
            _eid(registry, entry_id, "sensor", "last_generated"),
            _eid(registry, entry_id, "binary_sensor", "action_needed"),
        ],
    }
    stats = _md(
        "<table>{% for s in " + a + "'stats') or [] %}"
        "<tr><td>{{ s.label }}</td><td><b>{{ s.value }}</b></td><td>{{ s.sub }}</td></tr>{% endfor %}</table>",
        "Readout",
    )
    alarms = _md(
        PILL + "<table><tr><th></th><th>Alarm</th><th>Count</th><th>Last</th></tr>"
        "{% for r in " + a + "'alarms') or [] %}<tr><td>{{ p.get(r.verdict, '⚪') }}</td><td>{{ r.alarm }}</td>"
        "<td>{{ r.count }}</td><td>{{ (r.last or '')[5:16] | replace('T', ' ') }}</td></tr>{% endfor %}</table>",
        "Alarm status",
    )
    temps = _md(
        PILL + "{% set u = " + a + "'temp_unit') or '' %}<table><tr><th></th><th>Sensor</th><th>Min</th><th>Typical</th><th>Max</th></tr>"
        "{% for t in " + a + "'temperatures') or [] %}<tr><td>{{ p.get(t.status, '⚪') }}</td><td>{{ t.sensor }}</td>"
        "<td>{{ t.min }}</td><td>{{ t.typical }}</td><td>{{ t.max }} {{ u }}</td></tr>"
        "{% if t.note %}<tr><td></td><td colspan=4><i>{{ t.note }}</i></td></tr>{% endif %}{% endfor %}</table>",
        "Temperatures",
    )
    daily = _md(
        "{% set labels = " + a + "'array_labels') or [] %}<table><tr><th>Day</th><th>PV</th>"
        "{% for l in labels %}<th>{{ l.split(' · ')[0] }}</th>{% endfor %}"
        "<th>Load</th><th>Export</th><th>Import</th><th>SOC %</th><th>V max</th></tr>"
        "{% for d in " + a + "'daily') or [] %}<tr><td>{{ d.day }}</td><td>{{ d.pv }}</td>"
        "{% for v in d.arrays %}<td>{{ v }}</td>{% endfor %}<td>{{ d.load }}</td><td>{{ d.export }}</td>"
        "<td>{{ d.import }}</td><td>{{ d.soc_min }}–{{ d.soc_max }}</td><td>{{ d.v_max }}</td></tr>{% endfor %}"
        "{% set t = " + a + "'totals') %}{% if t %}<tr><td><b>Total</b></td><td><b>{{ t.pv }}</b></td>"
        "{% for v in t.arrays %}<td>{{ v }}</td>{% endfor %}<td>{{ t.load }}</td><td>{{ t.export }}</td>"
        "<td>{{ t.import }}</td><td></td><td></td></tr>{% endif %}</table>",
        "Day by day, kWh",
    )
    findings = _md(
        PILL + "{% for f in " + a + "'findings') or [] %}**{{ p.get(f.severity, '⚪') }} {{ f.title }}** · {{ f.group }}\n\n"
        "{{ f.detail }}\n\n{% if f.action and f.action != 'None.' %}_What to do:_ {{ f.action }}\n\n{% endif %}"
        "{% else %}Nothing to report.{% endfor %}",
        "Findings",
    )
    actions = _md(
        "{% for x in " + a + "'actions') or [] %}{{ loop.index }}. {{ x }}\n{% else %}Nothing to do.{% endfor %}",
        "What to do",
    )
    checks = _md(
        PILL + "<table>{% for c in " + a + "'checks') or [] %}<tr><td>{{ p.get(c.status, '⚪') }}</td>"
        "<td>{{ c.group }}</td><td>{{ c.check }}</td><td>{{ c.result }}</td></tr>{% endfor %}</table>",
        "All checks",
    )
    charts = [
        {"type": "picture-entity", "entity": _eid(registry, entry_id, "image", f"chart_{key}"),
         "name": TITLES[key], "show_name": False, "show_state": False}
        for key in CHARTS
    ]
    return {
        "views": [
            {
                "title": title,
                "path": "report",
                "icon": "mdi:solar-power-variant",
                "cards": [verdict, controls, stats, alarms, temps, daily, findings, *charts, actions, checks],
            }
        ]
    }
