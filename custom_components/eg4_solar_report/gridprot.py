"""The inverter's grid-protection settings, read from the Monitor Center (read-only).

Pure Python with no Home Assistant imports. The cloud `remoteRead` endpoint returns named holding parameters
(pylxpweb `constants/registers.py`). This module only interprets values that were already read; nothing here or in
the code that reads them ever writes a parameter.
"""
from __future__ import annotations

from typing import Any

# Parameter names, as the Monitor Center returns them
STAGES = (1, 2, 3)
KEYS = (
    *(f"HOLD_GRID_VOLT_LIMIT{n}_{side}{suffix}" for n in STAGES for side in ("HIGH", "LOW") for suffix in ("", "_TIME")),
    "HOLD_GRID_VOLT_MOV_AVG_HIGH",
    "HOLD_GRID_VOLT_CONN_HIGH",
    "HOLD_GRID_VOLT_CONN_LOW",
    "HOLD_CONNECT_TIME",
    "HOLD_RECONNECT_TIME",
    "FUNC_VOLT_WATT_EN",
    "HOLD_DISCHG_CUT_OFF_SOC_EOD",    # on-grid discharge floor, %
    "HOLD_SOC_LOW_LIMIT_EPS_DISCHG",  # off-grid (outage) discharge cut-off, %
    *(f"HOLD_VW_{x}{n}" for x in ("V", "P") for n in (1, 2, 3, 4)),
)
# Register ranges that hold them (the same three ranges the Monitor Center's parameter page reads)
READ_RANGES = ((0, 127), (127, 127), (240, 127))

# Times are in 10 ms units: a live FlexBOSS21 read gives 1300 / 16 for the IEEE 1547 Cat III 13 s / 0.16 s stages
TIME_UNIT_S = 0.01


def _num(v: Any) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _volts(raw: Any, nominal_v: float, high: bool = True) -> float | None:
    """Volts on the report's line-to-line basis; None when the value doesn't look like a grid voltage.

    The Monitor Center returns volts (a FlexBOSS21 read gives "264"); a value over 1000 is taken as 0.1 V units.
    Only a HIGH limit below nominal can be a per-leg value; low limits go down to 0.5 pu (120 V on 240 V).
    """
    v = _num(raw)
    if v is None or v <= 0:
        return None
    if v > 1000:  # register value in 0.1 V
        v /= 10
    if high and nominal_v >= 200 and 0.4 * nominal_v <= v <= 0.75 * nominal_v:  # per-leg limit on split phase
        v *= 2
    lo = 0.9 * nominal_v if high else 0.3 * nominal_v
    return round(v, 1) if lo <= v <= 1.5 * nominal_v else None


def _seconds(raw: Any) -> float | None:
    t = _num(raw)
    return round(t * TIME_UNIT_S, 2) if t is not None and t >= 0 else None


def _enabled(raw: Any) -> bool:
    return str(raw).strip().lower() in ("1", "true", "on", "enable", "enabled")


def interpret(raw: dict[str, Any] | None, nominal_v: float = 240.0) -> dict[str, Any] | None:
    """Turn the raw parameter block into the values the voltage check uses, or None when nothing usable was read."""
    if not raw:
        return None
    stages = []
    for n in STAGES:
        v = _volts(raw.get(f"HOLD_GRID_VOLT_LIMIT{n}_HIGH"), nominal_v)
        t = _seconds(raw.get(f"HOLD_GRID_VOLT_LIMIT{n}_HIGH_TIME"))
        if v is not None:
            stages.append({"stage": n, "volts": v, "seconds": t, "enabled": t is None or t > 0})
    low = []
    for n in STAGES:
        v = _volts(raw.get(f"HOLD_GRID_VOLT_LIMIT{n}_LOW"), nominal_v, high=False)
        if v is not None:
            low.append({"stage": n, "volts": v, "seconds": _seconds(raw.get(f"HOLD_GRID_VOLT_LIMIT{n}_LOW_TIME"))})
    enabled = [s for s in stages if s["enabled"]]
    trip = min(enabled, key=lambda s: s["volts"]) if enabled else None
    vw_points = []
    for n in (1, 2, 3, 4):
        v = _volts(raw.get(f"HOLD_VW_V{n}"), nominal_v)
        p = _num(raw.get(f"HOLD_VW_P{n}"))
        if v is not None:
            vw_points.append({"volts": v, "percent": p})
    vw_flag = raw.get("FUNC_VOLT_WATT_EN")
    out = {
        "trip": trip,
        "stages": stages,
        "low_stages": low,
        "mov_avg_high": _volts(raw.get("HOLD_GRID_VOLT_MOV_AVG_HIGH"), nominal_v),
        "connect_low": _volts(raw.get("HOLD_GRID_VOLT_CONN_LOW"), nominal_v, high=False),
        "connect_high": _volts(raw.get("HOLD_GRID_VOLT_CONN_HIGH"), nominal_v),
        "reconnect_s": _num(raw.get("HOLD_RECONNECT_TIME")),
        "volt_watt": {
            # Unknown enable flag: the curve exists but whether it acts is unknown, so it isn't claimed as active
            "enabled": _enabled(vw_flag) if vw_flag is not None else None,
            "points": vw_points,
        },
    }
    if trip is None and out["mov_avg_high"] is None and not vw_points:
        return None
    return out


def stage_text(stage: dict[str, Any]) -> str:
    return f"{stage['volts']:.1f} V" + (f" / {stage['seconds']:g} s" if stage.get("seconds") is not None else "")
