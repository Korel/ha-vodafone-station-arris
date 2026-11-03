"""Wi-Fi state and the 'web UI in use' indicator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ArrisConfigEntry, CoordinatorData
from .entity import ArrisRouterEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ArrisBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[CoordinatorData], bool | None]


BINARY_SENSORS: tuple[ArrisBinarySensorDescription, ...] = (
    ArrisBinarySensorDescription(
        key="web_ui_in_use",
        translation_key="web_ui_in_use",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.web_ui_busy,
    ),
    ArrisBinarySensorDescription(
        key="wifi_enabled",
        translation_key="wifi_enabled",
        value_fn=lambda d: d.router.wifi_enabled,
    ),
    ArrisBinarySensorDescription(
        key="guest_wifi_enabled",
        translation_key="guest_wifi_enabled",
        value_fn=lambda d: d.router.guest_wifi_enabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ArrisConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ArrisBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class ArrisBinarySensor(ArrisRouterEntity, BinarySensorEntity):
    entity_description: ArrisBinarySensorDescription

    def __init__(self, coordinator, description: ArrisBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
