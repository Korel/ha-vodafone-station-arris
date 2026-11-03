"""Router, client-count and DOCSIS sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DocsisChannel
from .coordinator import ArrisConfigEntry, CoordinatorData
from .entity import ArrisRouterEntity

PARALLEL_UPDATES = 0


def _count(data: CoordinatorData, connection: str | None = None) -> int:
    return sum(
        1
        for d in data.router.devices.values()
        if connection is None or d.connection == connection
    )


def _locked(channels: list[DocsisChannel]) -> int:
    return sum(1 for c in channels if c.locked)


def _agg(channels: list[DocsisChannel], attr: str, fn: Callable[..., float]) -> float | None:
    values = [v for c in channels if c.locked and (v := getattr(c, attr)) is not None]
    return round(fn(values), 1) if values else None


@dataclass(frozen=True, kw_only=True)
class ArrisSensorDescription(SensorEntityDescription):
    value_fn: Callable[[CoordinatorData], str | int | float | datetime | None]


SENSORS: tuple[ArrisSensorDescription, ...] = (
    ArrisSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.boot_time,
    ),
    ArrisSensorDescription(
        key="last_read",
        translation_key="last_read",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_read,
    ),
    ArrisSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.router.firmware,
    ),
    ArrisSensorDescription(
        key="wan_ipv4",
        translation_key="wan_ipv4",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.router.wan_ipv4,
    ),
    ArrisSensorDescription(
        key="wan_ipv6",
        translation_key="wan_ipv6",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.router.wan_ipv6,
    ),
    ArrisSensorDescription(
        key="modem_status",
        translation_key="modem_status",
        value_fn=lambda d: d.router.modem_status,
    ),
    ArrisSensorDescription(
        key="connected_devices",
        translation_key="connected_devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count,
    ),
    ArrisSensorDescription(
        key="lan_devices",
        translation_key="lan_devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _count(d, "lan"),
    ),
    ArrisSensorDescription(
        key="wifi_devices",
        translation_key="wifi_devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _count(d, "wifi"),
    ),
    ArrisSensorDescription(
        key="guest_wifi_devices",
        translation_key="guest_wifi_devices",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _count(d, "guest_wifi"),
    ),
    ArrisSensorDescription(
        key="downstream_locked",
        translation_key="downstream_locked",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _locked(d.router.downstream),
    ),
    ArrisSensorDescription(
        key="upstream_locked",
        translation_key="upstream_locked",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _locked(d.router.upstream),
    ),
    ArrisSensorDescription(
        key="downstream_snr_min",
        translation_key="downstream_snr_min",
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _agg(d.router.downstream, "snr_db", min),
    ),
    ArrisSensorDescription(
        key="downstream_power_min",
        translation_key="downstream_power_min",
        native_unit_of_measurement="dBmV",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _agg(d.router.downstream, "power_dbmv", min),
    ),
    ArrisSensorDescription(
        key="downstream_power_max",
        translation_key="downstream_power_max",
        native_unit_of_measurement="dBmV",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _agg(d.router.downstream, "power_dbmv", max),
    ),
    ArrisSensorDescription(
        key="upstream_power_max",
        translation_key="upstream_power_max",
        native_unit_of_measurement="dBmV",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _agg(d.router.upstream, "power_dbmv", max),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ArrisConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ArrisSensor(coordinator, description) for description in SENSORS)


class ArrisSensor(ArrisRouterEntity, SensorEntity):
    entity_description: ArrisSensorDescription

    def __init__(self, coordinator, description: ArrisSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | float | datetime | None:
        return self.entity_description.value_fn(self.coordinator.data)
