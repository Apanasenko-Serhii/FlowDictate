#!/bin/bash
# FlowDictate — run on macOS without building a .app (dev / quick-start mode).
# Double-click in Finder, OR run:  bash install_mac.command
# First run installs everything; later runs just start the app.
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 not found. Install it first:  brew install python@3.11"
  echo "Also:  brew install portaudio ffmpeg"
  read -r -p "Press Enter to close..."
  exit 1
fi

if [ ! -d .venv ]; then
  echo ">> First run: setting up (installs faster-whisper etc., ~1 GB)"
  "$PY" -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install faster-whisper sounddevice pynput pyobjc rumps
else
  source .venv/bin/activate
fi

echo ">> Starting FlowDictate. Hold your hotkey (default: right Option) and speak."
echo ">> If the hotkey/paste do nothing, grant permissions in:"
echo "   System Settings > Privacy & Security > Accessibility + Input Monitoring + Microphone"
python flowdictate_mac.py
