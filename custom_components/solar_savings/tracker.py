"""Hour-locked tracking of solar kept at home and the money it saved."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
)
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_utc_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .calc import kept_by_source, meter_delta
from .const import SAVE_DELAY, STORAGE_KEY_PREFIX, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


def hour_start(moment: datetime) -> datetime:
    """Start of the UTC hour that contains moment."""
    return dt_util.as_utc(moment).replace(minute=0, second=0, microsecond=0)


def reading_kwh(state: State | None) -> float | None:
    """Meter reading in kWh, or None when the state cannot be used."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if unit == UnitOfEnergy.KILO_WATT_HOUR:
        return value
    if unit not in EnergyConverter.VALID_UNITS:
        return None
    try:
        return EnergyConverter.convert(value, unit, UnitOfEnergy.KILO_WATT_HOUR)
    except HomeAssistantError:
        return None


def price_per_kwh(state: State | None) -> float | None:
    """Price in currency per kWh from a price entity, or None."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or "")
    if unit.endswith("/MWh"):
        return value / 1000
    if unit.endswith("/Wh"):
        return value * 1000
    return value


@dataclass
class SourceTotals:
    """Committed totals for one solar source."""

    energy: float = 0.0
    savings: float = 0.0


@dataclass
class OpenHour:
    """Inputs collected for the open UTC hour."""

    start: datetime | None = None
    production: dict[str, float] = field(default_factory=dict)
    # Production delta times the price when it was measured.
    value: dict[str, float] = field(default_factory=dict)
    export: float = 0.0


class SolarSavingsTracker:
    """Track kept solar per UTC hour and commit it when the hour ends.

    Inside the open hour, production and export deltas only accumulate. When
    the hour ends, each source commits max(0, produced - exported) for that
    hour, with export split by production share. Committed totals never go
    down, so the energy sensor can use state_class total_increasing.

    Savings are priced when the energy is measured: each production delta is
    multiplied by the price at that moment, then scaled by the share of the
    hour's production that was kept.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        solar_sensors: list[str],
        export_sensor: str | None,
        fixed_price: float | None,
        price_entity: str | None,
    ) -> None:
        """Initialize the tracker."""
        self.hass = hass
        self.solar_sensors = list(dict.fromkeys(solar_sensors))
        self.export_sensor = export_sensor or None
        self.fixed_price = fixed_price
        self.price_entity = price_entity or None
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}")
        self._reset_state()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []

    def _reset_state(self) -> None:
        self.readings: dict[str, float] = {}
        self.sources: dict[str, SourceTotals] = {}
        self.total_energy = 0.0
        self.total_savings = 0.0
        self.unpriced_energy = 0.0
        self.last_price: float | None = self.fixed_price
        self.open = OpenHour()

    # ----- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        """Restore state, take first readings and start listening."""
        await self._async_restore()
        for source in self.solar_sensors:
            self.sources.setdefault(source, SourceTotals())
        now = dt_util.utcnow()
        self.roll(now)
        if self.price_entity:
            self._update_price(self.hass.states.get(self.price_entity))
        for entity_id in self._meters():
            self.handle_reading(entity_id, reading_kwh(self.hass.states.get(entity_id)), now)
        self._unsubs.append(
            async_track_state_change_event(self.hass, self._meters(), self._async_meter_changed)
        )
        if self.price_entity:
            self._unsubs.append(
                async_track_state_change_event(self.hass, [self.price_entity], self._async_price_changed)
            )
        self._unsubs.append(async_track_utc_time_change(self.hass, self._async_hour_tick, minute=0, second=0))
        self._schedule_save()

    async def async_stop(self) -> None:
        """Stop listening and save."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    async def async_remove(self) -> None:
        """Delete saved state."""
        await self._store.async_remove()

    # ----- listeners -------------------------------------------------------

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Call update whenever totals or the open hour change."""
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def _async_meter_changed(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        self.handle_reading(entity_id, reading_kwh(event.data["new_state"]), dt_util.utcnow())
        self._schedule_save()
        self._notify()

    @callback
    def _async_price_changed(self, event: Event[EventStateChangedData]) -> None:
        self._update_price(event.data["new_state"])
        self._notify()

    @callback
    def _async_hour_tick(self, now: datetime) -> None:
        if self.roll(now):
            self._schedule_save()
            self._notify()

    # ----- math ------------------------------------------------------------

    def _meters(self) -> list[str]:
        meters = list(self.solar_sensors)
        if self.export_sensor:
            meters.append(self.export_sensor)
        return meters

    def _update_price(self, state: State | None) -> None:
        price = price_per_kwh(state)
        if price is not None:
            self.last_price = price
        elif self.last_price is not None:
            _LOGGER.debug("Price entity %s unusable, keeping %s", self.price_entity, self.last_price)

    @property
    def price(self) -> float | None:
        """Price per kWh applied to energy measured now."""
        if self.price_entity is None:
            return self.fixed_price
        return self.last_price

    def roll(self, now: datetime) -> bool:
        """Commit the open hour if now is in a later hour. Return True if committed."""
        start = hour_start(now)
        if self.open.start is None:
            self.open.start = start
            return False
        if start <= self.open.start:
            return False
        self._commit()
        self.open = OpenHour(start=start)
        return True

    def _commit(self) -> None:
        kept = kept_by_source(self.open.production, self.open.export)
        for source, energy in kept.items():
            produced = self.open.production[source]
            share = energy / produced if produced > 0 else 0.0
            savings = self.open.value.get(source, 0.0) * share
            totals = self.sources.setdefault(source, SourceTotals())
            totals.energy += energy
            totals.savings += savings
            self.total_energy += energy
            self.total_savings += savings

    def handle_reading(self, entity_id: str, kwh: float | None, now: datetime) -> None:
        """Feed one meter reading in kWh. None (unavailable) is skipped."""
        self.roll(now)
        if kwh is None:
            return
        delta, reference = meter_delta(self.readings.get(entity_id), kwh)
        self.readings[entity_id] = reference
        if delta <= 0:
            return
        if entity_id in self.solar_sensors:
            self.open.production[entity_id] = self.open.production.get(entity_id, 0.0) + delta
            price = self.price
            if price is None:
                self.unpriced_energy += delta
                price = 0.0
            self.open.value[entity_id] = self.open.value.get(entity_id, 0.0) + delta * price
        elif entity_id == self.export_sensor:
            self.open.export += delta

    # ----- views -----------------------------------------------------------

    def provisional(self) -> dict[str, tuple[float, float]]:
        """Kept energy and savings so far in the open hour, per source."""
        kept = kept_by_source(self.open.production, self.open.export)
        result: dict[str, tuple[float, float]] = {}
        for source, energy in kept.items():
            produced = self.open.production[source]
            share = energy / produced if produced > 0 else 0.0
            result[source] = (energy, self.open.value.get(source, 0.0) * share)
        return result

    # ----- storage ---------------------------------------------------------

    def _data(self) -> dict[str, Any]:
        return {
            "readings": self.readings,
            "sources": {k: {"energy": v.energy, "savings": v.savings} for k, v in self.sources.items()},
            "total_energy": self.total_energy,
            "total_savings": self.total_savings,
            "unpriced_energy": self.unpriced_energy,
            "last_price": self.last_price if self.price_entity else None,
            "open": {
                "start": self.open.start.isoformat() if self.open.start else None,
                "production": self.open.production,
                "value": self.open.value,
                "export": self.open.export,
            },
        }

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    async def _async_restore(self) -> None:
        data = await self._store.async_load()
        if not data:
            return
        try:
            meters = set(self._meters())
            self.readings = {k: float(v) for k, v in data.get("readings", {}).items() if k in meters}
            self.sources = {
                k: SourceTotals(float(v.get("energy", 0.0)), float(v.get("savings", 0.0)))
                for k, v in data.get("sources", {}).items()
            }
            self.total_energy = float(data.get("total_energy", 0.0))
            self.total_savings = float(data.get("total_savings", 0.0))
            self.unpriced_energy = float(data.get("unpriced_energy", 0.0))
            if self.price_entity and data.get("last_price") is not None:
                self.last_price = float(data["last_price"])
            open_data = data.get("open") or {}
            start = dt_util.parse_datetime(open_data["start"]) if open_data.get("start") else None
            self.open = OpenHour(
                start=start,
                production={
                    k: float(v) for k, v in open_data.get("production", {}).items() if k in self.solar_sensors
                },
                value={k: float(v) for k, v in open_data.get("value", {}).items() if k in self.solar_sensors},
                export=float(open_data.get("export", 0.0)) if self.export_sensor else 0.0,
            )
        except (TypeError, ValueError, KeyError, AttributeError) as err:
            _LOGGER.warning("Ignoring unreadable saved Solar Savings state: %s", err)
            self._reset_state()
