"""Hand-built SVG charts for the report, in the console palette.

Pure Python with no Home Assistant imports. The SVG uses only presentation attributes (no CSS, no
variables, no filters), so it renders in old WebViews such as Chrome 101 on wall tablets.

Input is the report's `series` dict:
- t0: ISO start time; t: hours since t0 for each sample
- pv, load: kW; soc: %; v: grid volts (one value per sample, None for gaps)
- bars: {"cats": ["Sun 10/4", ...], "arrays": [{"name": "South", "values": [kWh per day]}, ...]}
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Sequence
from xml.sax.saxutils import escape

W, H = 800, 300
MARGIN = {"l": 52, "r": 16, "t": 40, "b": 30}

NIGHT = "#0b1020"
PANEL = "#141b2d"
RULE = "#26304a"
RULE_2 = "#34405f"
INK = "#e8ebf4"
INK_2 = "#aeb6ca"
MUTED = "#808aa3"
PV = "#c98500"
LOAD = "#9085e9"
TRACE = "#9db1db"
WARN = "#fab219"
CRIT = "#d03b3b"
ARRAY_COLORS = ["#d95926", "#3987e5", "#199e70", "#c98500", "#9085e9", "#7f95c4"]

MONO = "ui-monospace, 'SF Mono', 'Cascadia Mono', Consolas, 'Liberation Mono', monospace"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

CHARTS = ("daily_pv", "pv_load", "soc", "grid_voltage")


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if not float(v).is_integer() else str(int(v))


def _text(x: float, y: float, s: str, fill: str = INK_2, size: int = 12, anchor: str = "start",
          weight: str = "normal") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-family="{MONO}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{escape(s)}</text>'
    )


def _frame(title: str, legend: Sequence[tuple[str, str]], body: list[str]) -> bytes:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect x="0" y="0" width="{W}" height="{H}" rx="10" fill="{PANEL}"/>',
        _text(MARGIN["l"], 24, title.upper(), INK, 13, weight="bold"),
    ]
    # Legend, right-aligned
    x = W - MARGIN["r"]
    for name, color in reversed(legend):
        label = name.upper()
        x -= len(label) * 7.4
        parts.append(_text(x, 24, label, INK_2, 11))
        x -= 14
        parts.append(f'<rect x="{x:.1f}" y="15" width="10" height="10" rx="2" fill="{color}"/>')
        x -= 14
    parts.extend(body)
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def _empty(title: str, message: str = "No data for this range") -> bytes:
    return _frame(title, [], [_text(W / 2, H / 2 + 4, message, MUTED, 14, "middle")])


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / max(count - 1, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    v = math.floor(lo / step) * step
    ticks = [round(v, 6)]
    # The last tick must reach hi so nothing is clipped
    while v < hi - step * 0.001:
        v += step
        ticks.append(round(v, 6))
    return ticks


def _plot_box() -> tuple[float, float, float, float]:
    return MARGIN["l"], MARGIN["t"], W - MARGIN["l"] - MARGIN["r"], H - MARGIN["t"] - MARGIN["b"]


def _y_axis(ticks: list[float], y_of, unit: str) -> list[str]:
    px, _py, pw, _ph = _plot_box()
    out = []
    for v in ticks:
        y = y_of(v)
        out.append(f'<line x1="{px}" y1="{y:.1f}" x2="{px + pw}" y2="{y:.1f}" stroke="{RULE}" stroke-width="1"/>')
        out.append(_text(px - 8, y + 4, f"{_fmt(v)}{unit}", MUTED, 11, "end"))
    return out


def render_daily_pv(bars: dict[str, Any] | None) -> bytes:
    title = "Daily PV harvest by array, kWh"
    cats = (bars or {}).get("cats") or []
    arrays = (bars or {}).get("arrays") or []
    if not cats or not arrays:
        return _empty(title)

    totals = [sum((a["values"][i] or 0) for a in arrays) for i in range(len(cats))]
    ticks = nice_ticks(0, max(totals) * 1.12 or 1)
    top = ticks[-1]
    px, py, pw, ph = _plot_box()

    def y_of(v: float) -> float:
        return py + (1 - v / top) * ph

    body = _y_axis(ticks, y_of, "")
    band = pw / len(cats)
    bw = min(36, band * 0.6)
    for i, cat in enumerate(cats):
        cx = px + band * (i + 0.5)
        base = 0.0
        for k, arr in enumerate(arrays):
            v = arr["values"][i] or 0
            if v <= 0:
                continue
            y0, y1 = y_of(base), y_of(base + v)
            body.append(
                f'<rect x="{cx - bw / 2:.1f}" y="{y1:.1f}" width="{bw:.1f}" height="{max(y0 - y1, 0.5):.1f}" '
                f'fill="{ARRAY_COLORS[k % len(ARRAY_COLORS)]}"/>'
            )
            base += v
        body.append(_text(cx, y_of(totals[i]) - 6, f"{totals[i]:.0f}", INK, 11, "middle"))
        body.append(_text(cx, H - 10, cat, MUTED, 11, "middle"))
    legend = [(a["name"], ARRAY_COLORS[k % len(ARRAY_COLORS)]) for k, a in enumerate(arrays)]
    return _frame(title, legend, body)


def _x_scale(t: Sequence[float]):
    px, _py, pw, _ph = _plot_box()
    span = max(t[-1], 1e-6)
    return lambda h: px + (h / span) * pw, span


def _day_marks(t0: datetime, span: float) -> list[str]:
    """Midnight gridlines with the weekday label centred on each day."""
    px, py, pw, ph = _plot_box()
    out = []
    midnight = t0.replace(hour=0, minute=0, second=0, microsecond=0)
    day = midnight
    while (day - t0).total_seconds() / 3600 < span:
        h0 = max((day - t0).total_seconds() / 3600, 0)
        h1 = min((day + timedelta(days=1) - t0).total_seconds() / 3600, span)
        x0 = px + h0 / span * pw
        if h0 > 0:
            out.append(f'<line x1="{x0:.1f}" y1="{py}" x2="{x0:.1f}" y2="{py + ph}" stroke="{RULE_2}" stroke-width="1"/>')
        if h1 - h0 >= span / 40:
            xm = px + (h0 + h1) / 2 / span * pw
            label = f"{WEEKDAYS[day.weekday()]} {day.month}/{day.day}" if span > 30 else f"{int(h0 + t0.hour) % 24:02d}:00"
            out.append(_text(xm, H - 10, label, MUTED, 11, "middle"))
        day += timedelta(days=1)
    if span <= 30:
        # Single day: label every 3 hours instead
        out = []
        for hh in range(0, 25, 3):
            h = (midnight + timedelta(hours=hh) - t0).total_seconds() / 3600
            if 0 <= h <= span:
                x = px + h / span * pw
                out.append(f'<line x1="{x:.1f}" y1="{py}" x2="{x:.1f}" y2="{py + ph}" stroke="{RULE}" stroke-width="1"/>')
                out.append(_text(x, H - 10, f"{hh:02d}:00", MUTED, 11, "middle"))
    return out


def _path(t: Sequence[float], vals: Sequence[float | None], x_of, y_of) -> str:
    """Polyline path that breaks at gaps (None)."""
    d, pen = [], False
    for h, v in zip(t, vals):
        if v is None:
            pen = False
            continue
        d.append(f"{'L' if pen else 'M'}{x_of(h):.1f},{y_of(v):.1f}")
        pen = True
    return "".join(d)


def _line_chart(
    title: str,
    series: dict[str, Any],
    lines: list[tuple[str, str, str]],
    lo: float,
    hi: float,
    unit: str,
    area_key: str | None = None,
    refs: Sequence[tuple[float, str, str]] = (),
    mark: tuple[str, bool, str] | None = None,
) -> bytes:
    t = series.get("t") or []
    if len(t) < 2 or not any(series.get(key) for key, _n, _c in lines):
        return _empty(title)
    t0 = datetime.fromisoformat(series["t0"])
    x_of, span = _x_scale(t)
    ticks = nice_ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]
    px, py, pw, ph = _plot_box()

    def y_of(v: float) -> float:
        return py + (1 - (min(max(v, lo), hi) - lo) / (hi - lo)) * ph

    body = _y_axis(ticks, y_of, unit) + _day_marks(t0, span)
    for value, label, color in refs:
        if lo <= value <= hi:
            y = y_of(value)
            body.append(
                f'<line x1="{px}" y1="{y:.1f}" x2="{px + pw}" y2="{y:.1f}" stroke="{color}" '
                f'stroke-width="1.5" stroke-dasharray="6 4"/>'
            )
            body.append(_text(px + pw - 4, y - 5, label, color, 11, "end"))
    for key, _name, color in lines:
        vals = series.get(key) or []
        if key == area_key:
            d = _path(t, vals, x_of, y_of)
            if d:
                base = f"{y_of(lo):.1f}"
                # Close each segment down to the baseline for the fill
                segs = [s for s in d.split("M") if s]
                for seg in segs:
                    pts = seg.split("L")
                    x_first = pts[0].split(",")[0]
                    x_last = pts[-1].split(",")[0]
                    body.append(
                        f'<path d="M{x_first},{base}L{seg}L{x_last},{base}Z" fill="{color}" fill-opacity="0.22"/>'
                    )
        body.append(
            f'<path d="{_path(t, vals, x_of, y_of)}" fill="none" stroke="{color}" stroke-width="1.6" '
            f'stroke-linejoin="round"/>'
        )
    if mark:
        key, use_max, label_fmt = mark
        pts = [(h, v) for h, v in zip(t, series.get(key) or []) if v is not None]
        if pts:
            h, v = (max if use_max else min)(pts, key=lambda p: p[1])
            cx, cy = x_of(h), y_of(v)
            when = t0 + timedelta(hours=h)
            label = label_fmt.format(v=v, when=f"{WEEKDAYS[when.weekday()]} {when:%H:%M}")
            anchor = "end" if cx > px + pw * 0.75 else "start"
            dx = -8 if anchor == "end" else 8
            body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{INK}" stroke="{PANEL}" stroke-width="2"/>')
            body.append(_text(cx + dx, cy - 8 if use_max else cy + 16, label, INK, 11, anchor))
    legend = [(name, color) for _key, name, color in lines]
    return _frame(title, legend, body)


def _finite(vals: Sequence[float | None]) -> list[float]:
    return [v for v in vals if v is not None]


def render_pv_load(series: dict[str, Any]) -> bytes:
    hi = max(_finite(series.get("pv") or []) + _finite(series.get("load") or []) + [1])
    return _line_chart(
        "PV production and home load, kW", series,
        [("pv", "PV", PV), ("load", "Load", LOAD)], 0, hi * 1.1, "",
        area_key="pv", mark=("pv", True, "PV peak {v:.1f} kW"),
    )


def render_soc(series: dict[str, Any]) -> bytes:
    soc = _finite(series.get("soc") or [])
    lo = math.floor(min(soc + [100]) / 20) * 20 if soc else 0
    return _line_chart(
        "Battery state of charge, %", series, [("soc", "Charge", TRACE)], min(lo, 80), 100, "%",
        mark=("soc", False, "low {v:.0f}% {when}"),
    )


def render_grid_voltage(series: dict[str, Any], hv_watch: float | None, hv_act: float | None) -> bytes:
    volts = _finite(series.get("v") or [])
    refs = []
    if hv_act:
        refs.append((hv_act, f"{_fmt(hv_act)} V typical trip", CRIT))
    if hv_watch:
        refs.append((hv_watch, f"{_fmt(hv_watch)} V watch", WARN))
    lo = min(volts + [hv_watch or 255]) - 5 if volts else 220
    hi = max(volts + [hv_act or 264]) + 4 if volts else 270
    return _line_chart(
        "Grid voltage, V", series, [("v", "Grid", TRACE)], lo, hi, "",
        refs=refs, mark=("v", True, "peak {v:.1f} V"),
    )


def render_all(series: dict[str, Any] | None, settings: dict[str, Any]) -> dict[str, bytes]:
    series = series or {}
    return {
        "daily_pv": render_daily_pv(series.get("bars")),
        "pv_load": render_pv_load(series),
        "soc": render_soc(series),
        "grid_voltage": render_grid_voltage(series, settings.get("hv_watch"), settings.get("hv_act")),
    }


def render_placeholders(message: str = "Generate a report to see this chart") -> dict[str, bytes]:
    titles = {
        "daily_pv": "Daily PV harvest by array, kWh",
        "pv_load": "PV production and home load, kW",
        "soc": "Battery state of charge, %",
        "grid_voltage": "Grid voltage, V",
    }
    return {key: _empty(titles[key], message) for key in CHARTS}
