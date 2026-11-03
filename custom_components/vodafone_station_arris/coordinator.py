"""Polling coordinator: one login/read/logout per update, skipped while the web UI is in use."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from homeassistant.components.device_tracker import (
    CONF_CONSIDER_HOME,
    DEFAULT_CONSIDER_HOME,
    DOMAIN as DEVICE_TRACKER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ArrisError,
    ArrisStationClient,
    ConnectedDevice,
    InvalidAuth,
    RouterData,
    SessionLost,
    WebUiBusy,
)
from .const import DOMAIN, LOGGER, SCAN_INTERVAL
from .session import async_client_session

type ArrisConfigEntry = ConfigEntry[ArrisCoordinator]

# Boot time is derived from minute-resolution uptime; ignore drift below this.
BOOT_TIME_TOLERANCE = timedelta(minutes=3)


@dataclass(slots=True)
class TrackedDevice:
    mac: str
    device: ConnectedDevice | None
    last_seen: datetime | None
    home: bool


@dataclass(slots=True)
class CoordinatorData:
    router: RouterData
    devices: dict[str, TrackedDevice] = field(default_factory=dict)
    boot_time: datetime | None = None
    last_read: datetime | None = None
    web_ui_busy: bool = False


class ArrisCoordinator(DataUpdateCoordinator[CoordinatorData]):
    config_entry: ArrisConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ArrisConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}-{entry.data[CONF_HOST]}",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.client = ArrisStationClient(
            entry.data[CONF_HOST],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            async_client_session(hass),
        )
        self.consider_home = timedelta(
            seconds=entry.options.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME.total_seconds())
        )
        registry = er.async_get(hass)
        # Restore trackers for devices that are away at startup.
        self._known_macs: set[str] = {
            e.unique_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
            if e.domain == DEVICE_TRACKER_DOMAIN
        }

    async def _async_update_data(self) -> CoordinatorData:
        try:
            router = await self.client.fetch()
        except (WebUiBusy, SessionLost) as err:
            if self.data is None:
                raise UpdateFailed(f"web UI in use, will retry: {err!r}") from err
            LOGGER.debug("Web UI in use, skipping this poll (%r)", err)
            return replace(self.data, web_ui_busy=True)
        except InvalidAuth as err:
            # Stops polling so a wrong password can't escalate the router's lockout.
            raise ConfigEntryAuthFailed(str(err)) from err
        except ArrisError as err:
            raise UpdateFailed(repr(err)) from err

        now = dt_util.utcnow()
        devices = self._merge_devices(router, now)
        self._known_macs |= devices.keys()
        return CoordinatorData(
            router=router,
            devices=devices,
            boot_time=self._boot_time(router, now),
            last_read=now,
        )

    def _merge_devices(self, router: RouterData, now: datetime) -> dict[str, TrackedDevice]:
        previous = self.data.devices if self.data else {}
        merged: dict[str, TrackedDevice] = {}
        for mac in self._known_macs | router.devices.keys():
            if (device := router.devices.get(mac)) is not None:
                merged[mac] = TrackedDevice(mac, device, now, True)
                continue
            old = previous.get(mac)
            last_seen = old.last_seen if old else None
            home = last_seen is not None and now - last_seen < self.consider_home
            merged[mac] = TrackedDevice(mac, old.device if old else None, last_seen, home)
        return merged

    def _boot_time(self, router: RouterData, now: datetime) -> datetime | None:
        if router.uptime is None:
            return None
        boot = (now - router.uptime).replace(second=0, microsecond=0)
        previous = self.data.boot_time if self.data else None
        if previous and abs(boot - previous) < BOOT_TIME_TOLERANCE:
            return previous
        return boot
