"""One read-only poll against a real router, using the integration's own api.py.

    uv run --with aiohttp --with cryptography python -I scripts/probe.py [host]

Prints counts and versions only; no MACs, hostnames, IPs or serial numbers.
"""

from __future__ import annotations

import asyncio
import getpass
import importlib.util
import os
import sys
from collections import Counter
from pathlib import Path

import aiohttp

API_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "vodafone_station_arris" / "api.py"


def _load_api():
    if "arris_api" in sys.modules:
        return sys.modules["arris_api"]
    spec = importlib.util.spec_from_file_location("arris_api", API_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["arris_api"] = module
    spec.loader.exec_module(module)
    return module


api = _load_api()


def _locked(channels) -> str:
    return f"{sum(c.locked for c in channels)}/{len(channels)}"


def summarize(data) -> str:
    by_type = Counter(d.connection for d in data.devices.values())
    split = ", ".join(f"{k} {by_type[k]}" for k in ("lan", "wifi", "guest_wifi"))
    return "\n".join(
        [
            f"model: {data.model}",
            f"firmware: {data.firmware}",
            f"hardware: {data.hardware_version}",
            f"uptime: {data.uptime}",
            f"modem status: {data.modem_status}",
            f"wifi enabled: {data.wifi_enabled}, guest wifi enabled: {data.guest_wifi_enabled}",
            f"devices: {len(data.devices)} ({split})",
            f"downstream locked: {_locked(data.downstream)}",
            f"upstream locked: {_locked(data.upstream)}",
        ]
    )


async def run(host: str, username: str, password: str) -> str:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        client = api.ArrisStationClient(host, username, password, session)
        return summarize(await client.fetch())


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.1"
    password = os.environ.get("ARRIS_PASSWORD") or getpass.getpass("Router password: ")
    try:
        print(asyncio.run(run(host, os.environ.get("ARRIS_USERNAME", "admin"), password)))
    except api.WebUiBusy:
        sys.exit("someone is logged into the web UI; log out there first (nothing was sent)")
    except api.InvalidAuth as err:
        sys.exit(f"{err}; not retrying (repeated attempts extend the lockout)")


if __name__ == "__main__":
    main()
