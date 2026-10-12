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
4. **Battery:** usable kWh (0 = work it out from the log), pack count, discharge limit per pack, max cell voltage.
5. **Arrays:** a name per MPPT input, plus the MPPT current limits, max PV voltage and AC output ceiling. These are
   pre-filled for known system types; leave a limit empty or 0 to skip that check.
6. **Grid and rates:** import rate, export credit, monthly service charge, utility name, nominal grid voltage, and the
   high-voltage Watch/Act thresholds (default 254 / 264 V).

**Configure** (later): weekly report day and time, a report after a grid outage (with a delay so EG4's cloud catches up),
a notify service with which severities to push, and known issues to report as Info.

## The 21 checks

Each check is rated **OK**, **Info** (worth knowing), **Watch** (keep an eye on it) or **Act** (needs attention).

| Group | Checks |
|---|---|
| Grid | Outages and blips · Transient-failure signature (W016–W018) · High grid voltage · Low grid voltage · Grid frequency |
| Battery | Pack-dropout signature (W004 + W027) · All packs online · Cell balance · Cell voltage limits · Cell temperature · State of health · Grid carrying load while the battery sits out |
| Inverter | Fault codes · Warning codes · Heatsink temperature · Output ceiling · MPPT current · PV string voltage |
| Arrays | Array balance (weather vs. array problem) |
| Data | Logger gaps · Energy counter cross-check |

The report only sees what the inverter logs. Thresholds such as the 264 V trip point are typical values, so confirm
them against your own inverter settings.

## Entities

| Entity | What it does |
|---|---|
| `select.<station>_report_period` | **Today** or **7 days** |
| `date.<station>_report_end_date` | Last day of the report (resets to today at midnight) |
| `button.<station>_generate_report` | Run the report now |
| `sensor.<station>_report` | Verdict (`healthy` / `watch` / `act` / `error`); counts, findings, key numbers and chart series as attributes |
| `binary_sensor.<station>_action_needed` | On when the verdict is `act` or the report failed |
| `sensor.<station>_last_generated` | When the last report finished |
| `image.<station>_chart_harvest` | Daily harvest by array (stacked columns) |
| `image.<station>_chart_energy` | Daily house load, export and import |
| `image.<station>_chart_pv_ac` | PV total vs. inverter AC output, with the AC ceiling |
| `image.<station>_chart_grid_voltage` | Line voltage with the Watch and trip thresholds |
| `image.<station>_chart_soc` | Battery state of charge, with its floor |
| `image.<station>_chart_cell_voltage` | Highest and lowest cell voltage, with the cell limit |

The charts are drawn by the integration itself as SVG images and redrawn on every run. Show them with the built-in
**Picture entity** card; no custom cards are needed.

**Service** `eg4_solar_report.generate` (optional `period`, `end_date`, `config_entry_id`).

**Event** `eg4_solar_report_generated`, with `verdict`, `range`, `counts` and `new_findings`. Use it for your own automations.

## Diagnostics

Settings → Devices & services → EG4 Solar Report → ⋮ → **Download diagnostics**. Your username, password, station and
inverter serials are redacted.

## License

MIT
