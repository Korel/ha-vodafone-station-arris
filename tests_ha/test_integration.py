from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.components.device_tracker import CONF_CONSIDER_HOME
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, STATE_HOME, STATE_NOT_HOME, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.vodafone_station_arris.api import InvalidAuth, WebUiBusy
from custom_components.vodafone_station_arris.const import DOMAIN

FETCH = "custom_components.vodafone_station_arris.api.ArrisStationClient.fetch"
USER_INPUT = {CONF_HOST: "192.168.0.1", CONF_USERNAME: "admin", CONF_PASSWORD: "secret"}


def _register_known_macs(hass: HomeAssistant, *macs: str) -> None:
    """Pretend another integration knows these devices, so HA enables their trackers."""
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    for mac in macs:
        dr.async_get(hass).async_get_or_create(
            config_entry_id=other.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, mac)}
        )


async def _setup(hass: HomeAssistant, router_data, options: dict | None = None) -> MockConfigEntry:
    _register_known_macs(hass, "02:00:00:00:00:01", "02:00:00:00:00:02", "02:00:00:00:00:99")
    entry = MockConfigEntry(
        domain=DOMAIN, data=USER_INPUT, unique_id="TESTSERIAL0001", options=options or {}
    )
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=router_data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_user_flow_creates_entry(hass: HomeAssistant, router_data) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch(FETCH, return_value=router_data), patch(
        "custom_components.vodafone_station_arris.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Vodafone Station TG6442"
    assert result["result"].unique_id == "TESTSERIAL0001"


async def test_user_flow_does_not_close_ha_owned_session(
    hass: HomeAssistant, router_data, caplog
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(FETCH, return_value=router_data), patch(
        "custom_components.vodafone_station_arris.async_setup_entry", return_value=True
    ):
        await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert "closes the Home Assistant aiohttp session" not in caplog.text


async def test_user_flow_web_ui_busy(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(FETCH, side_effect=WebUiBusy):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "web_ui_busy"}


async def test_setup_creates_entities(hass: HomeAssistant, router_data) -> None:
    entry = await _setup(hass, router_data)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.vodafone_station_connected_devices").state == "3"
    assert hass.states.get("sensor.vodafone_station_wi_fi_devices").state == "1"
    assert hass.states.get("sensor.vodafone_station_downstream_channels_locked").state == "2"
    assert hass.states.get("sensor.vodafone_station_upstream_power_max").state == "57.5"
    assert hass.states.get("binary_sensor.vodafone_station_web_ui_in_use").state == STATE_OFF
    assert hass.states.get("device_tracker.phone").state == STATE_HOME
    assert hass.states.get("device_tracker.server").attributes["connection"] == "lan"
    # Unknown MAC (guest device): created, but disabled until the user enables it.
    guest = er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, "02:00:00:00:00:04")
    assert er.async_get(hass).async_get(guest).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_busy_poll_keeps_last_data(hass: HomeAssistant, router_data) -> None:
    entry = await _setup(hass, router_data)
    coordinator = entry.runtime_data
    with patch(FETCH, side_effect=WebUiBusy):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.vodafone_station_web_ui_in_use").state == STATE_ON
    assert hass.states.get("sensor.vodafone_station_connected_devices").state == "3"
    assert hass.states.get("device_tracker.phone").state == STATE_HOME


async def test_device_leaving_and_new_device(hass: HomeAssistant, router_data) -> None:
    entry = await _setup(hass, router_data)
    coordinator = entry.runtime_data
    phone = router_data.devices.pop("02:00:00:00:00:02")
    with patch(FETCH, return_value=router_data):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    # Still within consider_home (180 s).
    assert hass.states.get("device_tracker.phone").state == STATE_HOME
    router_data.devices["02:00:00:00:00:99"] = type(phone)(
        mac="02:00:00:00:00:99", name="tablet", ip_address=None, connection="wifi",
        interface=None, link_rate_mbps=None,
    )
    with patch(FETCH, return_value=router_data):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("device_tracker.tablet").state == STATE_HOME


async def test_invalid_auth_starts_reauth(hass: HomeAssistant, router_data) -> None:
    entry = await _setup(hass, router_data)
    with patch(FETCH, side_effect=InvalidAuth("Lockout", 1)):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [config_entries.SOURCE_REAUTH]


async def test_options_flow_sets_consider_home(hass: HomeAssistant, router_data) -> None:
    entry = await _setup(hass, router_data)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    with patch(FETCH, return_value=router_data):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_CONSIDER_HOME: 60}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_CONSIDER_HOME: 60}


async def _leave_for(hass: HomeAssistant, entry, router_data, freezer, seconds: int) -> str:
    """Phone drops off the router, then `seconds` pass before the next poll."""
    without_phone = replace(router_data, devices=dict(router_data.devices))
    without_phone.devices.pop("02:00:00:00:00:02")
    freezer.tick(timedelta(seconds=seconds))
    with patch(FETCH, return_value=without_phone):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    return hass.states.get("device_tracker.phone").state


async def test_consider_home_option_shortens_away_delay(hass: HomeAssistant, router_data, freezer) -> None:
    entry = await _setup(hass, router_data, options={CONF_CONSIDER_HOME: 60})
    assert await _leave_for(hass, entry, router_data, freezer, 90) == STATE_NOT_HOME


async def test_default_consider_home_is_180s(hass: HomeAssistant, router_data, freezer) -> None:
    entry = await _setup(hass, router_data)
    assert await _leave_for(hass, entry, router_data, freezer, 90) == STATE_HOME
    assert await _leave_for(hass, entry, router_data, freezer, 100) == STATE_NOT_HOME
