"""Hand-built SVG charts for the report, in the week-review console style.

Pure Python with no Home Assistant imports. The SVG uses only presentation attributes (no CSS, no
variables, no filters), so it renders in old WebViews such as Chrome 101 on wall tablets.

Input is the report's `series` dict:
- t0: ISO start time; t: hours since t0 for each sample (one value per sample below; None = gap)
- pv: PV total kW (DC); ac: inverter AC output kW; v: grid volts L-L; soc: %;
  cell_max, cell_min: highest and lowest cell volts
- bars: {"cats": ["Oct 1", ...], "arrays": [{"name": "South", "values": [kWh per day]}, ...],
         "load": [...], "export": [...], "import": [...]}
- soc_floor: the battery's discharge floor in %, if known
- notes: {chart key: [{"t": hours or "day": index, "v": value, "text": str}]}, written by the analyzer
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Callable, Sequence
from xml.sax.saxutils import escape

W, H = 600, 260
PLOT = {"l": 46, "r": 14, "t": 48, "b": 26}  # header row above the plot

BG = "#0d1020"
PANEL = "#141931"
RULE = "#2a3157"
GRID = "#222a4c"
FG = "#e4e7f6"
DIM = "#98a0c8"
FAINT = "#6f78a6"
SOUTH = "#f2b950"
EAST = "#4fd0c4"
WEST = "#c592f5"
TOTAL = "#e4e7f6"
AC = "#7f8fd8"
OK = "#62d594"
WATCH = "#f2b950"
ACT = "#ff7d6e"
INFO = "#7fb0ff"
ARRAY_COLORS = [SOUTH, EAST, WEST, INFO, OK, ACT]

MONO = "ui-monospace, 'SF Mono', 'Cascadia Mono', 'JetBrains Mono', Menlo, Consolas, 'Liberation Mono', monospace"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

CHARTS = ("harvest", "energy", "pv_ac", "grid_voltage", "soc", "cell_voltage")
TITLES = {
    "harvest": "Harvest by array",
    "energy": "Load, export, import",
    "pv_ac": "PV and inverter output",
    "grid_voltage": "Line voltage",
    "soc": "State of charge",
    "cell_voltage": "Cell voltage, highest and lowest",
}


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _text(x: float, y: float, s: str, fill: str = DIM, size: float = 10.5, anchor: str = "start",
          weight: str = "normal", spacing: float = 0) -> str:
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-family="{MONO}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}"{extra}>{escape(s)}</text>'
    )


def _hline(y: float, color: str, dash: str = "", width: float = 1) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{PLOT["l"]}" y1="{y:.1f}" x2="{W - PLOT["r"]}" y2="{y:.1f}" '
        f'stroke="{color}" stroke-width="{width}"{d}/>'
    )


def _frame(key: str, unit: str, legend: Sequence[tuple[str, str]], body: list[str]) -> bytes:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect x="0" y="0" width="{W}" height="{H}" rx="8" fill="{PANEL}"/>',
        _text(14, 22, TITLES[key], FG, 12.5, weight="bold"),
    ]
    x = W - 14
    for name, color in reversed(legend):
        x -= len(name) * 6.4
        parts.append(_text(x, 22, name, DIM, 10.5))
        x -= 13
        parts.append(f'<rect x="{x:.1f}" y="13" width="9" height="9" rx="2" fill="{color}"/>')
        x -= 14
    parts.append(_text(PLOT["l"] + 4, PLOT["t"] - 8, unit, FAINT, 10, spacing=0.8))
    parts.extend(body)
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def _empty(key: str, message: str = "No data for this range") -> bytes:
    return _frame(key, "", [], [_text(W / 2, (H + PLOT["t"]) / 2, message, FAINT, 12, "middle")])


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / max(count - 1, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 4, 5, 10) if m * mag >= raw)
    v = math.floor(lo / step) * step
    ticks = [round(v, 6)]
    # The last tick must reach hi so nothing is clipped
    while v < hi - step * 0.001:
        v += step
        ticks.append(round(v, 6))
    return ticks


def _box() -> tuple[float, float, float, float]:
    return PLOT["l"], PLOT["t"], W - PLOT["l"] - PLOT["r"], H - PLOT["t"] - PLOT["b"]


def _y_scale(ticks: list[float]) -> Callable[[float], float]:
    _px, py, _pw, ph = _box()
    lo, hi = ticks[0], ticks[-1]
    return lambda v: py + (1 - (min(max(v, lo), hi) - lo) / (hi - lo)) * ph


def _y_axis(ticks: list[float], y_of) -> list[str]:
    px, py, _pw, ph = _box()
    out = []
    for v in ticks:
        y = y_of(v)
        out.append(_hline(y, GRID))
        out.append(_text(px - 6, y + 3.5, _fmt(v), FAINT, 10.5, "end"))
    out.append(_hline(py + ph, RULE))
    return out


def _finite(vals: Sequence[float | None] | None) -> list[float]:
    return [v for v in (vals or []) if v is not None]


# Daily bar charts


def _bars(key: str, bars: dict[str, Any] | None, groups: list[tuple[str, str, list[float]]],
          stacked: bool, unit: str = "kWh / day", notes: Sequence[dict[str, Any]] = ()) -> bytes:
    cats = (bars or {}).get("cats") or []
    if not cats or not groups:
        return _empty(key)
    n = len(cats)
    vals = [[(g[2][i] if i < len(g[2]) else 0) or 0 for i in range(n)] for g in groups]
    tops = [sum(col) for col in zip(*vals)] if stacked else [max(col) for col in zip(*vals)]
    ticks = nice_ticks(0, max(tops) * 1.08 or 1, 4)
    y_of = _y_scale(ticks)
    px, py, pw, ph = _box()
    body = _y_axis(ticks, y_of)
    band = pw / n
    for i, cat in enumerate(cats):
        cx = px + band * (i + 0.5)
        body.append(_text(cx, H - 8, cat, FAINT, 10.5, "middle"))
        if stacked:
            bw = min(38, band * 0.56)
            base = 0.0
            for (_name, color, _v), col in zip(groups, vals):
                v = col[i]
                if v > 0:
                    y0, y1 = y_of(base), y_of(base + v)
                    body.append(
                        f'<rect x="{cx - bw / 2:.1f}" y="{y1:.1f}" width="{bw:.1f}" '
                        f'height="{max(y0 - y1, 0.8):.1f}" fill="{color}"/>'
                    )
                    base += v
            body.append(_text(cx, y_of(tops[i]) - 6, f"{tops[i]:.0f}", FG, 10.5, "middle"))
        else:
            gw = min(54, band * 0.78)
            bw = gw / len(groups)
            for k, ((_name, color, _v), col) in enumerate(zip(groups, vals)):
                v = col[i]
                y1 = y_of(v)
                body.append(
                    f'<rect x="{cx - gw / 2 + k * bw:.1f}" y="{y1:.1f}" width="{bw - 2:.1f}" '
                    f'height="{max(py + ph - y1, 0.8):.1f}" fill="{color}"/>'
                )
    for note in notes:
        i = note.get("day")
        if i is not None and 0 <= i < n:
            body.append(_text(px + band * (i + 0.5), y_of(note.get("v", 0)) - 18, note["text"], DIM, 10.5, "middle"))
    return _frame(key, unit, [(g[0], g[1]) for g in groups], body)


def render_harvest(series: dict[str, Any]) -> bytes:
    bars = series.get("bars") or {}
    arrays = bars.get("arrays") or []
    groups = [(a["name"], ARRAY_COLORS[k % len(ARRAY_COLORS)], a["values"]) for k, a in enumerate(arrays)]
    return _bars("harvest", bars, groups, stacked=True, notes=_notes(series, "harvest"))


def render_energy(series: dict[str, Any]) -> bytes:
    bars = series.get("bars") or {}
    groups = [
        (name, color, bars.get(k))
        for name, color, k in (("House load", TOTAL, "load"), ("Export", ACT, "export"), ("Import", INFO, "import"))
        if bars.get(k)
    ]
    return _bars("energy", bars, groups, stacked=False, notes=_notes(series, "energy"))


# Time-series line charts


def _notes(series: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return list((series.get("notes") or {}).get(key) or [])


def _x_axis(t0: datetime, span: float, x_of) -> list[str]:
    """Day gridlines with centred date labels, or 3-hour gridlines for a single day."""
    px, py, pw, ph = _box()
    out = []
    midnight = t0.replace(hour=0, minute=0, second=0, microsecond=0)
    if span <= 30:
        for hh in range(0, 25, 3):
            h = (midnight + timedelta(hours=hh) - t0).total_seconds() / 3600
            if 0 <= h <= span:
                x = x_of(h)
                out.append(f'<line x1="{x:.1f}" y1="{py}" x2="{x:.1f}" y2="{py + ph + 4}" stroke="{GRID}" stroke-width="1"/>')
                out.append(_text(x, H - 8, f"{hh:02d}:00", FAINT, 10.5, "middle"))
        return out
    day = midnight
    while (day - t0).total_seconds() / 3600 < span:
        h0 = max((day - t0).total_seconds() / 3600, 0)
        h1 = min((day + timedelta(days=1) - t0).total_seconds() / 3600, span)
        x0 = x_of(h0)
        out.append(f'<line x1="{x0:.1f}" y1="{py}" x2="{x0:.1f}" y2="{py + ph + 4}" stroke="{GRID}" stroke-width="1"/>')
        if h1 - h0 >= span / 30:
            out.append(_text(x_of((h0 + h1) / 2), H - 8, f"{MONTHS[day.month - 1]} {day.day}", FAINT, 10.5, "middle"))
        day += timedelta(days=1)
    return out


def _path(t: Sequence[float], vals: Sequence[float | None], x_of, y_of) -> str:
    """Path that breaks at gaps (None)."""
    d, pen = [], False
    for h, v in zip(t, vals):
        if v is None:
            pen = False
            continue
        d.append(f"{'L' if pen else 'M'}{x_of(h):.1f},{y_of(v):.1f}")
        pen = True
    return "".join(d)


def _line_chart(
    key: str,
    series: dict[str, Any],
    lines: list[tuple[str, str, str, float, str]],
    lo: float,
    hi: float,
    unit: str,
    refs: Sequence[tuple[float, str, str, str, str]] = (),
    band: tuple[float, float, str, float] | None = None,
    mark: tuple[str, bool, Callable[[float, datetime], str]] | None = None,
) -> bytes:
    """lines: (series key, legend name, color, width, dash); refs: (value, label, color, dash, anchor)."""
    t = series.get("t") or []
    if len(t) < 2 or not any(_finite(series.get(k)) for k, *_rest in lines):
        return _empty(key)
    t0 = datetime.fromisoformat(series["t0"])
    span = max(t[-1], 1e-6)
    px, py, pw, ph = _box()

    def x_of(h: float) -> float:
        return px + h / span * pw

    ticks = nice_ticks(lo, hi, 6)
    y_of = _y_scale(ticks)
    body = _y_axis(ticks, y_of) + _x_axis(t0, span, x_of)
    if band:
        b_lo, b_hi, color, opacity = band
        y1, y0 = y_of(min(b_hi, ticks[-1])), y_of(max(b_lo, ticks[0]))
        if y0 > y1:
            body.append(
                f'<rect x="{px}" y="{y1:.1f}" width="{pw}" height="{y0 - y1:.1f}" fill="{color}" fill-opacity="{opacity}"/>'
            )
    for value, label, color, dash, anchor in refs:
        if ticks[0] <= value <= ticks[-1]:
            y = y_of(value)
            body.append(_hline(y, color, dash))
            lx = px + 26 if anchor == "start" else px + pw - 4
            body.append(_text(lx, y - 4, label, color, 10.5, anchor))
    for k, _name, color, width, dash in lines:
        d = _path(t, series.get(k) or [], x_of, y_of)
        if d:
            dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
            body.append(
                f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
                f'stroke-linejoin="round" stroke-linecap="round"{dash_attr}/>'
            )
    if mark:
        k, use_max, label_of = mark
        pts = [(h, v) for h, v in zip(t, series.get(k) or []) if v is not None]
        if pts:
            h, v = (max if use_max else min)(pts, key=lambda p: p[1])
            cx, cy = x_of(h), y_of(v)
            anchor = "end" if cx > px + pw * 0.7 else "start"
            dx = -7 if anchor == "end" else 7
            body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{FG}"/>')
            body.append(_text(cx + dx, cy - 6 if use_max else cy + 14, label_of(v, t0 + timedelta(hours=h)), DIM, 10.5, anchor))
    for note in _notes(series, key):
        if "t" in note:
            nx = x_of(note["t"])
            anchor = "end" if nx > px + pw * 0.7 else "start"
            body.append(_text(nx, y_of(note.get("v", ticks[-1])), note["text"], DIM, 10.5, anchor))
    legend = [(name, color) for _k, name, color, _w, _d in lines]
    return _frame(key, unit, legend, body)


def _day_label(when: datetime) -> str:
    return f"{MONTHS[when.month - 1]} {when.day}"


def render_pv_ac(series: dict[str, Any], ceiling_kw: float | None) -> bytes:
    hi = max(_finite(series.get("pv")) + _finite(series.get("ac")) + [ceiling_kw or 0, 1])
    refs = [(ceiling_kw, f"{_fmt(ceiling_kw)} kW AC ceiling", WATCH, "2 4", "end")] if ceiling_kw else []
    return _line_chart(
        "pv_ac", series,
        [("pv", "PV total (DC)", TOTAL, 2.1, ""), ("ac", "AC out", AC, 1.3, "4 3")],
        0, hi * 1.08, "kW", refs=refs,
    )


def render_grid_voltage(series: dict[str, Any], hv_watch: float | None, hv_act: float | None) -> bytes:
    volts = _finite(series.get("v"))
    if not volts:
        return _empty("grid_voltage")
    refs = []
    if hv_watch:
        refs.append((hv_watch, f"{_fmt(hv_watch)} V", WATCH, "2 4", "start"))
    if hv_act:
        refs.append((hv_act, f"{_fmt(hv_act)} V typical trip", ACT, "6 3", "end"))
    band = (hv_watch, hv_act or max(volts), WATCH, 0.09) if hv_watch else None
    lo = min(volts) - 2
    hi = max(volts + [hv_act or 0]) + 1
    return _line_chart(
        "grid_voltage", series, [("v", "L–L volts at inverter", ACT, 1.7, "")], lo, hi, "V",
        refs=refs, band=band,
        mark=("v", True, lambda v, when: f"{v:.1f} V {_day_label(when)}"),
    )


def render_soc(series: dict[str, Any]) -> bytes:
    floor = series.get("soc_floor")
    refs = [(floor, f"{_fmt(floor)} % floor", WATCH, "2 4", "end")] if floor else []
    return _line_chart("soc", series, [("soc", "SOC", OK, 2.1, "")], 0, 100, "% SOC", refs=refs)


def render_cell_voltage(series: dict[str, Any], cell_v_max: float | None) -> bytes:
    cells = _finite(series.get("cell_max")) + _finite(series.get("cell_min"))
    if not cells:
        return _empty("cell_voltage")
    refs = [(cell_v_max, f"{_fmt(cell_v_max)} V cell limit", ACT, "6 3", "end")] if cell_v_max else []
    lo = min(cells) - 0.02
    hi = max(cells + [cell_v_max or 0]) + 0.02
    return _line_chart(
        "cell_voltage", series,
        [("cell_max", "max cell", SOUTH, 1.7, ""), ("cell_min", "min cell", EAST, 1.7, "")],
        lo, hi, "V per cell", refs=refs,
    )


def render_all(series: dict[str, Any] | None, settings: dict[str, Any]) -> dict[str, bytes]:
    series = series or {}
    return {
        "harvest": render_harvest(series),
        "energy": render_energy(series),
        "pv_ac": render_pv_ac(series, settings.get("output_ceiling_kw")),
        "grid_voltage": render_grid_voltage(series, settings.get("hv_watch"), settings.get("hv_act")),
        "soc": render_soc(series),
        "cell_voltage": render_cell_voltage(series, settings.get("cell_v_max")),
    }


def render_placeholders(message: str = "Generate a report to see this chart") -> dict[str, bytes]:
    return {key: _empty(key, message) for key in CHARTS}
