"""Solar Savings: money saved by solar energy used at home."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_EXPORT_SENSOR,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_MODE,
    CONF_SOLAR_SENSORS,
    PRICE_MODE_ENTITY,
)
from .tracker import SolarSavingsTracker

PLATFORMS: list[Platform] = [Platform.SENSOR]

type SolarSavingsConfigEntry = ConfigEntry[SolarSavingsTracker]


async def async_setup_entry(hass: HomeAssistant, entry: SolarSavingsConfigEntry) -> bool:
    """Set up Solar Savings from a config entry."""
    options = {**entry.data, **entry.options}
    entity_mode = options.get(CONF_PRICE_MODE) == PRICE_MODE_ENTITY
    tracker = SolarSavingsTracker(
        hass,
        entry.entry_id,
        solar_sensors=list(options.get(CONF_SOLAR_SENSORS, [])),
        export_sensor=options.get(CONF_EXPORT_SENSOR),
        fixed_price=None if entity_mode else float(options.get(CONF_PRICE, 0.0)),
        price_entity=options.get(CONF_PRICE_ENTITY) if entity_mode else None,
    )
    await tracker.async_start()
    entry.runtime_data = tracker
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolarSavingsConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SolarSavingsConfigEntry) -> None:
    """Delete saved totals when the entry is deleted."""
    tracker = SolarSavingsTracker(hass, entry.entry_id, [], None, None, None)
    await tracker.async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: SolarSavingsConfigEntry) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)
