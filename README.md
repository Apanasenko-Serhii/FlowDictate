# FlowDictate

Local, offline, unlimited **push-to-talk dictation** for Windows (and macOS,
from source). Hold a hotkey, speak, release — the recognized text is typed
into whatever window you're in. A free, private alternative to cloud dictation
tools: no word limits, and your audio never leaves your machine.

Powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
(OpenAI Whisper via CTranslate2). On an NVIDIA GPU it's near-instant
(~0.6 s for 6 s of speech on an RTX 4060 Ti); it falls back to CPU otherwise.

## Features

- 🎙 **Push-to-talk**: hold a key or combo, speak, release → text is pasted.
- 🔌 **Fully offline**: audio is transcribed on-device; nothing is uploaded.
- ♾ **No limits**: dictate as long as you want, free.
- ⌨️ **Configurable hotkey**: single key or combo (`right ctrl`, `ctrl+shift`,
  `ctrl+alt+space`, …) — via a settings window or `config.json`.
- 🌐 **Multilingual**: Ukrainian, English, and 90+ languages (auto-detect).
- 📖 **Custom vocabulary**: bias recognition toward your own terms/names.
- 🖥 **Runs in the tray/menu bar**, out of your way.

## Install (Windows)

1. Download `FlowDictate-Windows-x64.zip` from the
   [Releases](../../releases) page.
2. **Extract** the whole folder (don't copy files out of it) to e.g.
   `C:\FlowDictate`.
3. Run `FlowDictate.exe`. First launch downloads the model (~1.6 GB) once.
4. Wait for the tray icon to turn **green**, then hold **right Ctrl**, speak,
   release.

No runtime to install — the build is self-contained and works on any 64-bit
Windows PC (GPU or CPU). Full guide: [docs/INSTRUCTION_WINDOWS.md](docs/INSTRUCTION_WINDOWS.md).

## Install (macOS)

There's no prebuilt `.app` yet — build it on a Mac from the `mac/` folder
(a Windows binary can't be built for macOS). Two paths (quick-run or build a
`.app`) in [docs/INSTRUCTION_MAC.md](docs/INSTRUCTION_MAC.md) and
[mac/README_MAC.md](mac/README_MAC.md). Note: on Mac the engine runs on CPU
(CTranslate2 has no Metal backend).

## Settings

Open **Налаштування…** from the tray icon, or edit `config.json`:

| Key | Meaning | Examples |
|-----|---------|----------|
| `hotkey` | Push-to-talk key/combo | `right ctrl`, `ctrl+shift`, `f9` |
| `language` | Recognition language | `auto`, `uk`, `en` |
| `model` | Whisper model | `large-v3-turbo`, `medium`, `small` |
| `sounds` | Confirmation sound on paste | `true` / `false` |
| `beep_on_record` | Sound when recording starts | `true` / `false` (default off) |
| `initial_prompt` | Vocabulary hint (your terms/names) | free text |

## Build from source (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install faster-whisper sounddevice keyboard pystray pillow pywin32 nvidia-cublas-cu12 nvidia-cudnn-cu12 pyinstaller
.\build.ps1   # -> dist\FlowDictate\FlowDictate.exe
```

Run directly without building: `python flowdictate.py`.

## Tests

Logic that can be tested without a mic/GPU is covered:

```powershell
.\.venv\Scripts\python hotkey_test.py       # Windows hotkey state machine
.\.venv\Scripts\python settings_test.py     # settings + config round-trip
.\.venv\Scripts\python mac\mac_hotkey_test.py  # macOS hotkey logic (fake pynput)
```

## How it works

`hotkey → record (sounddevice) → faster-whisper transcribe → paste into the
active window (clipboard + Ctrl/Cmd+V)`. The model runs locally; the app only
holds audio in memory while you speak.

## 💛 Support the project

Everyone who wants to help with development — here's a Monobank jar:
**https://send.monobank.ua/jar/5EsHj8Tyng**

Усі, хто хоче допомогти в розвитку — банка Monobank:
**https://send.monobank.ua/jar/5EsHj8Tyng**

## Credits & license

- [OpenAI Whisper](https://github.com/openai/whisper) — MIT
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) /
  [CTranslate2](https://github.com/OpenNMT/CTranslate2)

Licensed under the [MIT License](LICENSE).
