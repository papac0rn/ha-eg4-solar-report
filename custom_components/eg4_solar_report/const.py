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
CONF_ARRAY_COUNT = "array_count"
CONF_IMPORT_RATE = "import_rate"
CONF_EXPORT_CREDIT = "export_credit"
CONF_NOMINAL_VOLTAGE = "nominal_voltage"
CONF_HV_WATCH = "hv_watch"
CONF_HV_ACT = "hv_act"

SYSTEM_TYPES = ["FlexBOSS21", "FlexBOSS18", "18kPV", "12kPV", "6000XP", "Other"]

DEFAULT_BATTERY_KWH = 0  # 0 = infer from the log
DEFAULT_NOMINAL_VOLTAGE = 240
DEFAULT_HV_WATCH = 255
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
