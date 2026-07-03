"""FlowDictate — local push-to-talk dictation for Windows.

Hold a hotkey, speak, release — the recognized text is pasted into the
active window. Engine: faster-whisper (GPU float16, CPU int8 fallback).
Fully offline, no word limits.
"""

import json
import logging
import queue
import sys
import threading
import time
from pathlib import Path

APP_NAME = "FlowDictate"
SAMPLE_RATE = 16000

DEFAULT_CONFIG = {
    "hotkey": "right ctrl",
    "suppress_hotkey": True,
    "model": "large-v3-turbo",
    "device": "auto",            # auto -> try cuda, fall back to cpu
    "language": "auto",          # auto | uk | en | ...
    "beam_size": 2,
    "min_seconds": 0.3,
    "sounds": True,              # master switch for all sounds
    "beep_on_record": False,     # short beep when recording STARTS (off by default)
    "initial_prompt": (
        "Диктування українською. Термінологія: ЛДСП, МДФ, кромка, фурнітура "
        "Blum, Базіс-Мебельщик, корпус, фасад, тумба, шафа, стільниця, антресоль."
    ),
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def data_dir() -> Path:
    import os
    d = Path(os.environ.get("LOCALAPPDATA", str(app_dir()))) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging() -> logging.Logger:
    log = logging.getLogger(APP_NAME)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(app_dir() / "flowdictate.log", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if not getattr(sys, "frozen", False):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log


log = setup_logging()


def setup_cuda_dlls() -> None:
    """Make pip-installed cuBLAS/cuDNN visible to ctranslate2.

    Dev mode: site-packages/nvidia/*/bin. Frozen mode: DLLs are copied
    flat into _internal by build.ps1, which is already on the search path.
    """
    import os
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(Path(sys._MEIPASS))
    else:
        import sysconfig
        bases.append(Path(sysconfig.get_paths()["purelib"]))
    for base in bases:
        for bin_dir in sorted(base.glob("nvidia/*/bin")):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
            log.info("CUDA DLL dir added: %s", bin_dir)


def load_config() -> dict:
    path = app_dir() / "config.json"
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            log.error("Bad config.json, using defaults: %s", e)
    else:
        path.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cfg


class Beeper:
    def __init__(self, enabled: bool, on_record: bool = False):
        self.enabled = enabled
        self.on_record = on_record

    def _beep(self, freq: int, ms: int) -> None:
        if not self.enabled:
            return
        import winsound
        threading.Thread(
            target=winsound.Beep, args=(freq, ms), daemon=True
        ).start()

    def start(self):
        # Sound when recording begins — off by default (config: beep_on_record)
        if self.on_record:
            self._beep(880, 70)

    def done(self):
        self._beep(660, 70)

    def error(self):
        self._beep(220, 200)


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
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
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
    """Paste text into the active window via clipboard + Ctrl+V."""

    def paste(self, text: str) -> None:
        import keyboard
        old = self._get_clipboard()
        self._set_clipboard(text)
        time.sleep(0.05)
        keyboard.send("ctrl+v")

        def restore():
            # Give the target app time to read the clipboard before we
            # put the previous content back (slow apps race otherwise).
            time.sleep(0.8)
            if old is not None:
                self._set_clipboard(old)

        threading.Thread(target=restore, daemon=True).start()

    @staticmethod
    def _get_clipboard():
        import win32clipboard as wc
        try:
            wc.OpenClipboard()
            try:
                if wc.IsClipboardFormatAvailable(wc.CF_UNICODETEXT):
                    return wc.GetClipboardData(wc.CF_UNICODETEXT)
                return None
            finally:
                wc.CloseClipboard()
        except Exception:
            return None

    @staticmethod
    def _set_clipboard(text: str):
        import win32clipboard as wc
        for _ in range(3):
            try:
                wc.OpenClipboard()
                try:
                    wc.EmptyClipboard()
                    wc.SetClipboardData(wc.CF_UNICODETEXT, text)
                    return
                finally:
                    wc.CloseClipboard()
            except Exception:
                time.sleep(0.05)


class HotkeyListener:
    """Push-to-talk trigger: a single key or a combo like 'ctrl+shift+space'.

    Combo semantics: recording starts when ALL keys are held, stops when ANY
    of them is released. `suppress` applies to single-key hotkeys only —
    swallowing a modifier globally would break normal typing.
    """

    def __init__(self, hotkey: str, on_start, on_stop, suppress: bool):
        import keyboard
        self._kb = keyboard
        self.on_start, self.on_stop = on_start, on_stop
        self._active = False
        self.parts = [p.strip() for p in hotkey.split("+") if p.strip()]
        if not self.parts:
            raise ValueError(f"Empty hotkey: {hotkey!r}")
        if len(self.parts) == 1:
            keyboard.on_press_key(self.parts[0], self._press, suppress=suppress)
            keyboard.on_release_key(self.parts[0], self._release,
                                    suppress=suppress)
        else:
            keyboard.hook(self._event)

    def _press(self, _event):
        if not self._active:
            self._active = True
            self.on_start()

    def _release(self, _event):
        if self._active:
            self._active = False
            self.on_stop()

    def _event(self, event):
        if event.event_type == "down":
            if not self._active and all(
                    self._kb.is_pressed(p) for p in self.parts):
                self._press(event)
        elif event.event_type == "up" and self._active:
            if any(not self._kb.is_pressed(p) for p in self.parts):
                self._release(event)

    def unhook(self):
        self._kb.unhook_all()


class Engine:
    """faster-whisper wrapper with GPU -> CPU fallback."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = None
        self.device = "?"

    def load(self) -> None:
        import os
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        from faster_whisper import WhisperModel
        name = self.cfg["model"]
        root = str(data_dir() / "models")
        want = self.cfg["device"]
        attempts = []
        if want in ("auto", "cuda"):
            attempts.append(("cuda", "float16"))
        if want in ("auto", "cpu"):
            attempts.append(("cpu", "int8"))
        last_err = None
        for device, compute in attempts:
            # Offline-first: a cached model must load without any network
            # round-trip (HF hub revision checks can stall for minutes).
            for local_only in (True, False):
                try:
                    log.info("Loading model %s on %s/%s (local_only=%s)",
                             name, device, compute, local_only)
                    model = WhisperModel(
                        name, device=device, compute_type=compute,
                        download_root=root, local_files_only=local_only,
                    )
                    self._warmup(model)
                    self.model, self.device = model, device
                    log.info("Model ready on %s", device)
                    return
                except Exception as e:
                    last_err = e
                    log.error("Load on %s (local_only=%s) failed: %s",
                              device, local_only, e)
        raise RuntimeError(f"No usable device for model: {last_err}")

    @staticmethod
    def _warmup(model) -> None:
        """Exercise the full inference path (catches missing CUDA DLLs)."""
        import numpy as np
        audio = np.zeros(SAMPLE_RATE // 2, dtype="float32")
        segments, _ = model.transcribe(audio, beam_size=1, language="en")
        list(segments)

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
        log.info("Transcribed (%s, %.1fs audio): %r",
                 getattr(info, "language", "?"), len(audio) / SAMPLE_RATE, text)
        return text


class TrayIcon:
    COLORS = {
        "loading": (128, 128, 128),
        "ready": (46, 160, 67),
        "recording": (220, 53, 53),
        "busy": (240, 180, 0),
        "error": (0, 0, 0),
    }

    def __init__(self, on_quit, on_settings):
        import pystray
        self._pystray = pystray
        self.icon = pystray.Icon(
            APP_NAME, self._image("loading"), f"{APP_NAME} — завантаження…",
            menu=pystray.Menu(
                pystray.MenuItem("Налаштування…", lambda: on_settings()),
                pystray.MenuItem("Вихід", lambda: on_quit()),
            ),
        )

    def _image(self, state: str):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((8, 8, 56, 56), fill=self.COLORS[state] + (255,))
        return img

    def set_state(self, state: str, title: str):
        self.icon.icon = self._image(state)
        self.icon.title = f"{APP_NAME} — {title}"

    def run(self):
        self.icon.run()

    def stop(self):
        self.icon.stop()


def validate_hotkey(hotkey: str) -> bool:
    """True if the keyboard library can parse this hotkey string."""
    hotkey = (hotkey or "").strip()
    if not hotkey:
        return False
    try:
        import keyboard
        keyboard.parse_hotkey(hotkey)
        return True
    except Exception:
        return False


def save_config(cfg: dict) -> None:
    (app_dir() / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


class SettingsWindow:
    """A small tkinter settings dialog, opened from the tray menu.

    Runs in its own thread with its own Tk root so it never fights pystray
    for the main thread. On save it calls `on_save(new_cfg)`.
    """

    LANGUAGES = ["auto", "uk", "en", "ru", "pl", "de"]
    MODELS = ["large-v3-turbo", "large-v3", "medium", "small", "base"]

    def __init__(self, cfg: dict, on_save):
        self.cfg = cfg
        self.on_save = on_save
        self._open = False

    def open(self):
        if self._open:
            return
        self._open = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import tkinter as tk
        from tkinter import ttk, messagebox
        try:
            root = tk.Tk()
            root.title(f"{APP_NAME} — Налаштування")
            root.resizable(False, False)
            root.attributes("-topmost", True)
            pad = {"padx": 10, "pady": 6}
            row = 0

            ttk.Label(root, text="Гаряча клавіша").grid(
                column=0, row=row, sticky="w", **pad)
            hotkey_var = tk.StringVar(value=self.cfg.get("hotkey", "right ctrl"))
            entry = ttk.Entry(root, textvariable=hotkey_var, width=22)
            entry.grid(column=1, row=row, sticky="we", **pad)
            capture_btn = ttk.Button(root, text="Записати")
            capture_btn.grid(column=2, row=row, **pad)

            def do_capture():
                capture_btn.config(text="Натисніть…", state="disabled")

                def worker():
                    try:
                        import keyboard
                        combo = keyboard.read_hotkey(suppress=False)
                        hotkey_var.set(combo)
                    except Exception as e:
                        log.error("Hotkey capture failed: %s", e)
                    finally:
                        capture_btn.config(text="Записати", state="normal")

                threading.Thread(target=worker, daemon=True).start()

            capture_btn.config(command=do_capture)
            row += 1

            ttk.Label(root, text="(напр. right ctrl, ctrl+shift, f9)").grid(
                column=1, row=row, columnspan=2, sticky="w", padx=10)
            row += 1

            ttk.Label(root, text="Мова").grid(
                column=0, row=row, sticky="w", **pad)
            lang_var = tk.StringVar(value=self.cfg.get("language", "auto"))
            ttk.Combobox(root, textvariable=lang_var, values=self.LANGUAGES,
                         width=20, state="readonly").grid(
                column=1, row=row, columnspan=2, sticky="we", **pad)
            row += 1

            ttk.Label(root, text="Модель (потрібен перезапуск)").grid(
                column=0, row=row, sticky="w", **pad)
            model_var = tk.StringVar(
                value=self.cfg.get("model", "large-v3-turbo"))
            ttk.Combobox(root, textvariable=model_var, values=self.MODELS,
                         width=20, state="readonly").grid(
                column=1, row=row, columnspan=2, sticky="we", **pad)
            row += 1

            sounds_var = tk.BooleanVar(value=bool(self.cfg.get("sounds", True)))
            ttk.Checkbutton(root, text="Звук підтвердження вставки",
                            variable=sounds_var).grid(
                column=0, row=row, columnspan=3, sticky="w", **pad)
            row += 1

            beep_var = tk.BooleanVar(
                value=bool(self.cfg.get("beep_on_record", False)))
            ttk.Checkbutton(root, text="Звук на початок запису",
                            variable=beep_var).grid(
                column=0, row=row, columnspan=3, sticky="w", **pad)
            row += 1

            def do_save():
                hk = hotkey_var.get().strip()
                if not validate_hotkey(hk):
                    messagebox.showerror(
                        APP_NAME, f"Невідома клавіша або комбінація: {hk!r}")
                    return
                new = dict(self.cfg)
                new.update({
                    "hotkey": hk,
                    "language": lang_var.get(),
                    "model": model_var.get(),
                    "sounds": bool(sounds_var.get()),
                    "beep_on_record": bool(beep_var.get()),
                })
                try:
                    self.on_save(new)
                except Exception as e:
                    log.exception("Apply settings failed: %s", e)
                    messagebox.showerror(APP_NAME, f"Помилка: {e}")
                    return
                root.destroy()

            btns = ttk.Frame(root)
            btns.grid(column=0, row=row, columnspan=3, pady=10)
            ttk.Button(btns, text="Зберегти", command=do_save).pack(
                side="left", padx=6)
            ttk.Button(btns, text="Скасувати", command=root.destroy).pack(
                side="left", padx=6)

            root.update_idletasks()
            root.protocol("WM_DELETE_WINDOW", root.destroy)
            root.mainloop()
        except Exception as e:
            log.exception("Settings window error: %s", e)
        finally:
            self._open = False


class App:
    def __init__(self):
        self.cfg = load_config()
        self.beeper = Beeper(bool(self.cfg["sounds"]),
                             bool(self.cfg.get("beep_on_record", False)))
        self.engine = Engine(self.cfg)
        self.recorder = None
        self.paster = Paster()
        self.jobs = queue.Queue()
        self.tray = TrayIcon(on_quit=self.quit, on_settings=self.open_settings)
        self.settings = SettingsWindow(self.cfg, self.apply_settings)
        self.listener = None
        self._armed = False
        self._quitting = False

    # --- settings ----------------------------------------------------------
    def open_settings(self):
        self.settings.cfg = self.cfg
        self.settings.open()

    def apply_settings(self, new_cfg: dict):
        old_hotkey = self.cfg.get("hotkey")
        old_suppress = self.cfg.get("suppress_hotkey")
        self.cfg.update(new_cfg)
        save_config(self.cfg)
        # sounds apply immediately
        self.beeper.enabled = bool(self.cfg["sounds"])
        self.beeper.on_record = bool(self.cfg.get("beep_on_record", False))
        # language applies on next transcription (Engine reads cfg live)
        # rebind hotkey live if it changed
        if (self.cfg.get("hotkey") != old_hotkey
                or self.cfg.get("suppress_hotkey") != old_suppress):
            self._bind_hotkey()
        log.info("Settings applied: hotkey=%r sounds=%s beep_on_record=%s",
                 self.cfg.get("hotkey"), self.cfg["sounds"],
                 self.cfg.get("beep_on_record"))

    def _bind_hotkey(self):
        if self.listener:
            try:
                self.listener.unhook()
            except Exception:
                pass
        self.listener = HotkeyListener(
            self.cfg["hotkey"], self._on_start, self._on_stop,
            suppress=bool(self.cfg["suppress_hotkey"]))

    # --- hotkey handlers ---------------------------------------------------
    def _on_start(self):
        if self.engine.model is None or self.recorder is None:
            return
        self._armed = True
        self.recorder.start()
        self.beeper.start()
        self.tray.set_state("recording", "запис…")

    def _on_stop(self):
        if not self._armed:
            return
        self._armed = False
        audio = self.recorder.stop()
        self.tray.set_state("busy", "розпізнаю…")
        self.jobs.put(audio)

    # --- worker ------------------------------------------------------------
    def _worker(self):
        while True:
            audio = self.jobs.get()
            if audio is None:
                return
            try:
                if len(audio) < SAMPLE_RATE * float(self.cfg["min_seconds"]):
                    log.info("Clip too short (%.2fs), ignored",
                             len(audio) / SAMPLE_RATE)
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
                    self.tray.set_state(
                        "ready", f"готовий ({self.engine.device})")

    # --- startup / shutdown -------------------------------------------------
    def _startup(self):
        try:
            setup_cuda_dlls()
            self.engine.load()
            self.recorder = Recorder()
            self._bind_hotkey()
            self.tray.set_state("ready", f"готовий ({self.engine.device})")
            log.info("Ready: hotkey=%r device=%s",
                     self.cfg["hotkey"], self.engine.device)
        except Exception as e:
            log.exception("Startup failed: %s", e)
            self.tray.set_state("error", f"помилка: {e}")
            self.beeper.error()

    def quit(self):
        self._quitting = True
        self.jobs.put(None)
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        if self.recorder:
            self.recorder.close()
        self.tray.stop()

    def run(self):
        threading.Thread(target=self._startup, daemon=True).start()
        threading.Thread(target=self._worker, daemon=True).start()
        self.tray.run()  # blocks in the main thread


def ensure_single_instance() -> bool:
    import win32api
    import win32event
    import winerror
    handle = win32event.CreateMutex(None, False, f"Global\\{APP_NAME}Mutex")
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


def main():
    if not ensure_single_instance():
        log.warning("Another instance is running, exiting")
        return
    log.info("=== %s starting ===", APP_NAME)
    App().run()
    log.info("=== %s stopped ===", APP_NAME)


if __name__ == "__main__":
    main()
