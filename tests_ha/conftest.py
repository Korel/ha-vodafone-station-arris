from pathlib import Path

import pytest

from custom_components.vodafone_station_arris.api import build_router_data, parse_login_page

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def router_data():
    login = parse_login_page(
        "var currentSessionId = 'ab';var myIv = 'cd';var mySalt = 'ef';"
        "_ga.isModel6442 = 'true';var nonActiveSession = '1';"
    )
    pages = {p: (FIXTURES / f"{p}_data.php.txt").read_text() for p in ("overview", "status_status", "status_docsis")}
    return build_router_data(login, pages)
