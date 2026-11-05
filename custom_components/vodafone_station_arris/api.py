"""Async client for ARRIS-based Vodafone Stations (TG6442, TG3442).

Deliberately free of Home Assistant imports so it can be tested standalone and
later upstreamed into aiovodafone.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import aiohttp
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

PBKDF2_ITERATIONS = 1000
KEY_BYTES = 16
TAG_BYTES = 16
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
HEADERS = {"X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0"}

# Same endpoint with "Reset" is a factory reset; only this payload may ever be sent.
RESTART_PAYLOAD = {"RestartReset": "Restart"}

# page name -> "mid" the web UI puts in the Referer
DATA_PAGES = {
    "overview": "Overview",
    "status_status": "StatusStatus",
    "status_docsis": "StatusDocsis",
}


class ArrisError(Exception):
    """Base error."""


class CannotConnect(ArrisError):
    """Router unreachable or answered garbage."""


class NotArrisDevice(ArrisError):
    """Host answered, but not with the ARRIS web UI."""


class InvalidAuth(ArrisError):
    """Login rejected; `wait_time` is the router's lockout countdown, if any."""

    def __init__(self, status: str, wait_time: int | None = None) -> None:
        super().__init__(f"login rejected: p_status={status!r} p_waitTime={wait_time!r}")
        self.status = status
        self.wait_time = wait_time


class WebUiBusy(ArrisError):
    """Someone is logged into the web UI; logging in now would kick them out."""


class SessionLost(ArrisError):
    """Our session was taken over mid-read (someone logged in and confirmed the takeover)."""


def derive_key(password: str, salt_hex: str) -> bytes:
    """sjcl.misc.pbkdf2 defaults: HMAC-SHA256."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS, KEY_BYTES
    )


def ccm_encrypt(key: bytes, plaintext: str, iv_hex: str, aad: str) -> str:
    """Return hex(ciphertext || tag), matching the web UI's sjclCCMencrypt."""
    return AESCCM(key, tag_length=TAG_BYTES).encrypt(
        bytes.fromhex(iv_hex), plaintext.encode(), aad.encode()
    ).hex()


def ccm_decrypt(key: bytes, data_hex: str, iv_hex: str, aad: str) -> str:
    return AESCCM(key, tag_length=TAG_BYTES).decrypt(
        bytes.fromhex(iv_hex), bytes.fromhex(data_hex), aad.encode()
    ).decode()


@dataclass(frozen=True, slots=True)
class LoginPage:
    session_id: str
    iv: str
    salt: str
    firmware: str | None
    is_model_6442: bool
    web_ui_busy: bool


def _first(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def parse_login_page(html: str) -> LoginPage:
    session_id = _first(r"var currentSessionId\s*=\s*'([0-9a-fA-F]+)'", html)
    iv = _first(r"var myIv\s*=\s*'([0-9a-fA-F]+)'", html)
    salt = _first(r"var mySalt\s*=\s*'([0-9a-fA-F]+)'", html)
    if not (session_id and iv and salt):
        raise NotArrisDevice("start page lacks currentSessionId/myIv/mySalt")
    return LoginPage(
        session_id=session_id,
        iv=iv,
        salt=salt,
        firmware=_first(r"_ga\.swVersion\s*=\s*'([^']*)'", html),
        is_model_6442=_first(r"_ga\.isModel6442\s*=\s*'([^']*)'", html) == "true",
        # '1' when no session is active, '' while someone is logged in.
        web_ui_busy=_first(r"var nonActiveSession\s*=\s*'([^']*)'", html) != "1",
    )


_STRING_VAR = re.compile(r"\b(js_\w+|_ga\.\w+)\s*=\s*'([^']*)'\s*;")
_JSON_VAR = re.compile(r"\b(json_\w+)\s*=\s*")


def parse_js_vars(text: str) -> dict[str, Any]:
    """Extract `js_x = '...'`, `_ga.x = '...'` and `json_x = <json>` assignments."""
    result: dict[str, Any] = {m.group(1): m.group(2) for m in _STRING_VAR.finditer(text)}
    decoder = json.JSONDecoder()
    for m in _JSON_VAR.finditer(text):
        try:
            value, _ = decoder.raw_decode(text, m.end())
        except ValueError:
            continue
        result[m.group(1)] = value
    return result


@dataclass(frozen=True, slots=True)
class ConnectedDevice:
    mac: str
    name: str
    ip_address: str | None
    connection: str  # "lan", "wifi" or "guest_wifi"
    interface: str | None
    link_rate_mbps: float | None


@dataclass(frozen=True, slots=True)
class DocsisChannel:
    channel_id: str
    channel_type: str
    modulation: str
    frequency: str
    power_dbmv: float | None
    snr_db: float | None
    locked: bool


@dataclass(slots=True)
class RouterData:
    serial_number: str | None
    firmware: str | None
    hardware_version: str | None
    model: str
    uptime: timedelta | None
    wan_ipv4: str | None
    wan_ipv6: str | None
    modem_status: str | None
    wifi_enabled: bool | None
    guest_wifi_enabled: bool | None
    devices: dict[str, ConnectedDevice] = field(default_factory=dict)
    downstream: list[DocsisChannel] = field(default_factory=list)
    upstream: list[DocsisChannel] = field(default_factory=list)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() in ("true", "on", "1")


def parse_uptime(value: str | None) -> timedelta | None:
    """status_status reports uptime as 'DD,HH,MM'."""
    if not value:
        return None
    try:
        days, hours, minutes = (int(p) for p in value.split(","))
    except ValueError:
        return None
    return timedelta(days=days, hours=hours, minutes=minutes)


def parse_devices(overview: dict[str, Any]) -> dict[str, ConnectedDevice]:
    devices: dict[str, ConnectedDevice] = {}
    for var, connection in (
        ("json_lanAttachedDevice", "lan"),
        ("json_primaryWlanAttachedDevice", "wifi"),
        ("json_guestWlanAttachedDevice", "guest_wifi"),
    ):
        entries = overview.get(var)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            mac = str(entry.get("MAC") or "").lower()
            if not mac or entry.get("Active") is False:
                continue
            devices[mac] = ConnectedDevice(
                mac=mac,
                name=entry.get("HostName") or mac,
                ip_address=entry.get("IPv4") or None,
                connection=connection,
                interface=entry.get("Interface") or None,
                link_rate_mbps=_to_float(entry.get("LinkRate")),
            )
    return devices


def parse_docsis_channels(entries: Any) -> list[DocsisChannel]:
    if not isinstance(entries, list):
        return []
    channels = []
    for entry in entries:
        # PowerLevel is "dBmV/dBµV", e.g. "-5.3/54.7"
        power = str(entry.get("PowerLevel") or "").split("/")[0]
        channels.append(
            DocsisChannel(
                channel_id=str(entry.get("ChannelID", "")),
                channel_type=str(entry.get("ChannelType", "")),
                modulation=str(entry.get("Modulation", "")),
                frequency=str(entry.get("Frequency", "")),
                power_dbmv=_to_float(power),
                snr_db=_to_float(entry.get("SNRLevel")),
                locked=str(entry.get("LockStatus", "")).lower() in ("locked", "operate"),
            )
        )
    return channels


def build_router_data(login: LoginPage, pages: dict[str, str]) -> RouterData:
    overview = parse_js_vars(pages.get("overview", ""))
    status = parse_js_vars(pages.get("status_status", ""))
    docsis = parse_js_vars(pages.get("status_docsis", ""))
    return RouterData(
        serial_number=status.get("js_SerialNumber") or None,
        firmware=status.get("js_FWVersion") or login.firmware,
        hardware_version=status.get("js_HWTypeVersion") or None,
        model="TG6442" if login.is_model_6442 else "Vodafone Station (ARRIS)",
        uptime=parse_uptime(status.get("js_UptimeSinceReboot")),
        wan_ipv4=status.get("js_ipv4addr") or None,
        wan_ipv6=status.get("js_ipv6addr") or None,
        modem_status=overview.get("_ga.modemConnectionStatus") or None,
        wifi_enabled=_bool(overview.get("js_wifiEnable")),
        guest_wifi_enabled=_bool(overview.get("js_guestWifiEnable")),
        devices=parse_devices(overview),
        downstream=parse_docsis_channels(docsis.get("json_dsData")),
        upstream=parse_docsis_channels(docsis.get("json_usData")),
    )


class ArrisStationClient:
    """One `fetch()` = check busy, log in, read, log out; no session is held between polls."""

    def __init__(
        self, host: str, username: str, password: str, session: aiohttp.ClientSession
    ) -> None:
        self.base_url = f"http://{host}"
        self._username = username
        self._password = password
        self._session = session

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[int, str]:
        headers = {**HEADERS, **kwargs.pop("headers", {})}
        try:
            async with self._session.request(
                method,
                f"{self.base_url}/{path}",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                **kwargs,
            ) as resp:
                return resp.status, await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"{method} /{path}: {err!r}") from err

    async def probe(self) -> LoginPage:
        """Unauthenticated read of the start page; also tells whether the web UI is in use."""
        status, html = await self._request("GET", "")
        if status != 200:
            raise CannotConnect(f"start page returned HTTP {status}")
        return parse_login_page(html)

    async def _login(self, page: LoginPage) -> str:
        key = derive_key(self._password, page.salt)
        # Byte-identical to the web UI's string concatenation (no JSON escaping).
        js_data = '{"Password": "' + self._password + '", "Nonce": "' + page.session_id + '"}'
        payload = {
            "EncryptData": ccm_encrypt(key, js_data, page.iv, "loginPassword"),
            "Name": self._username,
            "AuthData": "loginPassword",
        }
        status, text = await self._request("POST", "php/ajaxSet_Password.php", json=payload)
        try:
            resp = json.loads(text)
        except ValueError as err:
            raise CannotConnect(f"login returned HTTP {status}, not JSON") from err
        p_status = str(resp.get("p_status", ""))
        if not (p_status.find("Match") > 0 or p_status == "Default"):
            raise InvalidAuth(p_status, resp.get("p_waitTime"))
        try:
            return ccm_decrypt(key, resp["encryptData"], page.iv, "nonce")
        except (KeyError, ValueError, InvalidTag) as err:
            raise CannotConnect("could not decrypt the CSRF nonce") from err

    async def _activate_session(self, csrf: str) -> None:
        # Mirrors the browser's post-login reload, which POSTs ajaxSet_Session.php.
        await self._request("GET", "", headers={"csrfNonce": csrf})
        _, text = await self._request(
            "POST",
            "php/ajaxSet_Session.php",
            headers={"csrfNonce": csrf, "Referer": f"{self.base_url}/"},
        )
        if '"LoginStatus":"yes"' not in text.replace(" ", ""):
            raise SessionLost(f"ajaxSet_Session answered {text.strip()[:100]!r}")

    async def _read_page(self, page: str, csrf: str) -> str:
        status, text = await self._request(
            "GET",
            f"php/{page}_data.php",
            headers={"csrfNonce": csrf, "Referer": f"{self.base_url}/?{page}&mid={DATA_PAGES[page]}"},
        )
        if status in (400, 401) or "SESSION_LOST" in text:
            raise SessionLost(f"{page}: HTTP {status}")
        if status != 200:
            raise CannotConnect(f"{page}: HTTP {status}")
        return text

    async def _logout(self, csrf: str) -> None:
        try:
            await self._request("POST", "php/logout.php", headers={"csrfNonce": csrf})
        except CannotConnect:
            pass

    async def fetch(self) -> RouterData:
        self._session.cookie_jar.clear()
        page = await self.probe()
        if page.web_ui_busy:
            raise WebUiBusy
        csrf = await self._login(page)
        taken_over = False
        try:
            await self._activate_session(csrf)
            pages = {name: await self._read_page(name, csrf) for name in DATA_PAGES}
        except SessionLost:
            # The session is someone else's now; logging out might end theirs.
            taken_over = True
            raise
        finally:
            if not taken_over:
                await self._logout(csrf)
            self._session.cookie_jar.clear()
        return build_router_data(page, pages)

    async def restart(self) -> None:
        """Reboot the router. Proceeds even if the web UI is in use: a reboot ends that session anyway."""
        self._session.cookie_jar.clear()
        page = await self.probe()
        csrf = await self._login(page)
        try:
            await self._activate_session(csrf)
            status, text = await self._request(
                "POST",
                "php/ajaxSet_status_restart.php",
                json=RESTART_PAYLOAD,
                headers={"csrfNonce": csrf, "Referer": f"{self.base_url}/?status_restart&mid=StatusRestart"},
            )
            if status in (400, 401) or "SESSION_LOST" in text:
                raise SessionLost(f"restart: HTTP {status}")
            if status != 200:
                raise CannotConnect(f"restart: HTTP {status}")
        finally:
            # No logout: the router is going down, and after a takeover it could end someone else's session.
            self._session.cookie_jar.clear()
