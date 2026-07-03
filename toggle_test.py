"""Unit test for HotkeyListener hold vs toggle mode (fake keyboard backend)."""

import sys
import types
from pathlib import Path


class FakeKb(types.ModuleType):
    def __init__(self):
        super().__init__("keyboard")
        self.held = set()
        self.press_cb = {}
        self.release_cb = {}
        self.hook_cb = None

    def is_pressed(self, k):
        return k in self.held

    def on_press_key(self, k, cb, suppress=False):
        self.press_cb[k] = cb

    def on_release_key(self, k, cb, suppress=False):
        self.release_cb[k] = cb

    def hook(self, cb):
        self.hook_cb = cb

    def unhook_all(self):
        pass

    class _E:
        def __init__(self, t, n):
            self.event_type = t
            self.name = n

    def down(self, k):
        self.held.add(k)
        if k in self.press_cb:
            self.press_cb[k](self._E("down", k))
        if self.hook_cb:
            self.hook_cb(self._E("down", k))

    def up(self, k):
        self.held.discard(k)
        if k in self.release_cb:
            self.release_cb[k](self._E("up", k))
        if self.hook_cb:
            self.hook_cb(self._E("up", k))


failures = []


def check(name, cond, got=None):
    print(f"{name}: {'PASS' if cond else 'FAIL'}" + (f"  got={got!r}" if not cond else ""))
    if not cond:
        failures.append(name)


def load():
    sys.path.insert(0, str(Path(__file__).parent))
    import importlib
    import flowdictate
    importlib.reload(flowdictate)
    return flowdictate


# --- HOLD mode (single key) ---
fk = FakeKb(); sys.modules["keyboard"] = fk
fd = load()
ev = []
hk = fd.HotkeyListener("right ctrl",
                       lambda: ev.append("start"), lambda: ev.append("stop"),
                       suppress=False, mode="hold",
                       on_toggle=lambda: ev.append("toggle"))
fk.down("right ctrl"); fk.up("right ctrl")
check("hold: start then stop", ev == ["start", "stop"], ev)

# --- TOGGLE mode (single key): tap on, tap off ---
fk = FakeKb(); sys.modules["keyboard"] = fk
fd = load()
ev = []
armed = {"on": False}


def on_start(): ev.append("start"); armed.__setitem__("on", True)
def on_stop(): ev.append("stop"); armed.__setitem__("on", False)
def on_toggle():
    (on_stop if armed["on"] else on_start)()


hk = fd.HotkeyListener("f9", on_start, on_stop, suppress=False,
                       mode="toggle", on_toggle=on_toggle)
fk.down("f9"); fk.up("f9")          # first tap -> start
check("toggle: first tap starts", ev == ["start"], ev)
fk.down("f9"); fk.up("f9")          # second tap -> stop
check("toggle: second tap stops", ev == ["start", "stop"], ev)
fk.down("f9"); fk.up("f9")          # third tap -> start again
check("toggle: third tap starts", ev == ["start", "stop", "start"], ev)

# --- TOGGLE mode (combo) ---
fk = FakeKb(); sys.modules["keyboard"] = fk
fd = load()
ev = []; armed = {"on": False}
hk = fd.HotkeyListener("alt+shift", on_start, on_stop, suppress=False,
                       mode="toggle", on_toggle=on_toggle)
fk.down("alt"); fk.down("shift")     # full combo -> tap 1 -> start
check("toggle combo: start on full press", ev == ["start"], ev)
fk.up("shift"); fk.up("alt")         # release: no stop in toggle
check("toggle combo: release does nothing", ev == ["start"], ev)
fk.down("alt"); fk.down("shift")     # tap 2 -> stop
check("toggle combo: second tap stops", ev == ["start", "stop"], ev)
fk.up("shift"); fk.up("alt")

print("SMOKE=PASS" if not failures else f"SMOKE=FAIL {failures}")
sys.exit(0 if not failures else 1)
