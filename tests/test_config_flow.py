"""Config and options flow tests."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_savings.const import (
    CONF_EXPORT_SENSOR,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_MODE,
    CONF_SOLAR_SENSORS,
    DOMAIN,
)


async def test_user_flow_fixed_price(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Home",
            CONF_SOLAR_SENSORS: ["sensor.export"],
            CONF_EXPORT_SENSOR: "sensor.export",
            CONF_PRICE_MODE: "fixed",
        },
    )
    assert result["errors"] == {CONF_EXPORT_SENSOR: "export_is_solar"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Home",
            CONF_SOLAR_SENSORS: ["sensor.pv"],
            CONF_EXPORT_SENSOR: "sensor.export",
            CONF_PRICE_MODE: "fixed",
        },
    )
    assert result["step_id"] == "fixed_price"
    with patch("custom_components.solar_savings.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PRICE: 0.32})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["options"] == {
        CONF_SOLAR_SENSORS: ["sensor.pv"],
        CONF_EXPORT_SENSOR: "sensor.export",
        CONF_PRICE_MODE: "fixed",
        CONF_PRICE: 0.32,
    }


async def test_options_flow_switch_to_entity(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={},
        options={CONF_SOLAR_SENSORS: ["sensor.pv"], CONF_PRICE_MODE: "fixed", CONF_PRICE: 0.3},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SOLAR_SENSORS: ["sensor.pv"], CONF_PRICE_MODE: "entity"}
    )
    assert result["step_id"] == "price_entity"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PRICE_ENTITY: "sensor.price"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {
        CONF_SOLAR_SENSORS: ["sensor.pv"],
        CONF_PRICE_MODE: "entity",
        CONF_PRICE_ENTITY: "sensor.price",
    }
