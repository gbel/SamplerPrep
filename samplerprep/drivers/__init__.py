"""Driver loader for SamplerPrep device drivers."""

from importlib import import_module

_DRIVER_MAP = {
    "radio-music": "radio_music",
    "morphagene": "morphagene",
    "digitakt": "digitakt",
    "octatrack": "octatrack",
    "tracker": "tracker",
    "rample": "rample",
    "queen-of-pentacles": "queen",
    "bitbox": "bitbox",
    "squid": "squid",
}


def load_driver(device_key: str):
    """Return the driver module for a device key."""
    module_name = _DRIVER_MAP[device_key]
    return import_module(f"samplerprep.drivers.{module_name}")
