"""Constants for Solar Savings."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "solar_savings"

CONF_SOLAR_SENSORS: Final = "solar_sensors"
CONF_EXPORT_SENSOR: Final = "export_sensor"
CONF_PRICE_MODE: Final = "price_mode"
CONF_PRICE: Final = "price"
CONF_PRICE_ENTITY: Final = "price_entity"

PRICE_MODE_FIXED: Final = "fixed"
PRICE_MODE_ENTITY: Final = "entity"
PRICE_MODES: Final = [PRICE_MODE_FIXED, PRICE_MODE_ENTITY]

DEFAULT_NAME: Final = "Solar Savings"

STORAGE_VERSION: Final = 1
STORAGE_KEY_PREFIX: Final = "solar_savings"
SAVE_DELAY: Final = 30

# A drop below this share of the last reading is a meter reset. A smaller drop
# is treated as a glitch and ignored, like the recorder does for
# total_increasing sensors.
RESET_THRESHOLD: Final = 0.9
