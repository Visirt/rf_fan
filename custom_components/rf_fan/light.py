"""Light platform for rf_fan - a toggle-controlled light with optimistic state."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .command import async_send_stored
from .const import (
    CLEAN_REPEAT,
    CMD_LIGHT,
    CONF_COMMANDS,
    CONF_DIRECT,
    CONF_FREQUENCY,
    CONF_HAS_LIGHT,
    CONF_NAME,
    CONF_TRANSMITTER,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the light entity if a light toggle was learned."""
    if entry.data.get(CONF_HAS_LIGHT) and CMD_LIGHT in entry.data[CONF_COMMANDS]:
        async_add_entities([RfFanLight(entry)])


class RfFanLight(LightEntity, RestoreEntity):
    """A light controlled by a single learned toggle code.

    The remote has one button that flips the light, so on and off both send the
    same code - we only send it when the requested state differs from our
    assumed state, to avoid toggling the light the wrong way.
    """

    _attr_has_entity_name = True
    _attr_name = "Light"
    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialise from the learned light command."""
        self._command = entry.data[CONF_COMMANDS][CMD_LIGHT]
        self._transmitter = entry.data[CONF_TRANSMITTER]
        self._frequency = entry.data[CONF_FREQUENCY]
        self._direct = entry.data.get(CONF_DIRECT, False)
        self._attr_unique_id = f"{entry.entry_id}_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="RF Fan (Broadlink Learning)",
        )
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore the last assumed state across restarts."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"

    async def _toggle(self) -> None:
        await async_send_stored(
            self.hass,
            self._transmitter,
            self._command,
            self._frequency,
            clean=self._direct,
            repeat=CLEAN_REPEAT if self._direct else 0,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on (only sends the toggle if currently off)."""
        if not self._attr_is_on:
            await self._toggle()
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off (only sends the toggle if currently on)."""
        if self._attr_is_on:
            await self._toggle()
        self._attr_is_on = False
        self.async_write_ha_state()
