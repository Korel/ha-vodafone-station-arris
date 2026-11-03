"""Base entity tied to the router device."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ArrisCoordinator


def router_device_info(coordinator: ArrisCoordinator) -> DeviceInfo:
    router = coordinator.data.router
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=router.model,
        name="Vodafone Station",
        sw_version=router.firmware,
        hw_version=router.hardware_version,
        serial_number=router.serial_number,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )


class ArrisRouterEntity(CoordinatorEntity[ArrisCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ArrisCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{key}"
        self._attr_device_info = router_device_info(coordinator)
