"""Config and options flow for Solar Savings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_EXPORT_SENSOR,
    CONF_PRICE,
    CONF_PRICE_ENTITY,
    CONF_PRICE_MODE,
    CONF_SOLAR_SENSORS,
    DEFAULT_NAME,
    DOMAIN,
    PRICE_MODE_ENTITY,
    PRICE_MODE_FIXED,
    PRICE_MODES,
)


def _sensors_schema(defaults: dict[str, Any], with_name: bool) -> vol.Schema:
    energy = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.ENERGY, multiple=True)
    )
    export = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.ENERGY)
    )
    mode = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=PRICE_MODES, translation_key=CONF_PRICE_MODE, mode=selector.SelectSelectorMode.LIST
        )
    )
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = (
            selector.TextSelector()
        )
    fields[vol.Required(CONF_SOLAR_SENSORS, default=defaults.get(CONF_SOLAR_SENSORS, []))] = energy
    if defaults.get(CONF_EXPORT_SENSOR):
        fields[
            vol.Optional(CONF_EXPORT_SENSOR, description={"suggested_value": defaults[CONF_EXPORT_SENSOR]})
        ] = export
    else:
        fields[vol.Optional(CONF_EXPORT_SENSOR)] = export
    fields[vol.Required(CONF_PRICE_MODE, default=defaults.get(CONF_PRICE_MODE, PRICE_MODE_FIXED))] = mode
    return vol.Schema(fields)


def _price_schema(mode: str, defaults: dict[str, Any], currency: str) -> vol.Schema:
    if mode == PRICE_MODE_FIXED:
        return vol.Schema(
            {
                vol.Required(CONF_PRICE, default=defaults.get(CONF_PRICE, 0.30)): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        step="any",
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement=f"{currency}/kWh",
                    )
                )
            }
        )
    key = (
        vol.Required(CONF_PRICE_ENTITY, default=defaults[CONF_PRICE_ENTITY])
        if defaults.get(CONF_PRICE_ENTITY)
        else vol.Required(CONF_PRICE_ENTITY)
    )
    return vol.Schema(
        {
            key: selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])
            )
        }
    )


def _validate_sensors(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    solar = user_input.get(CONF_SOLAR_SENSORS) or []
    if not solar:
        errors[CONF_SOLAR_SENSORS] = "no_solar"
    elif user_input.get(CONF_EXPORT_SENSOR) in solar:
        errors[CONF_EXPORT_SENSOR] = "export_is_solar"
    return errors


def _price_step(mode: str) -> str:
    return "price_entity" if mode == PRICE_MODE_ENTITY else "fixed_price"


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the price field for the chosen mode."""
    data = {k: v for k, v in data.items() if v not in (None, "")}
    if data.get(CONF_PRICE_MODE) == PRICE_MODE_ENTITY:
        data.pop(CONF_PRICE, None)
    else:
        data.pop(CONF_PRICE_ENTITY, None)
    return data


class SolarSavingsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Solar Savings in the UI."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_sensors(user_input)
            if not errors:
                self._data = dict(user_input)
                return await getattr(self, f"async_step_{_price_step(user_input[CONF_PRICE_MODE])}")()
        return self.async_show_form(
            step_id="user", data_schema=_sensors_schema(user_input or {}, with_name=True), errors=errors
        )

    async def async_step_fixed_price(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_price(PRICE_MODE_FIXED, user_input)

    async def async_step_price_entity(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_price(PRICE_MODE_ENTITY, user_input)

    async def _async_price(self, mode: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            data = dict(self._data)
            name = data.pop(CONF_NAME, DEFAULT_NAME)
            data.update(user_input)
            return self.async_create_entry(title=name, data={}, options=_clean(data))
        return self.async_show_form(
            step_id=_price_step(mode), data_schema=_price_schema(mode, {}, self.hass.config.currency)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SolarSavingsOptionsFlow()


class SolarSavingsOptionsFlow(OptionsFlow):
    """Change sensors and price later."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            errors = _validate_sensors(user_input)
            if not errors:
                self._data = dict(user_input)
                return await getattr(self, f"async_step_{_price_step(user_input[CONF_PRICE_MODE])}")()
        return self.async_show_form(
            step_id="init", data_schema=_sensors_schema(user_input or current, with_name=False), errors=errors
        )

    async def async_step_fixed_price(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_price(PRICE_MODE_FIXED, user_input)

    async def async_step_price_entity(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_price(PRICE_MODE_ENTITY, user_input)

    async def _async_price(self, mode: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            data = {**self._data, **user_input}
            return self.async_create_entry(data=_clean(data))
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id=_price_step(mode), data_schema=_price_schema(mode, current, self.hass.config.currency)
        )
