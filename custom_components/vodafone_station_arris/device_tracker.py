"""Presence detection from the router's attached-device lists."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ArrisConfigEntry, ArrisCoordinator, TrackedDevice

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ArrisConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    tracked: set[str] = set()

    @callback
    def add_new_devices() -> None:
        new = [
            ArrisDeviceTracker(coordinator, mac)
            for mac in coordinator.data.devices
            if mac not in tracked
        ]
        tracked.update(e.unique_id for e in new)
        if new:
            async_add_entities(new)

    add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(add_new_devices))


class ArrisDeviceTracker(CoordinatorEntity[ArrisCoordinator], ScannerEntity):
    """HA enables a tracker by default only if another integration already knows the MAC."""

    def __init__(self, coordinator: ArrisCoordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = mac
        self._attr_mac_address = mac
        self._attr_name = self._tracked.device.name if self._tracked.device else mac

    @property
    def _tracked(self) -> TrackedDevice:
        return self.coordinator.data.devices[self._mac]

    @property
    def is_connected(self) -> bool:
        return self._tracked.home

    @property
    def ip_address(self) -> str | None:
        device = self._tracked.device
        return device.ip_address if device else None

    @property
    def hostname(self) -> str | None:
        device = self._tracked.device
        return device.name if device else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tracked = self._tracked
        attrs: dict[str, Any] = {"last_seen": tracked.last_seen}
        if tracked.device:
            attrs["connection"] = tracked.device.connection
            attrs["interface"] = tracked.device.interface
            attrs["link_rate_mbps"] = tracked.device.link_rate_mbps
        return attrs
