"""Router restart button."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import ArrisError
from .const import DOMAIN
from .coordinator import ArrisConfigEntry
from .entity import ArrisRouterEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ArrisConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ArrisRestartButton(entry.runtime_data, "restart")])


class ArrisRestartButton(ArrisRouterEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        try:
            await self.coordinator.client.restart()
        except ArrisError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="restart_failed",
                translation_placeholders={"error": repr(err)},
            ) from err
