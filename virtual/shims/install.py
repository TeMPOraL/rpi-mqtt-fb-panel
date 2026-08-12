"""sys.modules pre-insertion of the hardware fakes.

Must run AFTER the environment is finalized (lcars_constants reads env at
import) and BEFORE anything imports panel modules. No sys.path shadowing is
used — the fakes are registered explicitly, so on-device runs can never be
affected by the presence of the virtual/ directory.
"""
import sys
import types
from typing import Callable

from PIL import Image

from virtual.shims.broker import MiniBroker

_PANEL_MODULES = ("mqtt_fb_panel", "framebuffer_utils", "event_log_mode", "clock_mode")


def install_shims(broker: MiniBroker,
                  frame_sink: Callable[[Image.Image], None],
                  fb_width: int, fb_height: int, fb_bpp: int,
                  touch_path: str, touch_abs_max: int,
                  paho_inline: bool = False) -> None:
    for name in _PANEL_MODULES:
        if name in sys.modules:
            raise RuntimeError(
                "install_shims() must run before panel modules are imported "
                "(found %r already in sys.modules)" % name)

    # Fake framebuffer — imports lcars_constants, so env must be final here.
    from virtual.shims import fake_framebuffer
    fake_framebuffer.configure(fb_width, fb_height, fb_bpp, frame_sink)
    sys.modules["framebuffer_utils"] = fake_framebuffer

    # Fake evdev with one registered virtual touchscreen.
    from virtual.shims import fake_evdev
    fake_evdev.register_device(path=touch_path, abs_max=touch_abs_max)
    sys.modules["evdev"] = fake_evdev

    # Fake paho: 'import paho.mqtt.client as mqtt' must bind our module.
    # paho_inline=True (Pyodide) replaces the network thread with explicit
    # pump_all() calls — see fake_paho docstring.
    from virtual.shims import fake_paho
    fake_paho.configure(broker, inline=paho_inline)
    paho_pkg = types.ModuleType("paho")
    paho_mqtt_pkg = types.ModuleType("paho.mqtt")
    paho_pkg.mqtt = paho_mqtt_pkg
    paho_mqtt_pkg.client = fake_paho
    sys.modules["paho"] = paho_pkg
    sys.modules["paho.mqtt"] = paho_mqtt_pkg
    sys.modules["paho.mqtt.client"] = fake_paho
