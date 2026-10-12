"""Inverter fault/warning and BMS code table, with known failure signatures.

Pure Python with no Home Assistant imports. Every entry names its source:
- "pylxpweb": the code name, from pylxpweb's constants/fault_codes.py (MIT), the map the EG4 Web Monitor
  integration uses. Inverter codes are bitfields (bit n = E0nn / W0nn).
- "report": the plain-language meaning, causes, severity and advice, written for this report.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeInfo:
    code: str
    name: str
    meaning: str
    causes: str
    severity: str  # watch or act when the code persists
    action: str
    source: str = "pylxpweb (name); report (guidance)"


def _w(bit: int, name: str, meaning: str, causes: str, severity: str, action: str) -> CodeInfo:
    return CodeInfo(f"W{bit:03d}", name, meaning, causes, severity, action)


def _e(bit: int, name: str, meaning: str, causes: str, severity: str, action: str) -> CodeInfo:
    return CodeInfo(f"E{bit:03d}", name, meaning, causes, severity, action)


_SUPPORT = "Note the time and contact EG4 support with the code if it persists or repeats."

WARNING_CODES: dict[int, CodeInfo] = {
    0: _w(0, "Battery communication failed", "The inverter lost the BMS link.", "Loose or wrong battery comms cable, BMS asleep, a pack restarting.", "act", "Check the battery communication cable at both ends and the BMS protocol setting."),
    1: _w(1, "AFCI communication failure", "The arc-fault detector stopped answering.", "AFCI board fault or firmware.", "watch", _SUPPORT),
    2: _w(2, "Battery low temperature", "The battery is too cold to charge at full rate.", "Cold garage or unheated enclosure.", "watch", "Keep the battery above freezing; charging is limited until it warms."),
    3: _w(3, "Meter communication failed", "The CT/meter link dropped.", "Meter cable, meter power, or meter address setting.", "watch", "Check the meter or CT wiring and its communication cable."),
    4: _w(4, "Battery cannot be charged/discharged", "The BMS blocked charge or discharge.", "A pack fault, protection event or a pack dropping off the bus.", "act", "Check each pack's status and the per-pack view; with W027 this is the pack-dropout signature."),
    5: _w(5, "Automated test failed", "A grid-code self test failed.", "Grid conditions during the test or a setting mismatch.", "watch", _SUPPORT),
    6: _w(6, "RSD Active", "Rapid shutdown is engaged.", "The RSD switch was pressed or its signal was lost.", "act", "Check the rapid-shutdown switch and wiring."),
    7: _w(7, "LCD communication failure", "The front panel stopped answering.", "Display cable or board.", "watch", _SUPPORT),
    8: _w(8, "Software version mismatch", "Firmware parts don't match.", "An interrupted or partial firmware update.", "watch", "Finish the firmware update for all boards."),
    9: _w(9, "Fan is stuck", "A cooling fan isn't turning.", "Debris, a failed fan or its connector.", "act", "Check and clean the fans; a stuck fan leads to heat derating."),
    10: _w(10, "Grid overload", "Load exceeded what the grid side can pass.", "Large loads at once, often with EV charging.", "watch", "Stagger big loads or lower the EV charge rate."),
    11: _w(11, "Number of parallel secondaries exceeds limit", "Too many units are set as parallel secondaries.", "Parallel setup error.", "act", "Check the parallel settings on every unit."),
    12: _w(12, "Battery reverse MOS abnormal", "A battery-side switch is abnormal.", "Internal fault.", "act", _SUPPORT),
    13: _w(13, "Radiator temperature out of range", "A heatsink is too hot or its sensor reads wrong.", "Blocked airflow, a failed fan or high ambient temperature.", "act", "Clear the air path and check the fans."),
    14: _w(14, "Multiple primary units set in parallel system", "More than one unit is set as primary.", "Parallel setup error.", "act", "Set exactly one primary."),
    15: _w(15, "Battery reverse", "Battery polarity is reversed.", "Wiring error.", "act", "Shut down and correct the battery wiring before running."),
    16: _w(16, "No grid connection", "The inverter sees no grid.", "Utility outage, open breaker, or a recloser operation.", "watch", "Brief ones with a grid event are normal; repeated ones need a look at the grid breaker and connections."),
    17: _w(17, "Grid voltage out of range", "Grid voltage left the allowed window.", "Utility voltage swings, high voltage while exporting, or a loose neutral.", "watch", "If it repeats, check the over-voltage setting and ask the utility about the line voltage."),
    18: _w(18, "Grid frequency out of range", "Grid frequency left the allowed window.", "Utility frequency events or generator power.", "watch", "Brief ones during grid events are normal."),
    20: _w(20, "Insulation resistance low", "PV insulation to ground is low.", "Wet connectors, damaged PV cable or a failing module.", "act", "Inspect PV connectors and cables for moisture or damage."),
    21: _w(21, "Leakage current too high", "Ground leakage current is high.", "PV insulation fault or moisture.", "act", "Inspect the PV wiring and connectors."),
    22: _w(22, "DCI exceeded standard", "DC injection into the grid is too high.", "Internal measurement or power stage issue.", "act", _SUPPORT),
    23: _w(23, "PV short circuit", "A PV input looks shorted.", "PV wiring fault.", "act", "Isolate the PV strings and inspect the wiring."),
    25: _w(25, "Battery overvoltage", "Battery voltage is too high.", "Charge settings or BMS problem.", "act", "Check charge voltage settings and the BMS."),
    26: _w(26, "Battery undervoltage", "Battery voltage is too low.", "Deep discharge or a pack offline.", "act", "Recharge, and check that all packs are online."),
    27: _w(27, "Battery open circuit", "The inverter sees no battery voltage.", "Battery breaker open, a pack dropping out, loose DC cable.", "act", "Check the battery breaker, DC cables and lug torque; with W004 this is the pack-dropout signature."),
    28: _w(28, "EPS overload", "Backup output is overloaded.", "Too much load on the backup panel during an outage.", "watch", "Shed load on the backup panel."),
    29: _w(29, "EPS voltage high", "Backup output voltage is high.", "Internal regulation or light load.", "watch", _SUPPORT),
    30: _w(30, "Meter reversed", "The meter or CT reads backwards.", "CT installed backwards or swapped.", "watch", "Flip or swap the CTs per the manual."),
    31: _w(31, "DCV exceeded standard", "DC voltage on the AC side is too high.", "Internal measurement issue.", "act", _SUPPORT),
}

FAULT_CODES: dict[int, CodeInfo] = {
    0: _e(0, "Internal communication failure 1", "Internal boards stopped talking.", "Internal fault or firmware.", "act", _SUPPORT),
    1: _e(1, "Model fault", "Model settings are inconsistent.", "Firmware or configuration.", "act", _SUPPORT),
    8: _e(8, "Parallel CAN communication failure", "Parallel units lost their link.", "Parallel cable or termination.", "act", "Check the parallel communication cables and termination."),
    9: _e(9, "The host is missing", "The primary unit isn't seen.", "Parallel cable or the primary is off.", "act", "Check the primary unit and parallel cables."),
    10: _e(10, "Inconsistent rated power", "Parallel units differ in rating.", "Mixed models in parallel.", "act", "Use matching units in parallel."),
    11: _e(11, "Inconsistent AC or safety settings", "Parallel units have different grid settings.", "Settings mismatch.", "act", "Match the grid and safety settings on every unit."),
    12: _e(12, "UPS short circuit", "The backup output is shorted.", "Fault on the backup panel wiring or a load.", "act", "Find and clear the short on the backup circuits."),
    13: _e(13, "UPS reverse current", "Current flowed back into the backup output.", "Wiring error or generator backfeed.", "act", "Check the backup wiring and any generator connection."),
    14: _e(14, "BUS short circuit", "The internal DC bus is shorted.", "Internal fault.", "act", _SUPPORT),
    15: _e(15, "Abnormal phase in three-phase system", "Phase sequence is wrong.", "Wiring error.", "act", "Correct the phase wiring."),
    16: _e(16, "Relay failure", "A grid relay failed its check.", "Relay wear or internal fault.", "act", _SUPPORT),
    17: _e(17, "Internal communication failure 2", "Internal boards stopped talking.", "Internal fault or firmware.", "act", _SUPPORT),
    18: _e(18, "Internal communication failure 3", "Internal boards stopped talking.", "Internal fault or firmware.", "act", _SUPPORT),
    19: _e(19, "BUS overvoltage", "The internal DC bus voltage is too high.", "Grid or PV transients.", "act", _SUPPORT),
    20: _e(20, "EPS connection fault", "Backup output wiring is wrong.", "Wiring error.", "act", "Check the backup output wiring."),
    21: _e(21, "PV overvoltage", "PV input voltage is too high.", "Too many panels in a string, cold weather.", "act", "Check the string's cold-weather voltage against the input limit."),
    22: _e(22, "Overcurrent protection", "Output current tripped protection.", "Overload or short.", "act", "Check for overloads or shorts on the output."),
    23: _e(23, "Neutral fault", "The neutral connection is bad.", "Loose or missing neutral.", "act", "Check the neutral connection; this is a safety issue."),
    24: _e(24, "PV short circuit", "A PV input is shorted.", "PV wiring fault.", "act", "Isolate the strings and inspect the wiring."),
    25: _e(25, "Heatsink temperature out of range", "A heatsink overheated.", "Blocked airflow, failed fan, high ambient.", "act", "Clear the air path and check the fans."),
    26: _e(26, "Internal failure", "General internal fault.", "Internal fault.", "act", _SUPPORT),
    27: _e(27, "Consistency failure", "Redundant measurements disagree.", "Sensor or internal fault.", "act", _SUPPORT),
    28: _e(28, "Inconsistent generator connection", "Generator input settings don't match wiring.", "Generator setup.", "act", "Check the generator input settings and wiring."),
    29: _e(29, "Parallel sync signal loss", "Parallel units lost sync.", "Parallel cable.", "act", "Check the parallel sync cables."),
    31: _e(31, "Internal communication failure 4", "Internal boards stopped talking.", "Internal fault or firmware.", "act", _SUPPORT),
}

# BMS event values are enumerated, not bitfields (pylxpweb BMS_FAULT_CODES)
BMS_CODES: dict[int, str] = {
    0x01: "Cell over-voltage protection",
    0x02: "Cell under-voltage protection",
    0x03: "Pack overvoltage",
    0x04: "Pack undervoltage",
    0x05: "Charging over-temperature protection",
    0x06: "Charging under-temperature protection",
    0x07: "Discharging over-temperature protection",
    0x08: "Low temperature protection",
    0x09: "Charging overcurrent",
    0x0A: "Discharging overcurrent",
    0x0B: "Short circuit",
    0x0C: "MOSFET over-temperature",
    0x0D: "Cell unbalance",
    0x0E: "Over-capacity",
}


@dataclass(frozen=True)
class Signature:
    id: str
    name: str
    bits: tuple[int, ...]  # warning bits
    need_all: bool
    meaning: str


SIGNATURES: tuple[Signature, ...] = (
    Signature("transient_grid_failure", "Transient grid failure (W016-W018)", (16, 17, 18), False,
              "The grid-loss, voltage and frequency warnings together are the pattern of a transient grid failure."),
    Signature("pack_dropout", "Pack dropout (W004 + W027)", (4, 27), True,
              "Battery blocked plus battery open circuit together are the pattern of a pack dropping off the bus."),
)


def lookup(kind: str, bit: int) -> CodeInfo | None:
    return (WARNING_CODES if kind == "warning" else FAULT_CODES).get(bit)


def label(kind: str, bit: int) -> str:
    return f"{'W' if kind == 'warning' else 'E'}{bit:03d}"
