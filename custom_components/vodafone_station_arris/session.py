"""aiohttp session factory."""

from aiohttp import ClientSession, CookieJar

from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client


def async_client_session(hass: HomeAssistant) -> ClientSession:
    """Dedicated session: the router's cookies must not leak into HA's shared one.

    `unsafe=True` because aiohttp otherwise drops cookies set by bare IP hosts.
    """
    return aiohttp_client.async_create_clientsession(
        hass, cookie_jar=CookieJar(unsafe=True, quote_cookie=False)
    )


def standalone_session() -> ClientSession:
    """Short-lived session for the config flow; the caller closes it (HA forbids closing its own)."""
    return ClientSession(cookie_jar=CookieJar(unsafe=True, quote_cookie=False))