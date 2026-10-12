# EG4 Solar Report for Home Assistant

> **Pre-release (0.1.0, in development).** The analyzer rules are still being ported. Not ready to install yet.

A Home Assistant custom integration that downloads your EG4 inverter's data from the **EG4 Monitor Center** and analyzes it.
You get a plain verdict (**healthy / watch / act**) plus a list of findings, for today or for the past 7 days.

> **Disclaimer:** this uses unofficial access to the EG4 Monitor Center. It is not affiliated with or endorsed by EG4
> Electronics, and it may break if EG4 changes their site.
>
> **Privacy:** your login is stored only in your Home Assistant config entry. Report data stays in your Home Assistant.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repository as an **Integration**.
2. Install **EG4 Solar Report**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → EG4 Solar Report.**

## Setup screens

1. **Account:** server, Monitor Center username and password. These are checked by signing in.
2. **Station:** chosen automatically if your account has only one.
3. **System:** which inverters to include, system type (detected), parallel count, GridBOSS.
4. **Battery and arrays:** usable battery kWh (0 = work it out from the log) and the number of PV strings.
5. **Grid and rates:** import rate, export credit, nominal grid voltage, and the high-voltage Watch/Act thresholds.

**Configure** (later): weekly report day and time, a report after a grid outage (with a delay so EG4's cloud catches up),
a notify service with which severities to push, and known issues to report as Info.

## Entities

| Entity | What it does |
|---|---|
| `select.<station>_report_period` | **Today** or **7 days** |
| `date.<station>_report_end_date` | Last day of the report (resets to today at midnight) |
| `button.<station>_generate_report` | Run the report now |
| `sensor.<station>_report` | Verdict (`healthy` / `watch` / `act` / `error`); counts, findings, key numbers and chart series as attributes |
| `binary_sensor.<station>_action_needed` | On when the verdict is `act` or the report failed |
| `sensor.<station>_last_generated` | When the last report finished |

**Service** `eg4_solar_report.generate` (optional `period`, `end_date`, `config_entry_id`).

**Event** `eg4_solar_report_generated`, with `verdict`, `range`, `counts` and `new_findings`. Use it for your own automations.

## Diagnostics

Settings → Devices & services → EG4 Solar Report → ⋮ → **Download diagnostics**. Your username, password, station and
inverter serials are redacted.

## License

MIT
