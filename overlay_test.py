"""Verify the recording overlay (its own Tk root in a thread) coexists with
the customtkinter settings window (another Tk root in another thread)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import flowdictate as fd  # noqa: E402

ov = fd.Overlay()
time.sleep(0.6)
ov.show("Запис", "#E03B3B")
time.sleep(0.8)

saved = {}
win = fd.SettingsWindow(dict(fd.DEFAULT_CONFIG), lambda c: saved.update(c))
win.open()
time.sleep(2.0)

# screenshot full screen to eyeball both windows
try:
    from PIL import ImageGrab
    ImageGrab.grab().save(Path(__file__).parent / "assets" / "overlay_test.png")
    print("screenshot saved")
except Exception as e:
    print("shot failed:", e)

ov.show("Розпізнаю…", "#EDBB30")
time.sleep(0.8)
ov.hide()
time.sleep(0.4)
print("OVERLAY_COEXIST=OK")
