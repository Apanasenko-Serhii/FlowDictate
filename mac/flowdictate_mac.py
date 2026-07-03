"""FlowDictate for macOS — local push-to-talk dictation.

Hold a hotkey, speak, release — the recognized text is pasted into the
active app. Engine: faster-whisper (CPU / Apple Accelerate). Fully offline.

macOS port of the Windows app. System pieces are swapped for Mac-native
tools: pynput (global hotkey), pbcopy + osascript (paste), rumps (menu-bar
icon), afplay (sounds).

STATUS: written against documented APIs but NOT yet run on a real Mac —
needs a live Mac test (see docs/INSTRUCTION_MAC.md). Requires macOS
permissions: Microphone, Accessibility, Input Monitoring.
"""

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

APP_NAME = "FlowDictate"
SAMPLE_RATE = 16000

DEFAULT_CONFIG = {
    "hotkey": "right alt",       # right Option (⌥) — easy to hold, rarely used
    "model": "large-v3-turbo",
    "language": "auto",          # auto | uk | en | ...
    "beam_size": 2,
    "min_seconds": 0.3,
    "sounds": True,              # master switch for all sounds
    "beep_on_record": False,     # sound when recording STARTS (off by default)
    "initial_prompt": (
        "Диктування українською. Термінологія: ЛДСП, МДФ, кромка, фурнітура "
        "Blum, Базіс-Мебельщик, корпус, фасад, тумба, шафа, стільниця, антресоль."
    ),
}

SOUND_START = "/System/Library/Sounds/Tink.aiff"
SOUND_DONE = "/System/Library/Sounds/Pop.aiff"
SOUND_ERROR = "/System/Library/Sounds/Basso.aiff"

# Menu-bar status glyphs
GLYPH = {
    "loading": "◌",
    "ready": "🟢",
    "recording": "🔴",
    "busy": "🟡",
    "error": "⚠️",
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Inside a .app bundle: config/log live next to the bundle
        return Path(sys.executable).resolve().parent
    return Path(__file__).parent


def data_dir() -> Path:
    d = Path.home() / "Library" / "Application Support" / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging() -> logging.Logger:
    log = logging.getLogger(APP_NAME)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(data_dir() / "flowdictate.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log


log = setup_logging()


def load_config() -> dict:
    path = app_dir() / "config.json"
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            log.error("Bad config.json, using defaults: %s", e)
    else:
        try:
            path.write_text(
                json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass  # read-only location inside a bundle is fine
    return cfg


class Beeper:
    def __init__(self, enabled: bool, on_record: bool = False):
        self.enabled = enabled
        self.on_record = on_record

    def _play(self, path: str) -> None:
        if not self.enabled:
            return
        try:
            subprocess.Popen(
                ["afplay", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def start(self):
        if self.on_record:
            self._play(SOUND_START)

    def done(self):
        self._play(SOUND_DONE)

    def error(self):
        self._play(SOUND_ERROR)


class Recorder:
    """Persistent input stream; frames are kept only while recording."""

    def __init__(self):
        import numpy as np
        import sounddevice as sd
        self._np = np
        self._frames = []
        self._recording = False
        self._lock = threading.Lock()
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        if self._recording:
            with self._lock:
                self._frames.append(indata.copy())

    def start(self):
        with self._lock:
            self._frames = []
        self._recording = True

    def stop(self):
        self._recording = False
        with self._lock:
            frames = self._frames
            self._frames = []
        if not frames:
            return self._np.zeros(0, dtype="float32")
        return self._np.concatenate(frames).flatten()

    def close(self):
        self._stream.stop()
        self._stream.close()


class Paster:
    """Paste text into the active app via pbcopy + Cmd+V (osascript)."""

    def paste(self, text: str) -> None:
        old = self._get_clipboard()
        self._set_clipboard(text)
        time.sleep(0.05)
        subprocess.run([
            "osascript", "-e",
            'tell application "System Events" to keystroke "v" using command down',
        ], check=False)

        def restore():
            time.sleep(0.8)
            if old is not None:
                self._set_clipboard(old)

        threading.Thread(target=restore, daemon=True).start()

    @staticmethod
    def _get_clipboard():
        try:
            r = subprocess.run(["pbpaste"], capture_output=True)
            return r.stdout
        except Exception:
            return None

    @staticmethod
    def _set_clipboard(data) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(data)
        except Exception:
            pass


def resolve_key_tokens(name: str):
    """Map a config key name to the set of pynput keys that satisfy it.

    Handles left/right modifier ambiguity by accepting either side unless
    a side is explicitly requested (e.g. 'right alt').
    """
    from pynput.keyboard import Key, KeyCode
    name = name.strip().lower()
    groups = {
        "ctrl": {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
        "control": {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
        "shift": {Key.shift, Key.shift_l, Key.shift_r},
        "alt": {Key.alt, Key.alt_l, Key.alt_r},
        "option": {Key.alt, Key.alt_l, Key.alt_r},
        "opt": {Key.alt, Key.alt_l, Key.alt_r},
        "cmd": {Key.cmd, Key.cmd_l, Key.cmd_r},
        "command": {Key.cmd, Key.cmd_l, Key.cmd_r},
        "win": {Key.cmd, Key.cmd_l, Key.cmd_r},
        "space": {Key.space},
        "esc": {Key.esc},
        "tab": {Key.tab},
        "caps lock": {Key.caps_lock},
        "capslock": {Key.caps_lock},
    }
    sided = {
        "right ctrl": {Key.ctrl_r}, "left ctrl": {Key.ctrl_l},
        "right shift": {Key.shift_r}, "left shift": {Key.shift_l},
        "right alt": {Key.alt_r}, "left alt": {Key.alt_l},
        "right option": {Key.alt_r}, "left option": {Key.alt_l},
        "right cmd": {Key.cmd_r}, "left cmd": {Key.cmd_l},
        "right command": {Key.cmd_r}, "left command": {Key.cmd_l},
    }
    if name in sided:
        return sided[name]
    if name in groups:
        return groups[name]
    # function keys f1..f20
    if name.startswith("f") and name[1:].isdigit():
        return {getattr(Key, name)}
    # single character
    if len(name) == 1:
        return {KeyCode.from_char(name)}
    raise ValueError(f"Unknown hotkey token: {name!r}")


class MacHotkey:
    """Push-to-talk trigger for a single key or a combo like 'cmd+shift'.

    Starts when all combo keys are held, stops when any is released.
    """

    def __init__(self, hotkey: str, on_start, on_stop):
        from pynput import keyboard
        self.on_start, self.on_stop = on_start, on_stop
        self.parts = [resolve_key_tokens(p)
                      for p in hotkey.split("+") if p.strip()]
        if not self.parts:
            raise ValueError(f"Empty hotkey: {hotkey!r}")
        self._held = set()
        self._active = False
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def _norm(self, key):
        # Compare character keys by char so KeyCode identity holds
        from pynput.keyboard import KeyCode
        if isinstance(key, KeyCode) and key.char:
            return KeyCode.from_char(key.char.lower())
        return key

    def _satisfied(self):
        return all(any(k in part for k in self._held) for part in self.parts)

    def _on_press(self, key):
        self._held.add(self._norm(key))
        if not self._active and self._satisfied():
            self._active = True
            self.on_start()

    def _on_release(self, key):
        self._held.discard(self._norm(key))
        if self._active and not self._satisfied():
            self._active = False
            self.on_stop()

    def stop(self):
        try:
            self._listener.stop()
        except Exception:
            pass


class Engine:
    """faster-whisper wrapper. On Mac this runs on CPU (int8)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = None
        self.device = "cpu"

    def load(self) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        from faster_whisper import WhisperModel
        name = self.cfg["model"]
        root = str(data_dir() / "models")
        last_err = None
        for local_only in (True, False):
            try:
                log.info("Loading model %s on cpu/int8 (local_only=%s)",
                         name, local_only)
                model = WhisperModel(
                    name, device="cpu", compute_type="int8",
                    download_root=root, local_files_only=local_only,
                )
                self._warmup(model)
                self.model = model
                log.info("Model ready on cpu")
                return
            except Exception as e:
                last_err = e
                log.error("Load (local_only=%s) failed: %s", local_only, e)
        raise RuntimeError(f"Model load failed: {last_err}")

    @staticmethod
    def _warmup(model) -> None:
        import numpy as np
        audio = np.zeros(SAMPLE_RATE // 2, dtype="float32")
        list(model.transcribe(audio, beam_size=1, language="en")[0])

    def transcribe(self, audio) -> str:
        lang = self.cfg["language"]
        segments, info = self.model.transcribe(
            audio,
            language=None if lang == "auto" else lang,
            beam_size=int(self.cfg["beam_size"]),
            vad_filter=True,
            initial_prompt=self.cfg["initial_prompt"] or None,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Transcribed (%s, %.1fs): %r",
                 getattr(info, "language", "?"), len(audio) / SAMPLE_RATE, text)
        return text


class App:
    def __init__(self):
        import rumps
        self.rumps = rumps
        self.cfg = load_config()
        self.beeper = Beeper(bool(self.cfg["sounds"]),
                             bool(self.cfg.get("beep_on_record", False)))
        self.engine = Engine(self.cfg)
        self.recorder = None
        self.paster = Paster()
        self.hotkey = None
        self.jobs = queue.Queue()
        self._armed = False
        self._quitting = False

        self.tray = rumps.App(APP_NAME, title=GLYPH["loading"],
                              quit_button=None)
        self.tray.menu = [rumps.MenuItem("Вихід", callback=self._menu_quit)]

    # --- state display -----------------------------------------------------
    def set_state(self, state: str):
        try:
            self.tray.title = GLYPH.get(state, "?")
        except Exception:
            pass

    # --- hotkey handlers ---------------------------------------------------
    def _on_start(self):
        if self.engine.model is None or self.recorder is None:
            return
        self._armed = True
        self.recorder.start()
        self.beeper.start()
        self.set_state("recording")

    def _on_stop(self):
        if not self._armed:
            return
        self._armed = False
        audio = self.recorder.stop()
        self.set_state("busy")
        self.jobs.put(audio)

    # --- worker ------------------------------------------------------------
    def _worker(self):
        while True:
            audio = self.jobs.get()
            if audio is None:
                return
            try:
                if len(audio) < SAMPLE_RATE * float(self.cfg["min_seconds"]):
                    log.info("Clip too short, ignored")
                else:
                    text = self.engine.transcribe(audio)
                    if text:
                        self.paster.paste(text)
                        self.beeper.done()
            except Exception as e:
                log.exception("Job failed: %s", e)
                self.beeper.error()
            finally:
                if not self._quitting:
                    self.set_state("ready")

    # --- startup -----------------------------------------------------------
    def _startup(self):
        try:
            self.engine.load()
            self.recorder = Recorder()
            self.hotkey = MacHotkey(
                self.cfg["hotkey"], self._on_start, self._on_stop)
            self.set_state("ready")
            log.info("Ready: hotkey=%r device=%s",
                     self.cfg["hotkey"], self.engine.device)
        except Exception as e:
            log.exception("Startup failed: %s", e)
            self.set_state("error")
            self.beeper.error()

    def _menu_quit(self, _sender):
        self._quitting = True
        self.jobs.put(None)
        if self.hotkey:
            self.hotkey.stop()
        if self.recorder:
            self.recorder.close()
        self.rumps.quit_application()

    def run(self):
        threading.Thread(target=self._startup, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()
        self.tray.run()  # blocks on the main thread (required by rumps)


def main():
    log.info("=== %s (macOS) starting ===", APP_NAME)
    App().run()
    log.info("=== %s stopped ===", APP_NAME)


if __name__ == "__main__":
    main()
