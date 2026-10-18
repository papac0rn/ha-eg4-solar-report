"""Read system facts from the EG4 Web Monitor integration's entities, when it is installed.

Those entities come straight from the BMS and inverter settings, so they beat both the Monitor Center lookup
and inference from the log. Entity ids follow that integration's naming, keyed by the inverter serial.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant

# Nominal voltage of a 16-cell LiFePO4 pack, for Ah -> kWh
NOMINAL_PACK_V = 51.2


def _number(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _find(hass: HomeAssistant, domain: str, serial: str, suffix: str) -> float | None:
    """First entity in `domain` whose id contains the serial and ends with `suffix`."""
    key = serial.lower()
    for state in hass.states.async_all(domain):
        if key in state.entity_id and state.entity_id.endswith(suffix):
            value = _number(hass, state.entity_id)
            if value is not None:
                return value
    return None


def battery_bank(hass: HomeAssistant, serial: str) -> dict[str, float | None] | None:
    """Full capacity (Ah), pack count and kWh from the battery-bank sensors, or None if they aren't there."""
    ah = _find(hass, "sensor", serial, "_battery_bank_full_capacity") or _find(
        hass, "sensor", serial, "_battery_bank_max_capacity"
    )
    packs = _find(hass, "sensor", serial, "_battery_count")
    if not ah and not packs:
        return None
    return {
        "ah": ah,
        "packs": int(packs) if packs else None,
        "kwh": round(ah * NOMINAL_PACK_V / 1000, 1) if ah else None,
        "source": "EG4 Web Monitor integration",
    }


def off_grid_cutoff(hass: HomeAssistant, serial: str) -> float | None:
    """The inverter's off-grid SOC cut-off, how low the bank goes during an outage."""
    return _find(hass, "number", serial, "_off_grid_soc_cut_off")


def firmware(hass: HomeAssistant, serial: str) -> str | None:
    """The inverter firmware version from the EG4 Web Monitor integration, e.g. FAAB-2727."""
    key = serial.lower()
    for state in hass.states.async_all("sensor"):
        if key in state.entity_id and state.entity_id.endswith("_firmware_version"):
            if state.state not in ("unknown", "unavailable", ""):
                return state.state
    return None


def soc_floor(hass: HomeAssistant, serial: str) -> float | None:
    """The inverter's on-grid SOC cut-off, the floor the bank discharges to."""
    return _find(hass, "number", serial, "_on_grid_soc_cut_off")