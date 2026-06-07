"""RF Fan with Learning.

A learn-and-replay Home Assistant integration for RF ceiling fans: capture your
remote's codes with a Broadlink RM Pro / RM4 Pro through a guided wizard, then
transmit them via Home Assistant's native ``radio_frequency`` platform. Fans,
lights and custom buttons are all set up from the UI - no YAML, no code lists.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS = [Platform.FAN, Platform.LIGHT, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a fan from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change (e.g. after re-learning)."""
    await hass.config_entries.async_reload(entry.entry_id)
