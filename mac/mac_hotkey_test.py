"""Unit test for MacHotkey + resolve_key_tokens using a fake pynput backend.

Runs on any OS (Windows CI included): stubs `pynput` so we exercise the
state machine and key resolver without a real Mac keyboard.
"""

import sys
import types
from pathlib import Path


# ---- fake pynput -----------------------------------------------------------
class _KeySentinel:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Key.{self.name}"


class Key:
    pass


for _n in ("ctrl", "ctrl_l", "ctrl_r", "shift", "shift_l", "shift_r",
           "alt", "alt_l", "alt_r", "cmd", "cmd_l", "cmd_r",
           "space", "esc", "tab", "caps_lock"):
    setattr(Key, _n, _KeySentinel(_n))
for _i in range(1, 21):
    setattr(Key, f"f{_i}", _KeySentinel(f"f{_i}"))


class KeyCode:
    def __init__(self, char):
        self.char = char

    @classmethod
    def from_char(cls, c):
        return cls(c)

    def __eq__(self, other):
        return isinstance(other, KeyCode) and other.char == self.char

    def __hash__(self):
        return hash(("KeyCode", self.char))

    def __repr__(self):
        return f"KeyCode({self.char!r})"


class Listener:
    """Captures callbacks; the test drives them via App.press/release."""
    last = None

    def __init__(self, on_press=None, on_release=None):
        self.on_press, self.on_release = on_press, on_release
        Listener.last = self

    def start(self):
        pass

    def stop(self):
        pass


fake_keyboard = types.ModuleType("pynput.keyboard")
fake_keyboard.Key = Key
fake_keyboard.KeyCode = KeyCode
fake_keyboard.Listener = Listener
fake_pynput = types.ModuleType("pynput")
fake_pynput.keyboard = fake_keyboard
sys.modules["pynput"] = fake_pynput
sys.modules["pynput.keyboard"] = fake_keyboard

# ---- load the module under test -------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))
import flowdictate_mac as fd  # noqa: E402

failures = []


def check(name, cond):
    print(f"{name}: {'PASS' if cond else 'FAIL'}")
    if not cond:
        failures.append(name)


def new(hotkey):
    events = []
    hk = fd.MacHotkey(hotkey, lambda: events.append("start"),
                      lambda: events.append("stop"))
    return hk, events, Listener.last


# resolver sanity
check("resolve right alt -> alt_r only",
      fd.resolve_key_tokens("right alt") == {Key.alt_r})
check("resolve ctrl -> both sides",
      fd.resolve_key_tokens("ctrl") == {Key.ctrl, Key.ctrl_l, Key.ctrl_r})
check("resolve letter v -> KeyCode",
      fd.resolve_key_tokens("v") == {KeyCode.from_char("v")})

# Case 1: single key (right alt) — press generic alt_r
_, ev, L = new("right alt")
L.on_press(Key.alt_r)
check("[right alt] start on press", ev == ["start"])
L.on_release(Key.alt_r)
check("[right alt] stop on release", ev == ["start", "stop"])

# Case 2: 'ctrl' matches either side (press left)
_, ev, L = new("ctrl")
L.on_press(Key.ctrl_l)
check("[ctrl] start on left ctrl", ev == ["start"])
L.on_release(Key.ctrl_l)
check("[ctrl] stop on release", ev == ["start", "stop"])

# Case 3: combo cmd+shift — start only when both held, stop on either release
_, ev, L = new("cmd+shift")
L.on_press(Key.cmd)
check("[cmd+shift] no start on partial", ev == [])
L.on_press(Key.shift_r)
check("[cmd+shift] start when both held", ev == ["start"])
L.on_release(Key.cmd)
check("[cmd+shift] stop when one released", ev == ["start", "stop"])
L.on_release(Key.shift_r)

# Case 4: 3-key combo cmd+alt+space, released by first
_, ev, L = new("cmd+alt+space")
L.on_press(Key.cmd); L.on_press(Key.alt_l)
check("[3combo] no start on 2/3", ev == [])
L.on_press(Key.space)
check("[3combo] start on all 3", ev == ["start"])
L.on_release(Key.cmd)
check("[3combo] stop on first release", ev == ["start", "stop"])
L.on_release(Key.alt_l); L.on_release(Key.space)

# Case 5: letter combo cmd+d, case-insensitive normalization
_, ev, L = new("cmd+d")
L.on_press(Key.cmd); L.on_press(KeyCode(char="D"))  # shifted char
check("[cmd+d] start with uppercase D normalized", ev == ["start"])
L.on_release(KeyCode(char="D"))
check("[cmd+d] stop on release", ev == ["start", "stop"])
L.on_release(Key.cmd)

# Case 6: re-arm
_, ev, L = new("cmd+shift")
L.on_press(Key.cmd); L.on_press(Key.shift); L.on_release(Key.shift)
L.on_press(Key.shift)
check("[rearm] second press starts again",
      ev == ["start", "stop", "start"])

print("SMOKE=PASS" if not failures else f"SMOKE=FAIL {failures}")
sys.exit(0 if not failures else 1)
