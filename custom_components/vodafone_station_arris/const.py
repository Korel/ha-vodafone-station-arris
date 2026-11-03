"""Constants for the ARRIS Vodafone Station integration."""

import logging
from datetime import timedelta

DOMAIN = "vodafone_station_arris"
LOGGER = logging.getLogger(__package__)

DEFAULT_HOST = "192.168.0.1"
DEFAULT_USERNAME = "admin"
# Each poll logs in and out; 60 s keeps the web UI free most of the time.
SCAN_INTERVAL = timedelta(seconds=60)
MANUFACTURER = "ARRIS"
