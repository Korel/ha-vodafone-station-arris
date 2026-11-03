"""Load api.py directly: importing the package would pull in Home Assistant."""

import importlib.util
import sys
from pathlib import Path

API_PATH = Path(__file__).parents[1] / "custom_components" / "vodafone_station_arris" / "api.py"
FIXTURES = Path(__file__).parent / "fixtures"

_spec = importlib.util.spec_from_file_location("arris_api", API_PATH)
arris_api = importlib.util.module_from_spec(_spec)
sys.modules["arris_api"] = arris_api
_spec.loader.exec_module(arris_api)
