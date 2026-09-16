"""Constants for the Flame King Propane Scale integration."""

from typing import Final

DOMAIN: Final = "flame_king_scale"
PLATFORMS: Final = ["sensor"]

DEVICE_NAME: Final = "Gas Monitor"
MODEL: Final = "YSNPS1"
MANUFACTURER: Final = "Flame King"

SERVICE_UUID: Final = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID: Final = "0000ffe4-0000-1000-8000-00805f9b34fb"

CONF_ADDRESS: Final = "address"
CONF_RAW_ZERO: Final = "raw_zero"
CONF_RAW_REFERENCE: Final = "raw_reference"
CONF_REFERENCE_WEIGHT: Final = "reference_weight_lb"
CONF_TARE_WEIGHT: Final = "tare_weight_lb"
CONF_CAPACITY: Final = "capacity_lb"

DEFAULT_RAW_ZERO: Final = 0
DEFAULT_RAW_REFERENCE: Final = 1600
DEFAULT_REFERENCE_WEIGHT: Final = 13.2277  # 6 kg, a published example point.
DEFAULT_TARE_WEIGHT: Final = 17.0
DEFAULT_CAPACITY: Final = 20.0

DEFAULT_OPTIONS: Final = {
    CONF_RAW_ZERO: DEFAULT_RAW_ZERO,
    CONF_RAW_REFERENCE: DEFAULT_RAW_REFERENCE,
    CONF_REFERENCE_WEIGHT: DEFAULT_REFERENCE_WEIGHT,
    CONF_TARE_WEIGHT: DEFAULT_TARE_WEIGHT,
    CONF_CAPACITY: DEFAULT_CAPACITY,
}
