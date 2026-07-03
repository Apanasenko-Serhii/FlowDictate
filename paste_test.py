"""Smoke test: paste into a real focused window via clipboard + Ctrl+V.

Opens a tiny tkinter window, forces it to the foreground (verified via
win32), pastes Ukrainian text through the same Paster the app uses, then
checks the widget content and clipboard restoration. Keys are NOT sent
unless our window is confirmed foreground — so nothing leaks into other apps.
"""

import sys
import time
import tkinter as tk
from pathlib import Path

import keyboard
import win32gui

sys.path.insert(0, str(Path(__file__).parent))
from flowdictate import Paster  # noqa: E402

EXPECTED = "Привіт, це тест вставки FlowDictate!"
MARKER = "MARKER_BEFORE_PASTE"
TITLE = "FlowDictate paste test 7f3a"


def force_foreground(hwnd) -> bool:
    for _ in range(6):
        try:
            # A benign key event unlocks SetForegroundWindow for this process
            keyboard.press_and_release("alt")
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        time.sleep(0.15)
        if win32gui.GetForegroundWindow() == hwnd:
            return True
    return False


Paster._set_clipboard(MARKER)

root = tk.Tk()
root.title(TITLE)
root.attributes("-topmost", True)
text = tk.Text(root, width=60, height=4)
text.pack()
result = {}


def do_paste():
    root.update_idletasks()
    hwnd = win32gui.FindWindow(None, TITLE)
    if not hwnd or not force_foreground(hwnd):
        result["error"] = "could not take foreground; keys not sent"
        root.destroy()
        return
    text.focus_force()
    root.update()
    Paster().paste(EXPECTED)  # blocks ~0.4s; key event lands after return
    root.after(600, read_back)


def read_back():
    result["content"] = text.get("1.0", "end").strip()
    root.destroy()


root.after(800, do_paste)
root.mainloop()

time.sleep(1.2)  # let the background clipboard-restore finish
restored = Paster._get_clipboard()
print(f"PASTED={result.get('content')!r}")
print(f"ERROR={result.get('error')}")
print(f"CLIP_RESTORED={restored == MARKER}")
ok = result.get("content") == EXPECTED and restored == MARKER
print("SMOKE=PASS" if ok else "SMOKE=FAIL")
sys.exit(0 if ok else 1)
