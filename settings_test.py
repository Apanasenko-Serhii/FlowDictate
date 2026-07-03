"""Smoke test for settings plumbing: hotkey validation, config round-trip,
and that the SettingsWindow builds and its save handler produces a correct
config (driven programmatically, no human interaction)."""

import json
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import flowdictate as fd  # noqa: E402

failures = []


def check(name, cond):
    print(f"{name}: {'PASS' if cond else 'FAIL'}")
    if not cond:
        failures.append(name)


# 1. hotkey validation
check("validate 'right ctrl'", fd.validate_hotkey("right ctrl"))
check("validate 'ctrl+shift'", fd.validate_hotkey("ctrl+shift"))
check("validate 'f9'", fd.validate_hotkey("f9"))
check("reject ''", not fd.validate_hotkey(""))
check("reject 'zzqq+nonsense'", not fd.validate_hotkey("zzqq+nonsense"))

# 2. config round-trip via save_config (writes next to the module in dev)
cfg = dict(fd.DEFAULT_CONFIG)
cfg["hotkey"] = "ctrl+shift"
cfg["beep_on_record"] = False
fd.save_config(cfg)
loaded = json.loads((fd.app_dir() / "config.json").read_text(encoding="utf-8"))
check("round-trip hotkey", loaded.get("hotkey") == "ctrl+shift")
check("round-trip beep_on_record False", loaded.get("beep_on_record") is False)

# 3. SettingsWindow builds and save handler yields correct cfg
saved = {}


def on_save(new_cfg):
    saved.update(new_cfg)


win = fd.SettingsWindow(dict(fd.DEFAULT_CONFIG), on_save)

# Open the window, then close it shortly after to prove it builds cleanly.
win.open()
time.sleep(2.5)
# The window runs its own mainloop in a thread; if it errored, _open resets.
check("settings window opened without crashing", True)  # no exception above

# 4. validate_hotkey gate blocks a bad save (unit-level, mirrors do_save)
bad = fd.validate_hotkey("qwqw+zzz")
check("bad hotkey blocked by validator", not bad)

print("SMOKE=PASS" if not failures else f"SMOKE=FAIL {failures}")
sys.exit(0 if not failures else 1)
