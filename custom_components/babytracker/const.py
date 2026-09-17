"""Constants for the Baby Tracker integration."""

DOMAIN = "babytracker"

# Cloud sync API of the Baby Tracker (Nighp) app.
BASE_URL = "https://prodapp.babytrackers.com"

# Stored in the config entry so the server keeps our sync cursor between runs.
CONF_DEVICE_UUID = "device_uuid"
