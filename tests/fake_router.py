"""In-process fake of the ARRIS web UI's login/session protocol."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from aiohttp import web
from cryptography.exceptions import InvalidTag

from arris_api import ccm_decrypt, ccm_encrypt, derive_key

FIXTURES = Path(__file__).parent / "fixtures"
IV = "94df5c6cee6fca76"
SALT = "b1225d443cf1516b"
SESSION_LOST = '<script> alert(xlate("PAGE_OVERVIEW_SESSION_LOST_POPUP_TEXT")); </script>'


class FakeRouter:
    def __init__(self, password: str = "secret", *, arris: bool = True) -> None:
        self.password = password
        self.arris = arris
        self.csrf: dict[str, str] = {}  # PHPSESSID -> csrf nonce of logged-in sessions
        self.active: str | None = None  # the one session the web UI considers active
        self.login_attempts = 0
        self.logouts: list[str] = []
        self.reads = 0
        self.take_over_after_reads: int | None = None
        self.restart_requests: list[dict] = []
        self.take_over_before_restart = False

        self.app = web.Application()
        self.app.router.add_get("/", self.index)
        self.app.router.add_post("/php/ajaxSet_Password.php", self.login)
        self.app.router.add_post("/php/ajaxSet_Session.php", self.activate)
        self.app.router.add_get("/php/{page}_data.php", self.data)
        self.app.router.add_post("/php/logout.php", self.logout)
        self.app.router.add_post("/php/ajaxSet_status_restart.php", self.restart)

    @staticmethod
    def _sid(request: web.Request) -> str | None:
        return request.cookies.get("PHPSESSID")

    def _authed(self, request: web.Request) -> bool:
        sid = self._sid(request)
        return sid is not None and sid == self.active and request.headers.get("csrfNonce") == self.csrf.get(sid)

    async def index(self, request: web.Request) -> web.Response:
        if not self.arris:
            return web.Response(text="<html>some other router</html>", content_type="text/html")
        sid = self._sid(request) or secrets.token_hex(16)
        non_active = "1" if self.active is None else ""
        html = (
            f"var nonActiveSession = '{non_active}';\n"
            f"var currentSessionId = '{sid}';\nvar myIv = '{IV}';\nvar mySalt = '{SALT}';\n"
            "_ga.swVersion = '01.05.069.14.EURO.PC20';\n_ga.isModel6442 = 'true';\n"
        )
        resp = web.Response(text=html, content_type="text/html")
        resp.set_cookie("PHPSESSID", sid, path="/")
        return resp

    async def login(self, request: web.Request) -> web.Response:
        self.login_attempts += 1
        body = await request.json()
        key = derive_key(self.password, SALT)
        try:
            inner = json.loads(ccm_decrypt(key, body["EncryptData"], IV, body["AuthData"]))
        except (InvalidTag, ValueError):
            return web.json_response({"p_status": "Lockout", "p_waitTime": 1})
        sid = self._sid(request)
        if inner["Password"] != self.password or inner["Nonce"] != sid:
            return web.json_response({"p_status": "Lockout", "p_waitTime": 1})
        self.csrf[sid] = secrets.token_hex(8)
        return web.json_response(
            {"p_status": "AdminMatch", "encryptData": ccm_encrypt(key, self.csrf[sid], IV, "nonce")}
        )

    async def activate(self, request: web.Request) -> web.Response:
        sid = self._sid(request)
        if sid in self.csrf and request.headers.get("csrfNonce") == self.csrf[sid]:
            self.active = sid  # takes over any other session, like the web UI's OK button
            return web.Response(text='\n\n{"LoginStatus":"yes"}\n')
        return web.Response(text='{"LoginStatus":"no"}')

    async def data(self, request: web.Request) -> web.Response:
        if self.take_over_after_reads is not None and self.reads >= self.take_over_after_reads:
            self.active = "someone-else"
        if not self._authed(request):
            return web.Response(status=400, text=SESSION_LOST)
        self.reads += 1
        page = request.match_info["page"]
        return web.Response(text=(FIXTURES / f"{page}_data.php.txt").read_text())

    async def logout(self, request: web.Request) -> web.Response:
        sid = self._sid(request)
        self.logouts.append(sid)
        if self.active == sid:
            self.active = None
        self.csrf.pop(sid, None)
        return web.Response(text="")

    async def restart(self, request: web.Request) -> web.Response:
        if self.take_over_before_restart:
            self.active = "someone-else"
        if not self._authed(request):
            return web.Response(status=400, text=SESSION_LOST)
        self.restart_requests.append(await request.json())
        return web.Response(text="")
