from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from . import ha_eg4
from .api import Eg4AuthError, Eg4Error, Eg4MonitorClient
from .const import (
    CONF_ARRAY_NAMES,
    CONF_BATTERY_KWH,
    CONF_CELL_V_MAX,
    CONF_EXPORT_CREDIT,
    CONF_GRIDBOSS,
    CONF_HV_ACT,
    CONF_HV_WATCH,
    CONF_IMPORT_RATE,
    CONF_INVERTERS,
    CONF_MPPT_LIMITS_A,
    CONF_NOMINAL_VOLTAGE,
    CONF_OUTPUT_CEILING_KW,
    CONF_PACK_COUNT,
    CONF_PACK_DISCHARGE_A,
    CONF_PARALLEL_COUNT,
    CONF_PASSWORD,
    CONF_PLANT_ID,
    CONF_PLANT_NAME,
    CONF_PV_MAX_V,
    CONF_SERVER,
    CONF_SERVICE_CHARGE,
    CONF_SYSTEM_TYPE,
    CONF_USERNAME,
    CONF_UTILITY_NAME,
    DEFAULT_ARRAY_NAMES,
    DEFAULT_BATTERY_KWH,
    DEFAULT_CELL_V_MAX,
    DEFAULT_HV_ACT,
    DEFAULT_HV_WATCH,
    DEFAULT_NOMINAL_VOLTAGE,
    DEFAULT_OUTAGE_DELAY,
    DEFAULT_PACK_COUNT,
    DEFAULT_PACK_DISCHARGE_A,
    DEFAULT_SERVER,
    DEFAULT_WEEKLY_DAY,
    DEFAULT_WEEKLY_TIME,
    DOMAIN,
    EMPTY_PROFILE,
    OPT_KNOWN_ISSUES,
    OPT_NOTIFY_SERVICE,
    OPT_NOTIFY_SEVERITIES,
    OPT_OUTAGE_DELAY,
    OPT_OUTAGE_ENABLED,
    OPT_OUTAGE_ENTITY,
    OPT_WEEKLY_DAY,
    OPT_WEEKLY_ENABLED,
    OPT_WEEKLY_TIME,
    SERVERS,
    base_url_for,
    EG4_WEB_MONITOR_DOMAIN,
    CONF_BASE_URL,
    SEVERITY_ACT,
    SEVERITY_INFO,
    SEVERITY_WATCH,
    SYSTEM_PROFILES,
    SYSTEM_TYPES,
    TEMP_THRESHOLDS,
    OPT_TEMP_IMBALANCE,
    OPT_TEMP_UNIT,
    DEFAULT_TEMP_IMBALANCE,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)


def _number(min_v: float, max_v: float, step: float, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=min_v, max=max_v, step=step, mode=NumberSelectorMode.BOX)
    # The selector rejects unit_of_measurement=None, so only pass a real unit
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _guess_system_type(model: str) -> str:
    compact = model.replace(" ", "").lower()
    for stype in SYSTEM_TYPES[:-1]:
        if stype.lower() in compact:
            return stype
    return "Other"


class Eg4SolarReportConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._client: Eg4MonitorClient | None = None
        self._plants: list[dict[str, Any]] = []
        self._inverters: list[dict[str, Any]] = []
        self._battery: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Step 1: the Monitor Center account. Offer the EG4 Web Monitor login when that integration is set up."""
        if self.hass.config_entries.async_entries(EG4_WEB_MONITOR_DOMAIN):
            return self.async_show_menu(step_id="user", menu_options=["reuse_web_monitor", "manual"])
        return await self.async_step_manual()

    async def _async_try_account(self, account: dict[str, Any]) -> str | None:
        """Sign in and list stations; returns an error key, or None when it worked."""
        client = Eg4MonitorClient(
            async_create_clientsession(self.hass),
            base_url_for(account),
            account[CONF_USERNAME],
            account[CONF_PASSWORD],
        )
        try:
            await client.async_login()
            self._plants = await client.async_get_plants()
        except Eg4AuthError as err:
            _LOGGER.warning("EG4 Monitor Center rejected the login: %s", err)
            return "invalid_auth"
        except Eg4Error as err:
            _LOGGER.warning("EG4 Monitor Center login failed: %s", err)
            return "cannot_connect"
        if not self._plants:
            return "no_plants"
        self._client = client
        self._data.update(account)
        return None

    def _explain_rejection(self, typed: dict[str, Any]) -> str:
        """When EG4 Web Monitor's account signs in fine, say how the typed one differs. Never shows either login."""
        entries = self.hass.config_entries.async_entries(EG4_WEB_MONITOR_DOMAIN)
        stored = entries[0].data if entries else {}
        user, password = stored.get(CONF_USERNAME), stored.get(CONF_PASSWORD)
        if not user or not password:
            return "invalid_auth"
        typed_user = str(typed.get(CONF_USERNAME, ""))
        if typed_user.strip() != user:
            same_but_case = typed_user.strip().casefold() == user.strip().casefold()
            _LOGGER.warning("Typed EG4 username differs from EG4 Web Monitor's (%s)",
                            "only in capital letters or spaces" if same_but_case else "a different name")
            return "username_case" if same_but_case else "username_differs"
        if typed.get(CONF_PASSWORD) != password:
            typed_pw = str(typed.get(CONF_PASSWORD, ""))
            close = typed_pw.strip() == password.strip() or typed_pw.casefold() == password.casefold()
            _LOGGER.warning("Typed EG4 password differs from EG4 Web Monitor's (%s)",
                            "only in capitals or spaces" if close else "different")
            return "password_case" if close else "password_differs"
        _LOGGER.warning("Typed EG4 login matches EG4 Web Monitor's but was rejected; the server choice may differ")
        return "same_login_rejected"

    async def async_step_reuse_web_monitor(self, user_input: dict[str, Any] | None = None):
        """Use the account the EG4 Web Monitor integration already signs in with, so nobody retypes it."""
        source = self.hass.config_entries.async_entries(EG4_WEB_MONITOR_DOMAIN)[0].data
        if not source.get(CONF_USERNAME) or not source.get(CONF_PASSWORD):
            return await self.async_step_manual(error="web_monitor_no_login")
        account = {
            CONF_SERVER: DEFAULT_SERVER,
            CONF_USERNAME: source[CONF_USERNAME],
            CONF_PASSWORD: source[CONF_PASSWORD],
        }
        if source.get(CONF_BASE_URL):
            account[CONF_BASE_URL] = source[CONF_BASE_URL]
        error = await self._async_try_account(account)
        if error:
            return await self.async_step_manual(error=error)
        return await self.async_step_plant()

    async def async_step_manual(self, user_input: dict[str, Any] | None = None, error: str | None = None):
        """Type the Monitor Center account in."""
        errors: dict[str, str] = {"base": error} if error else {}
        if user_input is not None:
            if err := await self._async_try_account(user_input):
                errors["base"] = self._explain_rejection(user_input) if err == "invalid_auth" else err
            else:
                return await self.async_step_plant()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERVER, default=DEFAULT_SERVER): SelectSelector(
                        SelectSelectorConfig(
                            options=list(SERVERS), translation_key="server",
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    # The autocomplete hints stop phone keyboards capitalising or autocorrecting the login
                    vol.Required(CONF_USERNAME): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
                    ),
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_plant(self, user_input: dict[str, Any] | None = None):
        """Step 2a: pick the station (skipped when the account has only one)."""
        if user_input is None and len(self._plants) == 1:
            user_input = {CONF_PLANT_ID: self._plants[0]["plant_id"]}
        errors: dict[str, str] = {}
        if user_input is not None:
            plant_id = user_input[CONF_PLANT_ID]
            await self.async_set_unique_id(plant_id)
            self._abort_if_unique_id_configured()
            try:
                self._inverters = await self._client.async_get_inverters(plant_id)
            except Eg4Error as err:
                _LOGGER.warning("EG4 inverter discovery failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not self._inverters:
                    errors["base"] = "no_inverters"
                else:
                    self._data[CONF_PLANT_ID] = plant_id
                    self._data[CONF_PLANT_NAME] = next(
                        (p["name"] for p in self._plants if p["plant_id"] == plant_id), plant_id
                    )
                    return await self.async_step_system()

        return self.async_show_form(
            step_id="plant",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLANT_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=p["plant_id"], label=p["name"])
                                for p in self._plants
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_system(self, user_input: dict[str, Any] | None = None):
        """Step 2b: inverters and system type."""
        if user_input is not None:
            self._data.update(user_input)
            serial = self._data[CONF_INVERTERS][0]
            # The EG4 Web Monitor integration's battery-bank sensors first, then the Monitor Center BMS
            self._battery = ha_eg4.battery_bank(self.hass, serial) or await self._client.async_get_battery(serial) or {}
            if self._battery.get("kwh") and self._battery.get("packs"):
                # Found it, so don't ask. The per-pack limit is learned from the log; all of it is editable in Configure.
                self._data.update({
                    CONF_BATTERY_KWH: self._battery["kwh"],
                    CONF_PACK_COUNT: self._battery["packs"],
                    CONF_PACK_DISCHARGE_A: 0,
                    CONF_CELL_V_MAX: DEFAULT_CELL_V_MAX,
                })
                return await self.async_step_arrays()
            return await self.async_step_battery()

        serials = [i["serial"] for i in self._inverters]
        guessed = _guess_system_type(self._inverters[0]["model"])
        return self.async_show_form(
            step_id="system",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INVERTERS, default=serials): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=i["serial"],
                                    label=f"{i['serial']} {i['model']}".strip(),
                                )
                                for i in self._inverters
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(CONF_SYSTEM_TYPE, default=guessed): SelectSelector(
                        SelectSelectorConfig(options=SYSTEM_TYPES, mode=SelectSelectorMode.DROPDOWN)
                    ),
                    vol.Required(CONF_PARALLEL_COUNT, default=len(serials)): _number(1, 10, 1),
                    vol.Required(CONF_GRIDBOSS, default=False): BooleanSelector(),
                }
            ),
        )

    async def async_step_battery(self, user_input: dict[str, Any] | None = None):
        """Step 3: battery, asked only when neither the EG4 integration nor the BMS reports it."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_arrays()

        bank = self._battery or {}
        kwh_default = bank.get("kwh") or DEFAULT_BATTERY_KWH
        packs_default = bank.get("packs") or DEFAULT_PACK_COUNT
        return self.async_show_form(
            step_id="battery",
            description_placeholders={
                "bms": f"{bank['ah']:g} Ah × 51.2 V = {bank['kwh']:g} kWh, from the {bank['source']}"
                if bank.get("kwh") else "not reported"
            },
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BATTERY_KWH, default=kwh_default): _number(0, 1000, 0.1, "kWh"),
                    vol.Required(CONF_PACK_COUNT, default=packs_default): _number(1, 64, 1),
                    vol.Required(CONF_PACK_DISCHARGE_A, default=0): _number(0, 1000, 1, "A"),
                    vol.Required(CONF_CELL_V_MAX, default=DEFAULT_CELL_V_MAX): _number(2, 5, 0.01, "V"),
                }
            ),
        )

    async def async_step_arrays(self, user_input: dict[str, Any] | None = None):
        """Step 4: PV arrays and inverter limits (pre-filled for known system types)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            names = _split_csv(user_input[CONF_ARRAY_NAMES])
            limits = _split_csv(user_input.get(CONF_MPPT_LIMITS_A, ""))
            if not names:
                errors[CONF_ARRAY_NAMES] = "no_arrays"
            elif limits and (len(limits) != len(names) or not all(_is_number(v) for v in limits)):
                errors[CONF_MPPT_LIMITS_A] = "bad_mppt_limits"
            else:
                user_input[CONF_ARRAY_NAMES] = ",".join(names)
                user_input[CONF_MPPT_LIMITS_A] = ",".join(limits)
                self._data.update(user_input)
                return await self.async_step_grid()

        profile = SYSTEM_PROFILES.get(self._data.get(CONF_SYSTEM_TYPE), EMPTY_PROFILE)
        return self.async_show_form(
            step_id="arrays",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ARRAY_NAMES, default=DEFAULT_ARRAY_NAMES): str,
                    vol.Optional(
                        CONF_MPPT_LIMITS_A, description={"suggested_value": profile["mppt_limits_a"]}
                    ): str,
                    vol.Required(CONF_PV_MAX_V, default=profile["pv_max_v"]): _number(0, 1500, 1, "V"),
                    vol.Required(CONF_OUTPUT_CEILING_KW, default=profile["output_ceiling_kw"]): _number(0, 200, 0.1, "kW"),
                }
            ),
            errors=errors,
        )

    async def async_step_grid(self, user_input: dict[str, Any] | None = None):
        """Step 5: grid and rates."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_PLANT_NAME], data=self._data)

        return self.async_show_form(
            step_id="grid",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IMPORT_RATE, default=0.12): _number(0, 5, 0.0001, "$/kWh"),
                    vol.Required(CONF_EXPORT_CREDIT, default=0.0): _number(0, 5, 0.0001, "$/kWh"),
                    vol.Required(CONF_SERVICE_CHARGE, default=0.0): _number(0, 1000, 0.01, "$/month"),
                    vol.Optional(CONF_UTILITY_NAME): str,
                    vol.Required(CONF_NOMINAL_VOLTAGE, default=DEFAULT_NOMINAL_VOLTAGE): _number(100, 480, 1, "V"),
                    vol.Required(CONF_HV_WATCH, default=DEFAULT_HV_WATCH): _number(100, 500, 1, "V"),
                    vol.Required(CONF_HV_ACT, default=DEFAULT_HV_ACT): _number(100, 500, 1, "V"),
                }
            ),
        )
    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = Eg4MonitorClient(
                async_create_clientsession(self.hass),
                base_url_for(entry.data),
                entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.async_login()
            except Eg4AuthError:
                errors["base"] = "invalid_auth"
            except Eg4Error:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return Eg4SolarReportOptionsFlow()


def _default_unit(hass) -> str:
    return "f" if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else "c"


def _to_unit(c_value: float, unit: str) -> float:
    return round(c_value * 9 / 5 + 32) if unit == "F" else c_value


def _from_unit(value: float, unit: str) -> float:
    return round((value - 32) * 5 / 9, 1) if unit == "F" else value


class Eg4SolarReportOptionsFlow(OptionsFlow):
    """Two steps: report settings and system facts, then temperature thresholds in the chosen unit."""

    def __init__(self) -> None:
        self._opts: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._opts = {**self.config_entry.options, **user_input}
            return await self.async_step_temperatures()

        opts = self.config_entry.options
        data = self.config_entry.data
        schema: dict[Any, Any] = {
            vol.Required(OPT_WEEKLY_ENABLED, default=opts.get(OPT_WEEKLY_ENABLED, False)): BooleanSelector(),
            vol.Required(OPT_WEEKLY_DAY, default=opts.get(OPT_WEEKLY_DAY, DEFAULT_WEEKLY_DAY)): SelectSelector(
                SelectSelectorConfig(options=WEEKDAYS, translation_key="weekday", mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(OPT_WEEKLY_TIME, default=opts.get(OPT_WEEKLY_TIME, DEFAULT_WEEKLY_TIME)): TimeSelector(),
            vol.Required(OPT_OUTAGE_ENABLED, default=opts.get(OPT_OUTAGE_ENABLED, False)): BooleanSelector(),
        }
        outage_key = (
            vol.Optional(OPT_OUTAGE_ENTITY, description={"suggested_value": opts[OPT_OUTAGE_ENTITY]})
            if opts.get(OPT_OUTAGE_ENTITY)
            else vol.Optional(OPT_OUTAGE_ENTITY)
        )
        schema[outage_key] = EntitySelector(EntitySelectorConfig(domain="binary_sensor"))
        schema[vol.Required(OPT_OUTAGE_DELAY, default=opts.get(OPT_OUTAGE_DELAY, DEFAULT_OUTAGE_DELAY))] = _number(0, 240, 1, "min")
        schema[vol.Optional(OPT_NOTIFY_SERVICE, description={"suggested_value": opts.get(OPT_NOTIFY_SERVICE, "")})] = str
        schema[vol.Required(OPT_NOTIFY_SEVERITIES, default=opts.get(OPT_NOTIFY_SEVERITIES, [SEVERITY_ACT]))] = SelectSelector(
            SelectSelectorConfig(
                options=[SEVERITY_ACT, SEVERITY_WATCH, SEVERITY_INFO],
                translation_key="severity",
                multiple=True,
                mode=SelectSelectorMode.LIST,
            )
        )
        schema[vol.Optional(OPT_KNOWN_ISSUES, description={"suggested_value": opts.get(OPT_KNOWN_ISSUES, "")})] = str
        # System facts found at setup, correctable here
        schema[vol.Required(CONF_BATTERY_KWH, default=opts.get(CONF_BATTERY_KWH, data.get(CONF_BATTERY_KWH, 0)))] = _number(0, 1000, 0.1, "kWh")
        schema[vol.Required(CONF_PACK_COUNT, default=opts.get(CONF_PACK_COUNT, data.get(CONF_PACK_COUNT, DEFAULT_PACK_COUNT)))] = _number(1, 64, 1)
        schema[vol.Required(CONF_PACK_DISCHARGE_A, default=opts.get(CONF_PACK_DISCHARGE_A, data.get(CONF_PACK_DISCHARGE_A, 0)))] = _number(0, 1000, 1, "A")
        schema[vol.Required(OPT_TEMP_UNIT, default=opts.get(OPT_TEMP_UNIT, _default_unit(self.hass)))] = SelectSelector(
            SelectSelectorConfig(options=["f", "c"], translation_key="temp_unit", mode=SelectSelectorMode.LIST)
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))

    async def async_step_temperatures(self, user_input: dict[str, Any] | None = None):
        """Thresholds shown and entered in the chosen unit; stored in °C."""
        unit = str(self._opts.get(OPT_TEMP_UNIT, "c")).upper()
        if user_input is not None:
            stored = {
                k: (round(v * 5 / 9, 1) if k == OPT_TEMP_IMBALANCE and unit == "F" else
                    v if k == OPT_TEMP_IMBALANCE else _from_unit(v, unit))
                for k, v in user_input.items()
            }
            return self.async_create_entry(data={**self._opts, **stored})

        opts = self.config_entry.options
        sym = "°F" if unit == "F" else "°C"
        schema: dict[Any, Any] = {}
        for cls, (watch, act) in TEMP_THRESHOLDS.items():
            for level, default in (("watch", watch), ("act", act)):
                key = f"temp_{cls}_{level}"
                current = _to_unit(opts.get(key, default), unit)
                schema[vol.Required(key, default=current)] = _number(-20, 300, 1, sym)
        gap = opts.get(OPT_TEMP_IMBALANCE, DEFAULT_TEMP_IMBALANCE)
        schema[vol.Required(OPT_TEMP_IMBALANCE, default=round(gap * 9 / 5, 1) if unit == "F" else gap)] = _number(0.5, 40, 0.1, sym)
        return self.async_show_form(step_id="temperatures", data_schema=vol.Schema(schema))
