"""Constants for the RecTeq integration.

Most of these mirror what we extracted from the decompiled `com.ym.rectecgrill`
Android app. They are constants of the *app*, identical for every install —
not user secrets — so embedding them is fine and is what makes turnkey login
possible (the user only needs their own RecTeq account credentials).
"""

DOMAIN = "recteq"

# ── OEM Tuya API (RecTeq's branded backend) ────────────────────────────────
API_BASE = "https://a1.tuyaus.com"
API_PATH = "/api.json"

# These four constants combine into the HMAC signing key used for every
# request to the OEM API. Format:
#   {packageName}_{certSHA256_colon_upper}_{bmpSecret}_{appSecret}
PACKAGE_NAME = "com.ym.rectecgrill"
CERT_SHA256 = (
    "A9:84:0A:7A:2A:D8:3A:AE:27:60:4F:CD:C6:B1:8C:3D:"
    "4D:99:A3:E2:AB:5A:56:F6:8C:A0:08:BD:FC:19:A7:DF"
)
BMP_SECRET = "w7fcnn4p5ksyxyyrmctpxjqqk9fevmyh"
OEM_ACCESS_ID = "njwdwq5wmu8d3qc8ytvm"  # used as `clientId` in URL params
OEM_ACCESS_SECRET = "cyc74gcu73dpqsryh4aqn8pqe9n5e5nm"
PARTNER_IDENTITY = "p1026169"
CH_KEY = "babb361a"

HMAC_KEY = (
    f"{PACKAGE_NAME}_{CERT_SHA256}_{BMP_SECRET}_{OEM_ACCESS_SECRET}"
)

# Identifiers presented to the API. APP_VERSION/SDK_VERSION mirror what the
# Android app sent during the captures we recorded — Tuya rejects requests
# whose tuple doesn't look like a real app build.
APP_VERSION = "2.2.4"
SDK_VERSION = "5.8.0"
DEVICE_CORE_VERSION = "5.5.0"
TTID = "android"
LANG = "en_US"
OS_SYSTEM = "16"
PLATFORM = "sdk_gphone64_x86_64"

# Keys included in the canonical signing string (alphabetical order). Any
# other request fields are excluded from the HMAC input. Mirrors the
# whitelist baked into the OEM SDK.
SIGN_WHITELIST = {
    "a", "v", "lat", "lon", "lang", "deviceId", "appVersion", "ttid",
    "isH5", "h5Token", "os", "clientId", "postData", "time", "requestId",
    "et", "n4h5", "sid", "chKey", "sp",
}

# ── Local Tuya protocol ────────────────────────────────────────────────────
PROTOCOL_VERSION = 3.4
DEFAULT_SCAN_INTERVAL = 1  # seconds — the BBQ posts updates this often
LOCAL_PORT = 6668

# ── Config-entry data keys ─────────────────────────────────────────────────
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_HOST = "host"
CONF_DEVICE_NAME = "device_name"
CONF_PRODUCT_ID = "product_id"

# ── DualFire 2000 DP map ───────────────────────────────────────────────────
# DP -> entity descriptor. Used by every platform module. New RecTeq models
# get a new map here; product_id from the cloud API picks the right one.
#
# Each entry: (platform, slug, friendly_name, extra_kwargs)
# - slug: stable suffix used to derive entity_id (switch.bbq_<slug>)
# - extra_kwargs: platform-specific config (min/max for numbers, etc.)

DUALFIRE_DPS = [
    # (dp, platform, slug, friendly, extras)
    (101, "switch", "left", "Left Burner", {}),
    (102, "switch", "right", "Right Burner", {}),
    (103, "number", "left_setpoint", "Left Setpoint",
     {"min": 200, "max": 700, "step": 25, "unit": "°F", "icon": "mdi:thermometer-chevron-up"}),
    (104, "number", "right_setpoint", "Right Setpoint",
     {"min": 180, "max": 700, "step": 5, "unit": "°F", "icon": "mdi:thermometer-chevron-up"}),
    (105, "sensor", "left_temp", "Left Pit Temp",
     {"unit": "°F", "device_class": "temperature"}),
    (106, "sensor", "right_temp", "Right Pit Temp",
     {"unit": "°F", "device_class": "temperature"}),
    (107, "sensor", "probe_a", "Probe A",
     {"unit": "°F", "device_class": "temperature"}),
    (108, "sensor", "probe_b", "Probe B",
     {"unit": "°F", "device_class": "temperature"}),
    (109, "sensor", "probe_c", "Probe C",
     {"unit": "°F", "device_class": "temperature"}),
    (110, "sensor", "probe_d", "Probe D",
     {"unit": "°F", "device_class": "temperature"}),
    (111, "number", "left_min_feed", "Left Min Feed Rate",
     {"min": 5, "max": 250, "step": 5, "unit": "%"}),
    (112, "number", "right_min_feed", "Right Min Feed Rate",
     {"min": 5, "max": 250, "step": 5, "unit": "%"}),
    (113, "number", "left_calibration", "Left Temp Calibration",
     {"min": -25, "max": 25, "step": 1, "unit": "°F"}),
    (114, "number", "right_calibration", "Right Temp Calibration",
     {"min": -25, "max": 25, "step": 1, "unit": "°F"}),
    (115, "binary_sensor", "left_error_1", "Left Error 1", {"device_class": "problem"}),
    (116, "binary_sensor", "right_error_1", "Right Error 1", {"device_class": "problem"}),
    (117, "binary_sensor", "left_error_2", "Left Error 2", {"device_class": "problem"}),
    (118, "binary_sensor", "right_error_2", "Right Error 2", {"device_class": "problem"}),
    (119, "binary_sensor", "left_error_3", "Left Error 3", {"device_class": "problem"}),
    (120, "binary_sensor", "right_error_3", "Right Error 3", {"device_class": "problem"}),
]

# ── RT-B380X Bullseye Deluxe DP map ────────────────────────────────────────
# Single-zone pellet grill, protocol 3.4. Read live from a B380X on 2026-11-08:
#   {'2': True, '101': 225, '102': 221, '103': 0, '104': 20, '105': 0,
#    '106': False, '107': False, '108': False}
# 2/101/102 match the recteq app. 103-108 follow the DualFire layout shifted
# down (one probe, one feed rate, one calibration, three error flags).

BULLSEYE_DELUXE_DPS = [
    (2, "switch", "power", "Power", {}),
    (101, "number", "setpoint", "Setpoint",
     {"min": 200, "max": 750, "step": 5, "unit": "°F", "icon": "mdi:thermometer-chevron-up"}),
    (102, "sensor", "pit_temp", "Pit Temp",
     {"unit": "°F", "device_class": "temperature"}),
    (103, "sensor", "probe_a", "Probe A",
     {"unit": "°F", "device_class": "temperature"}),
    (104, "number", "min_feed", "Min Feed Rate",
     {"min": 5, "max": 250, "step": 5, "unit": "%"}),
    (105, "number", "calibration", "Temp Calibration",
     {"min": -25, "max": 25, "step": 1, "unit": "°F"}),
    (106, "binary_sensor", "error_1", "Error 1", {"device_class": "problem"}),
    (107, "binary_sensor", "error_2", "Error 2", {"device_class": "problem"}),
    (108, "binary_sensor", "error_3", "Error 3", {"device_class": "problem"}),
]

# Product ID → DP map (cloud API tells us which model we're talking to).
# When new RecTeq models surface, add their DUALFIRE_DPS-equivalent here.
DUALFIRE_PRODUCT_ID = "q5utybemjsoh72nx"
PRODUCT_DP_MAPS = {
    DUALFIRE_PRODUCT_ID: DUALFIRE_DPS,       # DualFire 2000
    "fasfaumc9mykaws3": BULLSEYE_DELUXE_DPS,  # RT-B380X Bullseye Deluxe
}


def dp_map_for(entry_data: dict) -> list:
    """DP map for a config entry. Entries created before the product id was
    stored are all DualFire 2000s (the only model supported then)."""
    return PRODUCT_DP_MAPS.get(entry_data.get(CONF_PRODUCT_ID), DUALFIRE_DPS)

PLATFORMS = ["switch", "sensor", "number", "binary_sensor"]
