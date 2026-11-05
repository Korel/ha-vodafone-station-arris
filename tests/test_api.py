from datetime import timedelta

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from arris_api import (
    ArrisStationClient,
    InvalidAuth,
    NotArrisDevice,
    SessionLost,
    WebUiBusy,
    build_router_data,
    ccm_decrypt,
    ccm_encrypt,
    derive_key,
    parse_js_vars,
    parse_login_page,
)
from fake_router import FIXTURES, FakeRouter


def test_crypto_matches_sjcl_vectors() -> None:
    # Vectors from vodafone-station-cli's crypto.test.ts (generated with sjcl).
    key = derive_key("test", "c4d0a0c70c3fcac4")
    assert key.hex() == "203c8c0da0606debbdd581d1a1cdb2c8"
    ct = ccm_encrypt(key, "textToEncrypt", "c68af53914949158", "authData")
    assert ct == "8f1ec931fd9f8d89d98cbb60e4a021320e988b9c6ab97b97208639aa72"
    assert ccm_decrypt(key, ct, "c68af53914949158", "authData") == "textToEncrypt"


def test_parse_js_vars() -> None:
    v = parse_js_vars((FIXTURES / "status_status_data.php.txt").read_text())
    assert v["js_SerialNumber"] == "TESTSERIAL0001"
    assert v["js_ethernet_port1_status"] == "Active"
    o = parse_js_vars((FIXTURES / "overview_data.php.txt").read_text())
    assert o["_ga.modemConnectionStatus"] == "DOCSIS Online"
    assert len(o["json_primaryWlanAttachedDevice"]) == 2
    assert "js_lanAttachedDevice" not in o  # unquoted JS expression, not a value


def test_build_router_data() -> None:
    login = parse_login_page(
        "var currentSessionId = 'ab';var myIv = 'cd';var mySalt = 'ef';"
        "_ga.isModel6442 = 'true';var nonActiveSession = '1';"
    )
    pages = {p: (FIXTURES / f"{p}_data.php.txt").read_text() for p in ("overview", "status_status", "status_docsis")}
    data = build_router_data(login, pages)
    assert data.model == "TG6442"
    assert data.serial_number == "TESTSERIAL0001"
    assert data.uptime == timedelta(days=2, hours=3, minutes=4)
    assert data.wifi_enabled is True and data.guest_wifi_enabled is False
    assert sorted(data.devices) == ["02:00:00:00:00:01", "02:00:00:00:00:02", "02:00:00:00:00:04"]
    assert data.devices["02:00:00:00:00:04"].connection == "guest_wifi"
    assert data.devices["02:00:00:00:00:04"].name == "02:00:00:00:00:04"
    assert data.devices["02:00:00:00:00:02"].link_rate_mbps == pytest.approx(864.7)
    assert [c.locked for c in data.downstream] == [True, True, False]
    assert data.downstream[1].power_dbmv == -5.3
    assert data.downstream[2].snr_db is None
    assert [c.power_dbmv for c in data.upstream] == [57.5, 49.8]


def test_busy_detection() -> None:
    base = "var currentSessionId = 'ab';var myIv = 'cd';var mySalt = 'ef';"
    assert parse_login_page(base + "var nonActiveSession = '1';").web_ui_busy is False
    assert parse_login_page(base + "var nonActiveSession = '';").web_ui_busy is True


@pytest.fixture
async def router_and_client():
    async def make(router: FakeRouter, password: str = "secret"):
        server = TestServer(router.app)
        await server.start_server()
        session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        cleanup.append((server, session))
        return ArrisStationClient(f"{server.host}:{server.port}", "admin", password, session)

    cleanup: list = []
    yield make
    for server, session in cleanup:
        await session.close()
        await server.close()


async def test_fetch_logs_in_reads_and_logs_out(router_and_client) -> None:
    router = FakeRouter()
    client = await router_and_client(router)
    data = await client.fetch()
    assert data.serial_number == "TESTSERIAL0001"
    assert len(data.devices) == 3
    assert router.reads == 3
    assert len(router.logouts) == 1
    assert router.active is None  # web UI free again
    await client.fetch()  # second poll works with fresh cookies
    assert router.login_attempts == 2


async def test_busy_web_ui_is_never_logged_into(router_and_client) -> None:
    router = FakeRouter()
    router.active = "browser-session"
    client = await router_and_client(router)
    with pytest.raises(WebUiBusy):
        await client.fetch()
    assert router.login_attempts == 0
    assert router.active == "browser-session"


async def test_wrong_password_tries_once(router_and_client) -> None:
    router = FakeRouter(password="secret")
    client = await router_and_client(router, password="wrong")
    with pytest.raises(InvalidAuth) as exc:
        await client.fetch()
    assert exc.value.wait_time == 1
    assert router.login_attempts == 1


async def test_takeover_mid_read_does_not_log_out(router_and_client) -> None:
    router = FakeRouter()
    router.take_over_after_reads = 1
    client = await router_and_client(router)
    with pytest.raises(SessionLost):
        await client.fetch()
    assert router.logouts == []  # logging out could end the new owner's session
    assert router.active == "someone-else"


async def test_non_arris_host(router_and_client) -> None:
    client = await router_and_client(FakeRouter(arris=False))
    with pytest.raises(NotArrisDevice):
        await client.fetch()


async def test_restart_sends_only_restart(router_and_client) -> None:
    router = FakeRouter()
    client = await router_and_client(router)
    await client.restart()
    # "Reset" on the same endpoint is a factory reset.
    assert router.restart_requests == [{"RestartReset": "Restart"}]
    assert router.login_attempts == 1


async def test_restart_proceeds_while_web_ui_in_use(router_and_client) -> None:
    router = FakeRouter()
    router.active = "browser-session"
    client = await router_and_client(router)
    await client.restart()
    assert router.restart_requests == [{"RestartReset": "Restart"}]


async def test_restart_wrong_password_tries_once(router_and_client) -> None:
    router = FakeRouter(password="secret")
    client = await router_and_client(router, password="wrong")
    with pytest.raises(InvalidAuth):
        await client.restart()
    assert router.login_attempts == 1
    assert router.restart_requests == []


async def test_restart_rejected_raises(router_and_client) -> None:
    router = FakeRouter()
    router.take_over_before_restart = True
    client = await router_and_client(router)
    with pytest.raises(SessionLost):
        await client.restart()
    assert router.restart_requests == []
