DOMAIN = "eg4_solar_report"

DEFAULT_NAME = "EG4 Solar Report"

# Monitor Center servers (EG4 runs on the Luxpower WManage platform)
SERVERS = {
    "us_eg4": "https://monitor.eg4electronics.com",
    "us_lux": "https://us.luxpowertek.com",
    "eu_lux": "https://eu.luxpowertek.com",
}
DEFAULT_SERVER = "us_eg4"

# Config entry data
CONF_SERVER = "server"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PLANT_ID = "plant_id"
CONF_PLANT_NAME = "plant_name"
CONF_INVERTERS = "inverters"
CONF_SYSTEM_TYPE = "system_type"
CONF_PARALLEL_COUNT = "parallel_count"
CONF_GRIDBOSS = "gridboss"
CONF_BATTERY_KWH = "battery_kwh"
CONF_PACK_COUNT = "pack_count"
CONF_PACK_DISCHARGE_A = "pack_discharge_a"
CONF_CELL_V_MAX = "cell_v_max"
CONF_ARRAY_NAMES = "array_names"
CONF_MPPT_LIMITS_A = "mppt_limits_a"
CONF_PV_MAX_V = "pv_max_v"
CONF_OUTPUT_CEILING_KW = "output_ceiling_kw"
CONF_IMPORT_RATE = "import_rate"
CONF_EXPORT_CREDIT = "export_credit"
CONF_NOMINAL_VOLTAGE = "nominal_voltage"
CONF_HV_WATCH = "hv_watch"
CONF_HV_ACT = "hv_act"
CONF_SERVICE_CHARGE = "service_charge"
CONF_UTILITY_NAME = "utility_name"

SYSTEM_TYPES = ["FlexBOSS21", "FlexBOSS18", "18kPV", "12kPV", "6000XP", "Other"]

DEFAULT_BATTERY_KWH = 0  # 0 = infer from the log
DEFAULT_PACK_COUNT = 4
DEFAULT_PACK_DISCHARGE_A = 200  # BMS discharge limit per pack; 4 packs = 800 A
DEFAULT_CELL_V_MAX = 3.65  # LiFePO4
DEFAULT_ARRAY_NAMES = "Array 1"

# Inverter limits by system type, used to pre-fill setup. 0 or empty = unknown, so that check is skipped
SYSTEM_PROFILES = {
    "FlexBOSS21": {"mppt_limits_a": "26,26,15", "pv_max_v": 600, "output_ceiling_kw": 16},
}
EMPTY_PROFILE = {"mppt_limits_a": "", "pv_max_v": 0, "output_ceiling_kw": 0}
DEFAULT_NOMINAL_VOLTAGE = 240
DEFAULT_HV_WATCH = 254
DEFAULT_HV_ACT = 264

# Options
OPT_WEEKLY_ENABLED = "weekly_enabled"
OPT_WEEKLY_DAY = "weekly_day"
OPT_WEEKLY_TIME = "weekly_time"
OPT_OUTAGE_ENABLED = "outage_enabled"
OPT_OUTAGE_ENTITY = "outage_entity"
OPT_OUTAGE_DELAY = "outage_delay_minutes"
OPT_NOTIFY_SERVICE = "notify_service"
OPT_NOTIFY_SEVERITIES = "notify_severities"
OPT_KNOWN_ISSUES = "known_issues"

# Temperature thresholds (°C): sensor class -> (watch, act). No published FlexBOSS heatsink derate point was found
# (EG4 docs, pylxpweb); 95/105 leaves room above a 93 °C summer peak that was normal. Editable in options.
TEMP_THRESHOLDS = {
    "heatsink": (95, 105),
    "internal": (70, 80),
    "battery": (45, 55),
    "cell": (45, 55),
}
OPT_TEMP_IMBALANCE = "temp_imbalance"
OPT_TEMP_UNIT = "temp_unit"  # "f" or "c"; defaults to the Home Assistant unit system
DEFAULT_TEMP_IMBALANCE = 3.0

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_WEEKLY_DAY = "sun"
DEFAULT_WEEKLY_TIME = "21:00:00"
DEFAULT_OUTAGE_DELAY = 45

# Report periods
PERIOD_TODAY = "Today"
PERIOD_7_DAYS = "7 days"
PERIODS = [PERIOD_TODAY, PERIOD_7_DAYS]

# Finding severities, mildest first
SEVERITY_OK = "ok"
SEVERITY_INFO = "info"
SEVERITY_WATCH = "watch"
SEVERITY_ACT = "act"
SEVERITIES = [SEVERITY_OK, SEVERITY_INFO, SEVERITY_WATCH, SEVERITY_ACT]

# Report sensor states
VERDICT_HEALTHY = "healthy"
VERDICT_WATCH = "watch"
VERDICT_ACT = "act"
VERDICT_ERROR = "error"

EVENT_REPORT_GENERATED = "eg4_solar_report_generated"
SERVICE_GENERATE = "generate"
