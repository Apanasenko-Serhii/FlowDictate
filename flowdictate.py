"""FlowDictate — local push-to-talk dictation for Windows.

Hold a hotkey, speak, release — the recognized text is pasted into the
active window. Engine: faster-whisper (GPU float16, CPU int8 fallback).
Fully offline, no word limits.
"""

import json
import logging
import queue
import re
import sys
import threading
import time
from pathlib import Path

APP_NAME = "FlowDictate"
SAMPLE_RATE = 16000

DEFAULT_CONFIG = {
    "hotkey": "right ctrl",
    "hotkey_mode": "hold",       # hold = record while held; toggle = tap on/off
    "suppress_hotkey": True,
    "model": "large-v3-turbo",
    "device": "auto",            # auto -> try cuda, fall back to cpu
    "language": "auto",          # auto | uk | en | ...
    "beam_size": 5,              # higher = more accurate (v2 tuning)
    "min_seconds": 0.3,
    "sounds": True,              # master switch for all sounds
    "beep_on_record": False,     # short beep when recording STARTS (off by default)
    "initial_prompt": (
        "Диктування українською. Термінологія: ЛДСП, МДФ, кромка, фурнітура "
        "Blum, Базіс-Мебельщик, корпус, фасад, тумба, шафа, стільниця, антресоль."
    ),
    # --- v2 ---
    "vocabulary": [],            # user terms/names -> biases recognition
    "voice_punctuation": True,   # "кома"/"крапка"/"з нового рядка" -> symbols
    "cleanup": False,            # AI cleanup via local LLM (off until model ready)
    "cleanup_endpoint": "http://localhost:11434/v1",   # Ollama (OpenAI-compatible)
    "cleanup_model": "qwen2.5:7b",   # quality default; "qwen2.5:3b" = faster/lighter
    "cleanup_style": "light",    # light | full
    "cleanup_timeout": 20,
    "preview": False,            # show a preview/edit window before pasting
    "history_size": 50,          # keep last N dictations
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

    def undo(self):
        """Undo the last insertion in the active app (Ctrl+Z)."""
        import keyboard
        keyboard.send("ctrl+z")

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

    Modes:
      hold   - record while the key/combo is held (default).
      toggle - tap once to start, tap again to stop (comfortable for long
               dictations: no need to keep a key pressed).
    """

    def __init__(self, hotkey: str, on_start, on_stop, suppress: bool,
                 mode: str = "hold", on_toggle=None):
        import keyboard
        self._kb = keyboard
        self.on_start, self.on_stop = on_start, on_stop
        self.on_toggle = on_toggle or (lambda: None)
        self.mode = mode
        self._engaged = False   # key/combo physically held right now
        self.parts = [p.strip() for p in hotkey.split("+") if p.strip()]
        if not self.parts:
            raise ValueError(f"Empty hotkey: {hotkey!r}")
        if len(self.parts) == 1:
            keyboard.on_press_key(self.parts[0], self._press, suppress=suppress)
            keyboard.on_release_key(self.parts[0], self._release,
                                    suppress=suppress)
        else:
            keyboard.hook(self._event)

    def _engage(self):
        if self._engaged:
            return
        self._engaged = True
        if self.mode == "toggle":
            self.on_toggle()      # flip recording on each tap
        else:
            self.on_start()

    def _disengage(self):
        if not self._engaged:
            return
        self._engaged = False
        if self.mode != "toggle":
            self.on_stop()        # hold mode: release stops recording

    def _press(self, _event):
        self._engage()

    def _release(self, _event):
        self._disengage()

    def _event(self, event):
        if event.event_type == "down":
            if not self._engaged and all(
                    self._kb.is_pressed(p) for p in self.parts):
                self._engage()
        elif event.event_type == "up" and self._engaged:
            if any(not self._kb.is_pressed(p) for p in self.parts):
                self._disengage()

    def unhook(self):
        self._kb.unhook_all()


# --- text processing (v2) --------------------------------------------------

# Order matters: multi-word phrases before single words.
_VOICE_PUNCT = [
    (r"\bновий абзац\b", "\n\n"),
    (r"\bз нового абзацу\b", "\n\n"),
    (r"\bз нового рядка\b", "\n"),
    (r"\bновий рядок\b", "\n"),
    (r"\bкрапка з комою\b", ";"),
    (r"\bзнак питання\b", "?"),
    (r"\bзнак запитання\b", "?"),
    (r"\bзнак оклику\b", "!"),
    (r"\bтри крапки\b", "…"),
    (r"\bдвокрапка\b", ":"),
    (r"\bтире\b", " — "),
    (r"\bкома\b", ","),
    (r"\bкрапка\b", "."),
]

_DELETE_CMDS = {"видали останнє", "видалити останнє", "стерти останнє",
                "видали", "скасувати"}


def detect_command(text: str):
    """Return a command name if the whole utterance is a command, else None."""
    t = re.sub(r"[.\s]+$", "", (text or "").strip().lower())
    if t in _DELETE_CMDS:
        return "undo"
    return None


def apply_voice_punctuation(text: str) -> str:
    """Turn spoken 'кома'/'крапка'/'з нового рядка' into real symbols."""
    if not text:
        return text
    out = text
    for pat, rep in _VOICE_PUNCT:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    out = re.sub(r"[ \t]+([,.:;!?…])", r"\1", out)      # no space before
    out = re.sub(r"([,.:;!?…])(?=[^\s\d])", r"\1 ", out)  # space after if glued
    out = re.sub(r"[ \t]*\n[ \t]*", "\n", out)          # tidy around newlines
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def build_initial_prompt(cfg: dict):
    """Base prompt plus the user's vocabulary, to bias recognition."""
    base = (cfg.get("initial_prompt") or "").strip()
    vocab = [v.strip() for v in (cfg.get("vocabulary") or []) if v.strip()]
    if vocab:
        base = (base + " Власні назви: " + ", ".join(vocab) + ".").strip()
    return base or None


_CLEANUP_LIGHT = (
    "Ти коректор тексту, продиктованого голосом. Зроби РІВНО дві речі: "
    "(1) прибери слова-паразити (еее, ммм, ну, як би, типу, коротше); "
    "(2) розстав пунктуацію та великі літери. "
    "СУВОРО ЗАБОРОНЕНО: перекладати текст, змінювати мову, додавати чи "
    "видаляти слова, міняти їх порядок або зміст, вживати ієрогліфи чи "
    "символи інших мов. Збережи кожне авторське слово тією ж мовою. "
    "Поверни ЛИШЕ виправлений текст, без пояснень і без лапок.\n"
    "Приклад вхід: ну значить треба купити матеріал і порізати його\n"
    "Приклад вихід: Значить, треба купити матеріал і порізати його."
)
_CLEANUP_FULL = (
    "Ти редактор. Причеши продиктований текст: пунктуація, великі літери, "
    "граматика, поділ на речення й абзаци, за потреби оформи списки. Збережи "
    "зміст і мову оригіналу. Поверни ЛИШЕ готовий текст, без пояснень."
)


class Cleaner:
    """Optional AI cleanup via a local OpenAI-compatible endpoint (Ollama /
    LM Studio). Any failure falls back to the raw text — never blocks."""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def cleanup(self, text: str) -> str:
        if not text or not self.cfg.get("cleanup"):
            return text
        import urllib.request
        style = self.cfg.get("cleanup_style", "light")
        system = _CLEANUP_FULL if style == "full" else _CLEANUP_LIGHT
        vocab = [v.strip() for v in (self.cfg.get("vocabulary") or [])
                 if v.strip()]
        if vocab:
            system += (" Не змінюй написання власних назв: "
                       + ", ".join(vocab) + ".")
        body = json.dumps({
            "model": self.cfg.get("cleanup_model", "qwen2.5:3b"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": 0 if style == "light" else 0.3,
            "stream": False,
        }).encode("utf-8")
        url = self.cfg.get("cleanup_endpoint",
                           "http://localhost:11434/v1").rstrip("/")
        req = urllib.request.Request(
            url + "/chat/completions", data=body,
            headers={"Content-Type": "application/json"})
        try:
            timeout = float(self.cfg.get("cleanup_timeout", 20))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            out = data["choices"][0]["message"]["content"].strip()
            out = self._unwrap(out)
            log.info("Cleanup ok (%s): %r -> %r", style, text, out)
            return out or text
        except Exception as e:
            log.error("Cleanup failed, using raw text: %s", e)
            return text

    @staticmethod
    def _unwrap(s: str) -> str:
        s = s.strip()
        # strip a single pair of wrapping quotes/backticks the model may add
        for q in ('"', "'", "`", "«"):
            if s.startswith(q):
                s = s[1:]
                break
        for q in ('"', "'", "`", "»"):
            if s.endswith(q):
                s = s[:-1]
                break
        return s.strip()


class History:
    """Keeps the last N dictations, persisted next to the app data."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.path = data_dir() / "history.json"
        self.items = []
        try:
            if self.path.exists():
                self.items = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.items = []

    def add(self, text: str) -> None:
        if not text:
            return
        self.items.insert(0, text)
        n = int(self.cfg.get("history_size", 50))
        self.items = self.items[:n]
        try:
            self.path.write_text(
                json.dumps(self.items, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            log.error("History save failed: %s", e)

    def recent(self, k: int = 10):
        return self.items[:k]


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
            vad_parameters=dict(speech_pad_ms=400),
            initial_prompt=build_initial_prompt(self.cfg),
            condition_on_previous_text=False,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Transcribed (%s, %.1fs audio): %r",
                 getattr(info, "language", "?"), len(audio) / SAMPLE_RATE, text)
        return text


def find_logo():
    """Locate the branded icon (bundled in frozen mode, else in assets/)."""
    names = ["icon.png"]
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys._MEIPASS) / "assets")
        roots.append(Path(sys.executable).parent / "assets")
    roots.append(Path(__file__).parent / "assets")
    for r in roots:
        for n in names:
            p = r / n
            if p.exists():
                return p
    return None


def set_window_icon(root):
    try:
        import tkinter as tk
        p = find_logo()
        if p:
            root._icon_img = tk.PhotoImage(file=str(p))
            root.iconphoto(True, root._icon_img)
    except Exception:
        pass


def _startup_lnk() -> Path:
    import os
    return (Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows"
            / "Start Menu" / "Programs" / "Startup" / f"{APP_NAME}.lnk")


def is_autostart_enabled() -> bool:
    try:
        return _startup_lnk().exists()
    except Exception:
        return False


def set_autostart(enable: bool) -> None:
    """Create/remove a Startup shortcut so the app launches with Windows."""
    import subprocess
    lnk = _startup_lnk()
    try:
        if enable:
            target = sys.executable
            work = str(Path(target).parent)
            ps = (
                "$s = New-Object -ComObject WScript.Shell; "
                f"$l = $s.CreateShortcut('{lnk}'); "
                f"$l.TargetPath = '{target}'; "
                f"$l.WorkingDirectory = '{work}'; $l.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           creationflags=0x08000000, timeout=15)
            log.info("Autostart enabled")
        elif lnk.exists():
            lnk.unlink()
            log.info("Autostart disabled")
    except Exception as e:
        log.error("Autostart change failed: %s", e)


class Overlay:
    """A small floating 'recording' pill near the bottom of the screen,
    shown while dictating (like Wispr). Runs its own Tk root in a thread."""

    def __init__(self):
        self._cmd = queue.Queue()
        self._root = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            import tkinter as tk
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            try:
                root.attributes("-alpha", 0.96)
            except Exception:
                pass
            BG = "#20242C"
            root.configure(bg=BG)
            frame = tk.Frame(root, bg=BG)
            frame.pack()
            self._dot = tk.Canvas(frame, width=14, height=14, bg=BG,
                                  highlightthickness=0)
            self._dot.pack(side="left", padx=(16, 8), pady=11)
            self._dot_id = self._dot.create_oval(2, 2, 12, 12,
                                                 fill="#E03B3B", outline="")
            self._lbl = tk.Label(frame, text="Запис", fg="#FFFFFF", bg=BG,
                                 font=("Segoe UI", 12))
            self._lbl.pack(side="left", padx=(0, 18), pady=11)
            root.withdraw()
            self._root = root
            self._pump()
            root.mainloop()
        except Exception as e:
            log.error("Overlay error: %s", e)

    def _pump(self):
        try:
            while True:
                cmd = self._cmd.get_nowait()
                if cmd[0] == "show":
                    self._lbl.config(text=cmd[1])
                    self._dot.itemconfig(self._dot_id, fill=cmd[2])
                    self._root.deiconify()
                    self._root.update_idletasks()
                    w = self._root.winfo_width()
                    sw = self._root.winfo_screenwidth()
                    sh = self._root.winfo_screenheight()
                    self._root.geometry(f"+{(sw - w) // 2}+{sh - 140}")
                    self._root.lift()
                elif cmd[0] == "hide":
                    self._root.withdraw()
        except queue.Empty:
            pass
        if self._root is not None:
            self._root.after(60, self._pump)

    def show(self, text: str, color: str):
        self._cmd.put(("show", text, color))

    def hide(self):
        self._cmd.put(("hide",))


class TrayIcon:
    COLORS = {
        "loading": (128, 128, 128),
        "ready": (46, 160, 67),
        "recording": (220, 53, 53),
        "busy": (240, 180, 0),
        "error": (200, 60, 40),
    }

    def __init__(self, on_quit, on_settings, on_history=None):
        import pystray
        self._pystray = pystray
        self._base = None
        p = find_logo()
        if p:
            try:
                from PIL import Image
                self._base = Image.open(p).convert("RGBA").resize(
                    (64, 64), Image.LANCZOS)
            except Exception:
                self._base = None
        items = [pystray.MenuItem("Налаштування…", lambda: on_settings())]
        if on_history is not None:
            items.append(pystray.MenuItem("Історія…", lambda: on_history()))
        items.append(pystray.MenuItem("Вихід", lambda: on_quit()))
        self.icon = pystray.Icon(
            APP_NAME, self._image("loading"), f"{APP_NAME} — завантаження…",
            menu=pystray.Menu(*items),
        )

    def _image(self, state: str):
        from PIL import Image, ImageDraw
        color = self.COLORS.get(state, (128, 128, 128))
        if self._base is not None:
            img = self._base.copy()
            d = ImageDraw.Draw(img)
            s = img.size[0]
            r = int(s * 0.20)
            box = (s - 2 * r - 3, s - 2 * r - 3, s - 3, s - 3)
            d.ellipse((box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3),
                      fill=(20, 22, 28, 255))
            d.ellipse(box, fill=color + (255,))
            return img
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=color + (255,))
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
        import customtkinter as ctk
        from tkinter import messagebox
        from PIL import Image
        cfg = self.cfg
        GOLD, CARD, SUB, BG = "#EDBB30", "#23262E", "#9AA0AA", "#171A20"
        try:
            ctk.set_appearance_mode("dark")
            root = ctk.CTk()
            root.title(f"{APP_NAME} — Налаштування")
            root.geometry("480x780")
            root.configure(fg_color=BG)
            set_window_icon(root)
            F = ctk.CTkFont

            header = ctk.CTkFrame(root, fg_color="transparent")
            header.pack(fill="x", padx=22, pady=(20, 6))
            lp = find_logo()
            if lp:
                try:
                    root._logo = ctk.CTkImage(Image.open(lp), size=(46, 46))
                    ctk.CTkLabel(header, image=root._logo, text="").pack(
                        side="left")
                except Exception:
                    pass
            tf = ctk.CTkFrame(header, fg_color="transparent")
            tf.pack(side="left", padx=14)
            ctk.CTkLabel(tf, text="FlowDictate",
                         font=F(size=20, weight="bold")).pack(anchor="w")
            ctk.CTkLabel(tf, text="Налаштування", text_color=SUB,
                         font=F(size=13)).pack(anchor="w")

            body = ctk.CTkScrollableFrame(root, fg_color="transparent")
            body.pack(fill="both", expand=True, padx=16, pady=(6, 4))

            def section(title):
                ctk.CTkLabel(body, text=title.upper(), text_color=GOLD,
                             font=F(size=11, weight="bold")).pack(
                    anchor="w", pady=(16, 6), padx=6)
                card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=14)
                card.pack(fill="x")
                return card

            def row(card, label):
                r = ctk.CTkFrame(card, fg_color="transparent")
                r.pack(fill="x", padx=14, pady=9)
                ctk.CTkLabel(r, text=label, font=F(size=13)).pack(side="left")
                return r

            def menu(parent, values):
                return ctk.CTkOptionMenu(
                    parent, values=values, width=150, fg_color="#2B2F38",
                    button_color=GOLD, button_hover_color="#d9a92a")

            def switch(parent, on):
                sw = ctk.CTkSwitch(parent, text="", progress_color=GOLD)
                (sw.select if on else sw.deselect)()
                sw.pack(side="right")
                return sw

            # Hotkey
            c = section("Гаряча клавіша")
            r = row(c, "Клавіша")
            hotkey_entry = ctk.CTkEntry(r, width=150)
            hotkey_entry.insert(0, cfg.get("hotkey", "right ctrl"))
            hotkey_entry.pack(side="right")
            capture_btn = ctk.CTkButton(r, text="Записати", width=96,
                                        fg_color="#333842",
                                        hover_color="#3d434f")
            capture_btn.pack(side="right", padx=8)

            capturing = {"on": False}

            def do_capture(*_):
                if capturing["on"]:
                    return
                capturing["on"] = True
                capture_btn.configure(text="Натисніть…", state="disabled")

                def worker():
                    combo = None
                    try:
                        import keyboard
                        combo = keyboard.read_hotkey(suppress=False)
                    except Exception as e:
                        log.error("Hotkey capture failed: %s", e)

                    def apply():
                        if combo:
                            hotkey_entry.delete(0, "end")
                            hotkey_entry.insert(0, combo)
                        capture_btn.configure(text="Записати", state="normal")
                        capturing["on"] = False

                    try:
                        hotkey_entry.after(0, apply)
                    except Exception:
                        capturing["on"] = False

                threading.Thread(target=worker, daemon=True).start()

            capture_btn.configure(command=do_capture)
            # click the field itself to record a key/combo
            hotkey_entry.bind("<Button-1>", do_capture)
            r = row(c, "Режим")
            mode_menu = menu(r, ["тримати", "перемикач"])
            mode_menu.set("тримати" if cfg.get("hotkey_mode", "hold") == "hold"
                          else "перемикач")
            mode_menu.pack(side="right")

            # Recognition
            c = section("Розпізнавання")
            lang_menu = menu(row(c, "Мова"),
                             ["auto", "uk", "en", "ru", "pl", "de"])
            lang_menu.set(cfg.get("language", "auto"))
            lang_menu.pack(side="right")
            model_menu = menu(row(c, "Модель"),
                              ["large-v3-turbo", "large-v3", "medium", "small",
                               "base"])
            model_menu.set(cfg.get("model", "large-v3-turbo"))
            model_menu.pack(side="right")
            ctk.CTkLabel(c, text="Словник (імена, терміни — по одному на рядок)",
                         text_color=SUB, font=F(size=12)).pack(
                anchor="w", padx=14, pady=(4, 2))
            vocab_box = ctk.CTkTextbox(c, height=80, corner_radius=8)
            vocab_box.insert("1.0", "\n".join(cfg.get("vocabulary") or []))
            vocab_box.pack(fill="x", padx=14, pady=(0, 12))

            # AI cleanup
            c = section("AI-чистка тексту")
            cleanup_sw = switch(row(c, "Увімкнути чистку (Ollama)"),
                                cfg.get("cleanup"))
            cmodel_menu = menu(row(c, "Модель чистки"),
                               ["qwen2.5:7b", "qwen2.5:3b"])
            cmodel_menu.set(cfg.get("cleanup_model", "qwen2.5:7b"))
            cmodel_menu.pack(side="right")
            cstyle_menu = menu(row(c, "Стиль"), ["light", "full"])
            cstyle_menu.set(cfg.get("cleanup_style", "light"))
            cstyle_menu.pack(side="right")

            # Punctuation & insert
            c = section("Пунктуація та вставка")
            vp_sw = switch(row(c, "Голосова пунктуація"),
                           cfg.get("voice_punctuation", True))
            preview_sw = switch(row(c, "Прев'ю перед вставкою"),
                                cfg.get("preview"))

            # Sound & system
            c = section("Звук та система")
            sounds_sw = switch(row(c, "Звук підтвердження вставки"),
                               cfg.get("sounds", True))
            beep_sw = switch(row(c, "Звук на початок запису"),
                             cfg.get("beep_on_record"))
            autostart_sw = switch(row(c, "Запускати разом з Windows"),
                                  is_autostart_enabled())

            def do_save():
                hk = hotkey_entry.get().strip()
                if not validate_hotkey(hk):
                    messagebox.showerror(
                        APP_NAME, f"Невідома клавіша або комбінація: {hk!r}")
                    return
                new = dict(self.cfg)
                new.update({
                    "hotkey": hk,
                    "hotkey_mode": ("hold" if mode_menu.get() == "тримати"
                                    else "toggle"),
                    "language": lang_menu.get(),
                    "model": model_menu.get(),
                    "vocabulary": [v.strip() for v in
                                   vocab_box.get("1.0", "end").splitlines()
                                   if v.strip()],
                    "cleanup": bool(cleanup_sw.get()),
                    "cleanup_model": cmodel_menu.get(),
                    "cleanup_style": cstyle_menu.get(),
                    "voice_punctuation": bool(vp_sw.get()),
                    "preview": bool(preview_sw.get()),
                    "sounds": bool(sounds_sw.get()),
                    "beep_on_record": bool(beep_sw.get()),
                })
                try:
                    set_autostart(bool(autostart_sw.get()))
                    self.on_save(new)
                except Exception as e:
                    log.exception("Apply settings failed: %s", e)
                    messagebox.showerror(APP_NAME, f"Помилка: {e}")
                    return
                root.destroy()

            def open_jar():
                import webbrowser
                webbrowser.open("https://send.monobank.ua/jar/5EsHj8Tyng")

            foot = ctk.CTkFrame(root, fg_color="transparent")
            foot.pack(fill="x", padx=20, pady=14)
            ctk.CTkButton(foot, text="💛 Підтримати проєкт",
                          fg_color="transparent", hover_color="#2B2F38",
                          text_color=GOLD, width=150, height=38,
                          command=open_jar).pack(side="left")
            ctk.CTkButton(foot, text="Зберегти", fg_color=GOLD,
                          text_color="#1A1A1A", hover_color="#d9a92a",
                          font=F(size=14, weight="bold"), height=38,
                          command=do_save).pack(side="right")
            ctk.CTkButton(foot, text="Скасувати", fg_color="#333842",
                          hover_color="#3d434f", height=38, width=110,
                          command=root.destroy).pack(side="right", padx=10)

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
        self.cleaner = Cleaner(self.cfg)
        self.history = History(self.cfg)
        self.overlay = Overlay()
        self.recorder = None
        self.paster = Paster()
        self.jobs = queue.Queue()
        self.tray = TrayIcon(on_quit=self.quit, on_settings=self.open_settings,
                             on_history=self.open_history)
        self.settings = SettingsWindow(self.cfg, self.apply_settings)
        self.listener = None
        self._armed = False
        self._quitting = False

    # --- settings ----------------------------------------------------------
    def open_settings(self):
        self.settings.cfg = self.cfg
        self.settings.open()

    def open_history(self):
        items = self.history.recent(20)

        def run():
            import tkinter as tk
            from tkinter import ttk
            try:
                root = tk.Tk()
                root.title(f"{APP_NAME} — Історія")
                set_window_icon(root)
                root.attributes("-topmost", True)
                if not items:
                    ttk.Label(root, text="Поки порожньо").pack(padx=20, pady=20)
                for it in items:
                    frm = ttk.Frame(root)
                    frm.pack(fill="x", padx=8, pady=2)
                    preview = (it[:70] + "…") if len(it) > 70 else it
                    ttk.Label(frm, text=preview.replace("\n", " "),
                              width=60, anchor="w").pack(side="left")
                    ttk.Button(
                        frm, text="Копіювати",
                        command=lambda t=it: Paster._set_clipboard(t)).pack(
                        side="right")
                root.mainloop()
            except Exception as e:
                log.exception("History window error: %s", e)

        threading.Thread(target=run, daemon=True).start()

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
            suppress=bool(self.cfg["suppress_hotkey"]),
            mode=self.cfg.get("hotkey_mode", "hold"),
            on_toggle=self._on_toggle)

    # --- hotkey handlers ---------------------------------------------------
    def _on_toggle(self):
        # toggle mode: tap starts recording, tap again stops it
        if self._armed:
            self._on_stop()
        else:
            self._on_start()

    def _on_start(self):
        if self.engine.model is None or self.recorder is None:
            return
        self._armed = True
        self.recorder.start()
        self.beeper.start()
        self.tray.set_state("recording", "запис…")
        self.overlay.show("Запис", "#E03B3B")

    def _on_stop(self):
        if not self._armed:
            return
        self._armed = False
        audio = self.recorder.stop()
        self.tray.set_state("busy", "розпізнаю…")
        self.overlay.show("Розпізнаю…", "#EDBB30")
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
                    self._process(self.engine.transcribe(audio))
            except Exception as e:
                log.exception("Job failed: %s", e)
                self.beeper.error()
            finally:
                self.overlay.hide()
                if not self._quitting:
                    self.tray.set_state(
                        "ready", f"готовий ({self.engine.device})")

    def _process(self, text: str):
        """Post-whisper pipeline: command -> punctuation -> cleanup ->
        (preview) -> paste + history."""
        if not text:
            return
        # spoken command (e.g. "видали останнє") short-circuits to an action
        if detect_command(text) == "undo":
            self.paster.undo()
            self.beeper.done()
            return
        if self.cfg.get("voice_punctuation", True):
            text = apply_voice_punctuation(text)
        if self.cfg.get("cleanup"):
            self.tray.set_state("busy", "чищу текст…")
            text = self.cleaner.cleanup(text)
        if not text:
            return
        if self.cfg.get("preview"):
            text = self._preview(text)
            if text is None:      # user cancelled
                return
        self.paster.paste(text)
        self.history.add(text)
        self.beeper.done()

    def _preview(self, text: str):
        """Blocking preview/edit dialog; returns edited text or None."""
        result = {"text": None}
        done = threading.Event()

        def run():
            import tkinter as tk
            from tkinter import ttk
            try:
                root = tk.Tk()
                root.title(f"{APP_NAME} — прев'ю")
                set_window_icon(root)
                root.attributes("-topmost", True)
                box = tk.Text(root, width=60, height=6, wrap="word")
                box.insert("1.0", text)
                box.pack(padx=10, pady=10)
                box.focus_force()

                def insert():
                    result["text"] = box.get("1.0", "end").rstrip("\n")
                    root.destroy()

                def cancel():
                    result["text"] = None
                    root.destroy()

                bar = ttk.Frame(root)
                bar.pack(pady=(0, 10))
                ttk.Button(bar, text="Вставити (Ctrl+Enter)",
                           command=insert).pack(side="left", padx=6)
                ttk.Button(bar, text="Скасувати (Esc)",
                           command=cancel).pack(side="left", padx=6)
                root.bind("<Control-Return>", lambda e: insert())
                root.bind("<Escape>", lambda e: cancel())
                root.protocol("WM_DELETE_WINDOW", cancel)
                root.mainloop()
            except Exception as e:
                log.exception("Preview error: %s", e)
            finally:
                done.set()

        threading.Thread(target=run, daemon=True).start()
        done.wait()
        return result["text"]

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
