"""Button platform for rf_fan - one entity per learned custom button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .command import async_send_stored
from .const import (
    CLEAN_REPEAT,
    CONF_COMMANDS,
    CONF_CUSTOMS,
    CONF_DIRECT,
    CONF_FREQUENCY,
    CONF_NAME,
    CONF_TRANSMITTER,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a button entity for each learned custom button."""
    commands = entry.data[CONF_COMMANDS]
    async_add_entities(
        RfFanButton(entry, custom)
        for custom in entry.data.get(CONF_CUSTOMS, [])
        if custom["key"] in commands
    )


class RfFanButton(ButtonEntity):
    """A custom learned button - presses send the captured code once."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, custom: dict[str, str]) -> None:
        """Initialise from a custom button definition."""
        self._command = entry.data[CONF_COMMANDS][custom["key"]]
        self._transmitter = entry.data[CONF_TRANSMITTER]
        self._frequency = entry.data[CONF_FREQUENCY]
        self._direct = entry.data.get(CONF_DIRECT, False)
        self._attr_name = custom["name"]
        self._attr_unique_id = f"{entry.entry_id}_{custom['key']}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="RF Fan (Broadlink Learning)",
        )

    async def async_press(self) -> None:
        """Send the learned code."""
        await async_send_stored(
            self.hass,
            self._transmitter,
            self._command,
            self._frequency,
            clean=self._direct,
            repeat=CLEAN_REPEAT if self._direct else 0,
        )
