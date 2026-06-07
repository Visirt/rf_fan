"""Constants for the rf_fan integration."""

DOMAIN = "rf_fan"

# The Broadlink integration stores its devices under this domain in hass.data.
BROADLINK_DOMAIN = "broadlink"

# 433.92 MHz - the carrier almost every cheap RF fan/remote kit uses. It falls
# inside the Broadlink 433 band (433.05-434.79 MHz). Use 315_000_000 for the
# 315 MHz variant.
DEFAULT_FREQUENCY = 433_920_000

# Config entry / form keys.
CONF_NAME = "name"
CONF_TRANSMITTER = "transmitter"
CONF_FREQUENCY = "frequency"
CONF_SPEED_COUNT = "speed_count"
CONF_HAS_ON = "has_on_button"
CONF_HAS_LIGHT = "has_light"
CONF_CUSTOM_BUTTONS = "custom_buttons"  # raw text field in the form
CONF_CUSTOMS = "customs"  # stored list of {"key", "name"}
CONF_COMMANDS = "commands"
CONF_DIRECT = "direct_capture"  # skip the frequency sweep, listen at the set freq

# Learned-command keys. Speeds are "speed_1" .. "speed_<n>"; custom buttons are
# "custom_<slug>".
CMD_OFF = "off"
CMD_ON = "on"
CMD_LIGHT = "light"

# Times to repeat a de-noised consensus frame for noisy direct-capture remotes
# (e.g. the Mercator FRM97). Sweep-captured fans are sent as-is (repeat 0).
CLEAN_REPEAT = 10
