"""Sensors for Solar Savings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SolarSavingsConfigEntry
from .const import DOMAIN
from .tracker import SolarSavingsTracker


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarSavingsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the combined sensors, plus per-source sensors for several sources."""
    tracker = entry.runtime_data
    entities: list[SensorEntity] = [
        SelfConsumedSensor(entry, tracker, None),
        SavingsSensor(entry, tracker, None),
    ]
    if len(tracker.solar_sensors) > 1:
        for source in tracker.solar_sensors:
            label = _source_label(hass, source)
            entities.append(SelfConsumedSensor(entry, tracker, source, label))
            entities.append(SavingsSensor(entry, tracker, source, label))
    async_add_entities(entities)


def _source_label(hass: HomeAssistant, source: str) -> str:
    state = hass.states.get(source)
    return state.name if state else source


class _Base(SensorEntity):
    """Shared plumbing: listen to the tracker, belong to the entry's device."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _key: str

    def __init__(
        self,
        entry: SolarSavingsConfigEntry,
        tracker: SolarSavingsTracker,
        source: str | None,
        label: str | None = None,
    ) -> None:
        self._tracker = tracker
        self._source = source
        if source is None:
            self._attr_translation_key = self._key
            self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        else:
            self._attr_translation_key = f"source_{self._key}"
            self._attr_unique_id = f"{entry.entry_id}_{source}_{self._key}"
            self._attr_translation_placeholders = {"source": label or source}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._tracker.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    def _committed(self) -> tuple[float, float]:
        if self._source is None:
            return self._tracker.total_energy, self._tracker.total_savings
        totals = self._tracker.sources.get(self._source)
        return (totals.energy, totals.savings) if totals else (0.0, 0.0)

    def _provisional(self) -> tuple[float, float]:
        provisional = self._tracker.provisional()
        if self._source is None:
            return sum(v[0] for v in provisional.values()), sum(v[1] for v in provisional.values())
        return provisional.get(self._source, (0.0, 0.0))

    def _hour_attrs(self) -> dict[str, Any]:
        start = self._tracker.open.start
        return {"current_hour_start": start.isoformat() if start else None}


class SelfConsumedSensor(_Base):
    """Solar energy kept at home. Only grows, so total_increasing is valid."""

    _key = "self_consumed"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = frozenset(
        {"current_hour_start", "provisional_kwh", "current_hour_production_kwh", "current_hour_export_kwh"}
    )

    @property
    def native_value(self) -> float:
        return round(self._committed()[0], 6)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        open_hour = self._tracker.open
        if self._source is None:
            production = sum(open_hour.production.values())
        else:
            production = open_hour.production.get(self._source, 0.0)
        attrs = self._hour_attrs()
        attrs["provisional_kwh"] = round(self._provisional()[0], 6)
        attrs["current_hour_production_kwh"] = round(production, 6)
        attrs["current_hour_export_kwh"] = round(open_hour.export, 6)
        return attrs


class SavingsSensor(_Base):
    """Money saved by solar kept at home."""

    _key = "savings"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = frozenset({"current_hour_start", "provisional_savings", "price_per_kwh"})

    @property
    def native_unit_of_measurement(self) -> str:
        return self.hass.config.currency

    @property
    def native_value(self) -> float:
        return round(self._committed()[1], 6)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = self._hour_attrs()
        attrs["provisional_savings"] = round(self._provisional()[1], 6)
        attrs["price_per_kwh"] = self._tracker.price
        if self._source is None:
            attrs["unpriced_energy_kwh"] = round(self._tracker.unpriced_energy, 6)
        return attrs
