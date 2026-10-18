"""Integration tests: real Home Assistant, real state changes, real hour rolls."""

from __future__ import annotations

from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.solar_savings.const import (
    CONF_EXPORT_SENSOR,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_MODE,
    CONF_SOLAR_SENSORS,
    DOMAIN,
    PRICE_MODE_ENTITY,
    PRICE_MODE_FIXED,
)

SOLAR = "sensor.solar"
SOLAR_B = "sensor.solar_b"
EXPORT = "sensor.export"
PRICE = "sensor.price"
ENERGY = "sensor.solar_savings_solar_self_consumed_energy"
SAVINGS = "sensor.solar_savings_solar_savings"
START = "2026-10-18 10:05:00+00:00"


def set_meter(hass: HomeAssistant, entity_id: str, value: Any, unit: str = "kWh") -> None:
    hass.states.async_set(
        entity_id,
        value,
        {ATTR_UNIT_OF_MEASUREMENT: unit, "device_class": "energy", "state_class": "total_increasing"},
    )


async def setup(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Solar Savings", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def next_hour(hass: HomeAssistant, freezer: FrozenDateTimeFactory, at: str) -> None:
    freezer.move_to(at)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def value(hass: HomeAssistant, entity_id: str) -> float:
    return float(hass.states.get(entity_id).state)


@pytest.fixture(autouse=True)
def _start(freezer: FrozenDateTimeFactory, hass: HomeAssistant) -> None:
    freezer.move_to(START)
    hass.config.currency = "EUR"


async def test_production_minus_export(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """10 kWh produced, 4 exported, price 1 -> 6 kWh kept, 6 EUR saved."""
    set_meter(hass, SOLAR, 100)
    set_meter(hass, EXPORT, 50)
    await setup(
        hass,
        **{
            CONF_SOLAR_SENSORS: [SOLAR],
            CONF_EXPORT_SENSOR: EXPORT,
            CONF_PRICE_MODE: PRICE_MODE_FIXED,
            CONF_PRICE: 1.0,
        },
    )
    set_meter(hass, SOLAR, 110)
    set_meter(hass, EXPORT, 54)
    await hass.async_block_till_done()

    # Open hour: nothing committed yet, the live value is an attribute.
    assert value(hass, ENERGY) == 0
    assert hass.states.get(ENERGY).attributes["provisional_kwh"] == pytest.approx(6.0)
    assert hass.states.get(SAVINGS).attributes["provisional_savings"] == pytest.approx(6.0)

    await next_hour(hass, freezer, "2026-10-18 11:00:01+00:00")
    assert value(hass, ENERGY) == pytest.approx(6.0)
    assert value(hass, SAVINGS) == pytest.approx(6.0)
    state = hass.states.get(SAVINGS)
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == "EUR"
    assert state.attributes["state_class"] == "total"
    assert hass.states.get(ENERGY).attributes["state_class"] == "total_increasing"


async def test_export_arriving_late_in_hour_never_lowers_total(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Export after production in the same hour only changes the provisional value."""
    set_meter(hass, SOLAR, 0)
    set_meter(hass, EXPORT, 0)
    await setup(
        hass,
        **{
            CONF_SOLAR_SENSORS: [SOLAR],
            CONF_EXPORT_SENSOR: EXPORT,
            CONF_PRICE_MODE: PRICE_MODE_FIXED,
            CONF_PRICE: 1.0,
        },
    )
    set_meter(hass, SOLAR, 10)
    await hass.async_block_till_done()
    assert hass.states.get(ENERGY).attributes["provisional_kwh"] == pytest.approx(10.0)
    set_meter(hass, EXPORT, 4)
    await hass.async_block_till_done()
    assert hass.states.get(ENERGY).attributes["provisional_kwh"] == pytest.approx(6.0)
    assert value(hass, ENERGY) == 0
    await next_hour(hass, freezer, "2026-10-18 11:00:01+00:00")
    assert value(hass, ENERGY) == pytest.approx(6.0)

    # Export in a later hour (battery sold) does not reach back.
    set_meter(hass, EXPORT, 7)
    await hass.async_block_till_done()
    await next_hour(hass, freezer, "2026-10-18 12:00:01+00:00")
    assert value(hass, ENERGY) == pytest.approx(6.0)


async def test_no_export_sensor(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Without an export sensor, savings = production x price. Wh is converted."""
    set_meter(hass, SOLAR, 1000, "Wh")
    await setup(hass, **{CONF_SOLAR_SENSORS: [SOLAR], CONF_PRICE_MODE: PRICE_MODE_FIXED, CONF_PRICE: 0.32})
    set_meter(hass, SOLAR, 6000, "Wh")
    await hass.async_block_till_done()
    await next_hour(hass, freezer, "2026-10-18 11:00:01+00:00")
    assert value(hass, ENERGY) == pytest.approx(5.0)
    assert value(hass, SAVINGS) == pytest.approx(1.6)


async def test_two_sources_share_export(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Export is split by production share."""
    hass.states.async_set(SOLAR, 0, {ATTR_UNIT_OF_MEASUREMENT: "kWh", "friendly_name": "Roof"})
    hass.states.async_set(SOLAR_B, 0, {ATTR_UNIT_OF_MEASUREMENT: "kWh", "friendly_name": "Balcony"})
    set_meter(hass, EXPORT, 0)
    await setup(
        hass,
        **{
            CONF_SOLAR_SENSORS: [SOLAR, SOLAR_B],
            CONF_EXPORT_SENSOR: EXPORT,
            CONF_PRICE_MODE: PRICE_MODE_FIXED,
            CONF_PRICE: 0.5,
        },
    )
    hass.states.async_set(SOLAR, 6, {ATTR_UNIT_OF_MEASUREMENT: "kWh", "friendly_name": "Roof"})
    hass.states.async_set(SOLAR_B, 2, {ATTR_UNIT_OF_MEASUREMENT: "kWh", "friendly_name": "Balcony"})
    set_meter(hass, EXPORT, 4)
    await hass.async_block_till_done()
    await next_hour(hass, freezer, "2026-10-18 11:00:01+00:00")

    assert value(hass, ENERGY) == pytest.approx(4.0)
    assert value(hass, SAVINGS) == pytest.approx(2.0)
    assert value(hass, "sensor.solar_savings_roof_self_consumed_energy") == pytest.approx(3.0)
    assert value(hass, "sensor.solar_savings_balcony_self_consumed_energy") == pytest.approx(1.0)
    assert value(hass, "sensor.solar_savings_roof_savings") == pytest.approx(1.5)
    assert value(hass, "sensor.solar_savings_balcony_savings") == pytest.approx(0.5)


async def test_meter_reset_and_unavailable(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A reset counts only growth after it; unavailable states are skipped."""
    set_meter(hass, SOLAR, 500)
    await setup(hass, **{CONF_SOLAR_SENSORS: [SOLAR], CONF_PRICE_MODE: PRICE_MODE_FIXED, CONF_PRICE: 1.0})
    set_meter(hass, SOLAR, 505)
    set_meter(hass, SOLAR, STATE_UNAVAILABLE)
    set_meter(hass, SOLAR, "unknown")
    set_meter(hass, SOLAR, 0)  # meter reset
    set_meter(hass, SOLAR, 2)
    await hass.async_block_till_done()
    await next_hour(hass, freezer, "2026-10-18 11:00:01+00:00")
    assert value(hass, ENERGY) == pytest.approx(7.0)
    assert value(hass, SAVINGS) == pytest.approx(7.0)


async def test_price_entity_change(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A new price applies only to energy measured after the change."""
    set_meter(hass, SOLAR, 0)
    hass.states.async_set(PRICE, 0.30, {ATTR_UNIT_OF_MEASUREMENT: "EUR/kWh"})
    await setup(
        hass, **{CONF_SOLAR_SENSORS: [SOLAR], CONF_PRICE_MODE: PRICE_MODE_ENTITY, CONF_PRICE_ENTITY: PRICE}
    )
    set_meter(hass, SOLAR, 5)
    await hass.async_block_till_done()
    hass.states.async_set(PRICE, 0.50, {ATTR_UNIT_OF_MEASUREMENT: "EUR/kWh"})
    await hass.async_block_till_done()
    set_meter(hass, SOLAR, 10)
    await hass.async_block_till_done()
    # Price changes again before the hour ends: already measured energy keeps its price.
    hass.states.async_set(PRICE, 9.99, {ATTR_UNIT_OF_MEASUREMENT: "EUR/kWh"})
    await hass.async_block_till_done()
    await next_hour(hass, freezer, "2026-10-18 11:00:01+00:00")
    assert value(hass, SAVINGS) == pytest.approx(5 * 0.30 + 5 * 0.50)

    # EUR/MWh is converted; unavailable price keeps the last known one.
    hass.states.async_set(PRICE, 200, {ATTR_UNIT_OF_MEASUREMENT: "EUR/MWh"})
    hass.states.async_set(PRICE, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    set_meter(hass, SOLAR, 20)
    await hass.async_block_till_done()
    await next_hour(hass, freezer, "2026-10-18 12:00:01+00:00")
    assert value(hass, SAVINGS) == pytest.approx(4.0 + 10 * 0.2)


async def test_totals_survive_restart(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Unload and set up again: totals and the open hour are restored."""
    set_meter(hass, SOLAR, 0)
    entry = await setup(
        hass, **{CONF_SOLAR_SENSORS: [SOLAR], CONF_PRICE_MODE: PRICE_MODE_FIXED, CONF_PRICE: 1.0}
    )
    set_meter(hass, SOLAR, 3)
    await hass.async_block_till_done()
    await next_hour(hass, freezer, "2026-10-18 11:00:01+00:00")
    set_meter(hass, SOLAR, 4)  # 1 kWh in the open hour
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    set_meter(hass, SOLAR, 6)  # produced while stopped
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert value(hass, ENERGY) == pytest.approx(3.0)
    assert hass.states.get(ENERGY).attributes["provisional_kwh"] == pytest.approx(3.0)
    await next_hour(hass, freezer, "2026-10-18 12:00:01+00:00")
    assert value(hass, ENERGY) == pytest.approx(6.0)
