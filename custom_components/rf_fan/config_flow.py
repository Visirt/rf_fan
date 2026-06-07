"""Config and options flows for rf_fan: a guided, learn-each-button wizard."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .command import async_send_stored
from .const import (
    CLEAN_REPEAT,
    CMD_LIGHT,
    CMD_OFF,
    CMD_ON,
    CONF_COMMANDS,
    CONF_CUSTOM_BUTTONS,
    CONF_CUSTOMS,
    CONF_DIRECT,
    CONF_FREQUENCY,
    CONF_HAS_LIGHT,
    CONF_HAS_ON,
    CONF_NAME,
    CONF_SPEED_COUNT,
    CONF_TRANSMITTER,
    DEFAULT_FREQUENCY,
    DOMAIN,
)
from .rf import async_capture_packet, async_sweep_frequency, find_rf_devices

_LOGGER = logging.getLogger(__name__)


async def _delayed_capture(device: Any) -> dict[str, Any]:
    """Brief settle, then capture the packet (sweep flow, phase 2)."""
    await asyncio.sleep(1)
    return await async_capture_packet(device)


def _unique_custom_key(name: str, taken: set[str]) -> str:
    """Build a unique custom_<slug> key for a button name."""
    base = f"custom_{slugify(name)}" if slugify(name) else "custom"
    key = base
    suffix = 2
    while key in taken:
        key = f"{base}_{suffix}"
        suffix += 1
    return key


class _LearnFlowMixin:
    """Shared two-phase learning steps for both the config and options flows.

    The concrete flow provides these attributes and implements
    ``_async_after_confirm`` (what to do once a code is kept).
    """

    _device: Any
    _current_key: str | None
    _task: Any
    _pending: dict[str, Any] | None
    _learn_error: str | None
    _commands: dict[str, Any]
    _transmitter: str
    _frequency: int
    _custom_names: dict[str, str]
    _speed_count: int
    _direct: bool

    def _label(self, key: str | None) -> str:
        """Human-friendly label for a command key."""
        if key == CMD_OFF:
            return "Off"
        if key == CMD_ON:
            return "On"
        if key == CMD_LIGHT:
            return "Light"
        if key and key.startswith("speed_"):
            number = key.removeprefix("speed_")
            total = self._speed_count
            if total:
                hint = ""
                if number == "1":
                    hint = " (lowest)"
                elif number == str(total):
                    hint = " (highest)"
                return f"Speed {number} of {total}{hint}"
            return f"Speed {number}"
        return self._custom_names.get(key, key or "")

    def _reset_learn_state(self) -> None:
        """Reset per-button learning state."""
        self._task = None
        self._pending = None
        self._learn_error = None

    async def _async_after_confirm(self) -> ConfigFlowResult:
        """Called after a code is kept. Implemented by the concrete flow."""
        raise NotImplementedError

    async def async_step_learn(self, user_input=None) -> ConfigFlowResult:
        """Learn a button - either direct capture or the two-phase sweep."""
        label = self._label(self._current_key)

        if self._direct:
            # Direct capture: listen at the chosen frequency, single press.
            if self._task is None:
                self._task = self.hass.async_create_task(
                    async_capture_packet(self._device, self._frequency / 1_000_000)
                )
                return self.async_show_progress(
                    step_id="learn",
                    progress_action="press",
                    description_placeholders={"button": label},
                    progress_task=self._task,
                )
            try:
                self._pending = await self._task
                self._learn_error = None
            except Exception as err:  # noqa: BLE001 - surface any capture failure
                self._learn_error = str(err)
                self._task = None
                return self.async_show_progress_done(next_step_id="learn_error")
            self._task = None
            return self.async_show_progress_done(next_step_id="learn_result")

        # Sweep flow, phase 1: hold the button while the carrier is found.
        if self._task is None:
            self._task = self.hass.async_create_task(
                async_sweep_frequency(self._device)
            )
            return self.async_show_progress(
                step_id="learn",
                progress_action="sweep",
                description_placeholders={"button": label},
                progress_task=self._task,
            )
        try:
            await self._task
        except Exception as err:  # noqa: BLE001 - surface any capture failure
            self._learn_error = str(err)
            self._task = None
            return self.async_show_progress_done(next_step_id="learn_error")
        self._task = None
        return self.async_show_progress_done(next_step_id="learn_press")

    async def async_step_learn_press(self, user_input=None) -> ConfigFlowResult:
        """Sweep flow, between phases: release and press again."""
        label = self._label(self._current_key)
        if user_input is not None:
            self._task = self.hass.async_create_task(_delayed_capture(self._device))
            return self.async_show_progress(
                step_id="learn_capture",
                progress_action="capture",
                description_placeholders={"button": label},
                progress_task=self._task,
            )
        return self.async_show_form(
            step_id="learn_press",
            data_schema=vol.Schema({}),
            description_placeholders={"button": label},
        )

    async def async_step_learn_capture(self, user_input=None) -> ConfigFlowResult:
        """Sweep flow, phase 2 done: store the captured code (or report failure)."""
        try:
            self._pending = await self._task
            self._learn_error = None
        except Exception as err:  # noqa: BLE001 - surface any capture failure
            self._learn_error = str(err)
            self._task = None
            return self.async_show_progress_done(next_step_id="learn_error")
        self._task = None
        return self.async_show_progress_done(next_step_id="learn_result")

    async def async_step_learn_result(self, user_input=None) -> ConfigFlowResult:
        """Offer to test, keep, or retry the just-learned code."""
        return self.async_show_menu(
            step_id="learn_result",
            menu_options=["confirm", "test", "retry"],
            description_placeholders={
                "button": self._label(self._current_key),
                "pulses": str(self._pending["length"] if self._pending else 0),
            },
        )

    async def async_step_confirm(self, user_input=None) -> ConfigFlowResult:
        """Store the learned code and continue."""
        assert self._pending is not None
        self._commands[self._current_key] = {
            "timings": self._pending["timings"],
            "repeat": self._pending["repeat"],
            "b64": self._pending["b64"],
        }
        return await self._async_after_confirm()

    async def async_step_test(self, user_input=None) -> ConfigFlowResult:
        """Transmit the just-learned code so the user can verify it."""
        if self._pending is not None:
            try:
                await async_send_stored(
                    self.hass,
                    self._transmitter,
                    self._pending,
                    self._frequency,
                    clean=self._direct,
                    repeat=CLEAN_REPEAT if self._direct else 0,
                )
            except HomeAssistantError as err:
                _LOGGER.error("rf_fan: test send failed: %s", err)
        return await self.async_step_learn_result()

    async def async_step_retry(self, user_input=None) -> ConfigFlowResult:
        """Re-learn the current button the same way."""
        self._reset_learn_state()
        return await self.async_step_learn()

    async def async_step_retry_direct(self, user_input=None) -> ConfigFlowResult:
        """Switch to direct capture (no sweep) and re-learn the current button."""
        self._direct = True
        self._reset_learn_state()
        return await self.async_step_learn()

    async def async_step_learn_error(self, user_input=None) -> ConfigFlowResult:
        """Offer to retry - and, if sweeping, to capture without the sweep."""
        menu_options = ["retry"]
        if not self._direct:
            menu_options.append("retry_direct")
        return self.async_show_menu(
            step_id="learn_error",
            menu_options=menu_options,
            description_placeholders={
                "button": self._label(self._current_key),
                "error": self._learn_error or "",
            },
        )


class RfFanConfigFlow(_LearnFlowMixin, ConfigFlow, domain=DOMAIN):
    """Collect settings, then walk the user through learning each button."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise wizard state."""
        self._data: dict[str, Any] = {}
        self._commands: dict[str, Any] = {}
        self._customs: list[dict[str, str]] = []
        self._custom_names: dict[str, str] = {}
        self._queue: list[str] = []
        self._current_key: str | None = None
        self._device: Any = None
        self._task: Any = None
        self._pending: dict[str, Any] | None = None
        self._learn_error: str | None = None
        self._speed_count: int = 0
        self._transmitter: str = ""
        self._frequency: int = DEFAULT_FREQUENCY
        self._direct: bool = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow (re-learn / add buttons)."""
        return RfFanOptionsFlow()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Collect the fan's name, transmitter and remote layout."""
        devices = find_rf_devices(self.hass)
        if not devices:
            return self.async_abort(reason="no_rf_device")

        if user_input is not None:
            self._device = next(iter(devices.values()))
            self._speed_count = int(user_input[CONF_SPEED_COUNT])
            self._transmitter = user_input[CONF_TRANSMITTER]
            self._frequency = int(user_input[CONF_FREQUENCY])
            self._direct = user_input[CONF_DIRECT]
            has_on = user_input[CONF_HAS_ON]
            has_light = user_input[CONF_HAS_LIGHT]

            # Parse the free-text custom-button names into unique keys.
            self._customs = []
            self._custom_names = {}
            taken: set[str] = set()
            raw = user_input.get(CONF_CUSTOM_BUTTONS) or ""
            for name in (n.strip() for n in re.split(r"[,\n]", raw)):
                if not name:
                    continue
                key = _unique_custom_key(name, taken)
                taken.add(key)
                self._customs.append({"key": key, "name": name})
                self._custom_names[key] = name

            self._data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_TRANSMITTER: self._transmitter,
                CONF_FREQUENCY: self._frequency,
                CONF_SPEED_COUNT: self._speed_count,
                CONF_HAS_ON: has_on,
                CONF_HAS_LIGHT: has_light,
            }

            self._queue = [CMD_OFF]
            self._queue += [f"speed_{i}" for i in range(1, self._speed_count + 1)]
            if has_on:
                self._queue.append(CMD_ON)
            if has_light:
                self._queue.append(CMD_LIGHT)
            self._queue += [c["key"] for c in self._customs]
            return await self.async_step_next()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_TRANSMITTER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="radio_frequency")
                ),
                vol.Required(
                    CONF_FREQUENCY, default=str(DEFAULT_FREQUENCY)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=str(DEFAULT_FREQUENCY), label="433.92 MHz"
                            ),
                            selector.SelectOptionDict(
                                value="315000000", label="315 MHz"
                            ),
                        ]
                    )
                ),
                vol.Required(CONF_SPEED_COUNT, default=3): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(CONF_HAS_ON, default=False): selector.BooleanSelector(),
                vol.Required(CONF_HAS_LIGHT, default=False): selector.BooleanSelector(),
                vol.Required(CONF_DIRECT, default=False): selector.BooleanSelector(),
                vol.Optional(
                    CONF_CUSTOM_BUTTONS, default=""
                ): selector.TextSelector(
                    selector.TextSelectorConfig(multiline=True)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_next(self, user_input=None) -> ConfigFlowResult:
        """Advance to the next button to learn, or finish."""
        if not self._queue:
            return self.async_create_entry(
                title=self._data[CONF_NAME],
                data={
                    **self._data,
                    CONF_COMMANDS: self._commands,
                    CONF_CUSTOMS: self._customs,
                    CONF_DIRECT: self._direct,
                },
            )
        self._current_key = self._queue.pop(0)
        self._reset_learn_state()
        return await self.async_step_learn()

    async def _async_after_confirm(self) -> ConfigFlowResult:
        """Continue learning the queued buttons."""
        return await self.async_step_next()


class RfFanOptionsFlow(_LearnFlowMixin, OptionsFlow):
    """Re-learn existing buttons or add new ones after setup."""

    def __init__(self) -> None:
        """Initialise options state (config entry is read lazily)."""
        self._commands: dict[str, Any] | None = None
        self._customs: list[dict[str, str]] = []
        self._custom_names: dict[str, str] = {}
        self._transmitter: str = ""
        self._frequency: int = 0
        self._speed_count: int = 0
        self._direct: bool = False
        self._device: Any = None
        self._current_key: str | None = None
        self._task: Any = None
        self._pending: dict[str, Any] | None = None
        self._learn_error: str | None = None

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Show the main configure menu."""
        if self._commands is None:
            entry = self.config_entry
            self._commands = dict(entry.data[CONF_COMMANDS])
            self._customs = [dict(c) for c in entry.data.get(CONF_CUSTOMS, [])]
            self._custom_names = {c["key"]: c["name"] for c in self._customs}
            self._transmitter = entry.data[CONF_TRANSMITTER]
            self._frequency = entry.data[CONF_FREQUENCY]
            self._speed_count = entry.data.get(CONF_SPEED_COUNT, 0)
            self._direct = entry.data.get(CONF_DIRECT, False)

        devices = find_rf_devices(self.hass)
        if not devices:
            return self.async_abort(reason="no_rf_device")
        self._device = next(iter(devices.values()))

        return self.async_show_menu(
            step_id="init", menu_options=["relearn", "add", "finish"]
        )

    async def async_step_relearn(self, user_input=None) -> ConfigFlowResult:
        """Pick an existing button to re-learn."""
        if user_input is not None:
            self._current_key = user_input["button"]
            self._reset_learn_state()
            return await self.async_step_learn()
        options = [
            selector.SelectOptionDict(value=key, label=self._label(key))
            for key in self._commands
        ]
        return self.async_show_form(
            step_id="relearn",
            data_schema=vol.Schema(
                {
                    vol.Required("button"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_add(self, user_input=None) -> ConfigFlowResult:
        """Name and learn a brand-new custom button."""
        if user_input is not None:
            name = (user_input.get("name") or "").strip()
            if not name:
                return await self.async_step_init()
            taken = set(self._commands) | {c["key"] for c in self._customs}
            key = _unique_custom_key(name, taken)
            self._customs.append({"key": key, "name": name})
            self._custom_names[key] = name
            self._current_key = key
            self._reset_learn_state()
            return await self.async_step_learn()
        return self.async_show_form(
            step_id="add",
            data_schema=vol.Schema({vol.Required("name"): selector.TextSelector()}),
        )

    async def _async_after_confirm(self) -> ConfigFlowResult:
        """Return to the configure menu after keeping a code."""
        return await self.async_step_init()

    async def async_step_finish(self, user_input=None) -> ConfigFlowResult:
        """Persist the updated commands and reload the entry."""
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_COMMANDS: self._commands,
                CONF_CUSTOMS: self._customs,
                CONF_DIRECT: self._direct,
            },
        )
        return self.async_create_entry(title="", data={})
