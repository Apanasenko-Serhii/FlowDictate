"""Unit test for HotkeyListener's state machine with a fake keyboard backend.

The real `keyboard` library needs an interactive desktop session (synthetic
events aren't visible in headless/background runs), so we stub it and drive
the listener's logic directly — that's the part we actually wrote.
"""

import sys
import types
from pathlib import Path


class Event:
    def __init__(self, event_type, name):
        self.event_type = event_type
        self.name = name


class FakeKeyboard(types.ModuleType):
    """Minimal stand-in: tracks held keys and captures registered handlers."""

    def __init__(self):
        super().__init__("keyboard")
        self.held = set()
        self.single_press = {}
        self.single_release = {}
        self.hook_fn = None

    def is_pressed(self, key):
        return key in self.held

    def on_press_key(self, key, cb, suppress=False):
        self.single_press[key] = cb

    def on_release_key(self, key, cb, suppress=False):
        self.single_release[key] = cb

    def hook(self, cb):
        self.hook_fn = cb

    def unhook_all(self):
        pass

    # --- test driver: simulate a physical key going down / up --------------
    def down(self, key):
        self.held.add(key)
        if key in self.single_press:
            self.single_press[key](Event("down", key))
        if self.hook_fn:
            self.hook_fn(Event("down", key))

    def up(self, key):
        self.held.discard(key)
        if key in self.single_release:
            self.single_release[key](Event("up", key))
        if self.hook_fn:
            self.hook_fn(Event("up", key))


failures = []


def check(name, cond):
    print(f"{name}: {'PASS' if cond else 'FAIL'}")
    if not cond:
        failures.append(name)


def make_listener(hotkey, fake):
    sys.modules["keyboard"] = fake
    sys.path.insert(0, str(Path(__file__).parent))
    import importlib
    import flowdictate
    importlib.reload(flowdictate)
    events = []
    lst = flowdictate.HotkeyListener(
        hotkey, lambda: events.append("start"),
        lambda: events.append("stop"), suppress=False)
    return lst, events


# Case 1: single key
fk = FakeKeyboard()
_, ev = make_listener("right ctrl", fk)
fk.down("right ctrl")
check("[single] start on press", ev == ["start"])
fk.up("right ctrl")
check("[single] stop on release", ev == ["start", "stop"])

# Case 2: two-key combo, released by 2nd key
fk = FakeKeyboard()
_, ev = make_listener("ctrl+shift", fk)
fk.down("ctrl")
check("[combo] no start on partial", ev == [])
fk.down("shift")
check("[combo] start when full", ev == ["start"])
fk.up("shift")
check("[combo] stop on release of one key", ev == ["start", "stop"])
fk.up("ctrl")
check("[combo] no extra event on 2nd release", ev == ["start", "stop"])

# Case 3: three-key combo, released by 1st key
fk = FakeKeyboard()
_, ev = make_listener("ctrl+alt+space", fk)
fk.down("ctrl"); fk.down("alt")
check("[combo3] no start on 2 of 3", ev == [])
fk.down("space")
check("[combo3] start when all 3 held", ev == ["start"])
fk.up("ctrl")
check("[combo3] stop when first released", ev == ["start", "stop"])
fk.up("alt"); fk.up("space")

# Case 4: re-arm — second full press starts again
fk = FakeKeyboard()
_, ev = make_listener("ctrl+shift", fk)
fk.down("ctrl"); fk.down("shift"); fk.up("shift")
fk.down("shift")  # ctrl still held, shift again -> full combo
check("[rearm] second press starts again",
      ev == ["start", "stop", "start"])
fk.up("ctrl"); fk.up("shift")

print("SMOKE=PASS" if not failures else f"SMOKE=FAIL {failures}")
sys.exit(0 if not failures else 1)
