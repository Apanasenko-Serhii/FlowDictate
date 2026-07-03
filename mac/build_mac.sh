#!/bin/bash
# Build FlowDictate.app on macOS.  Usage:  bash build_mac.sh
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
echo ">> Using $($PY --version)"

if [ ! -d .venv ]; then
  echo ">> Creating virtualenv"
  "$PY" -m venv .venv
fi
source .venv/bin/activate

echo ">> Installing dependencies (this pulls ~1 GB the first time)"
pip install --upgrade pip
pip install faster-whisper sounddevice pynput pyobjc rumps py2app

echo ">> Building .app"
rm -rf build dist
python setup_mac.py py2app

echo ""
echo ">> Done: $(pwd)/dist/FlowDictate.app"
echo ">> Drag it to /Applications, then grant permissions:"
echo "   System Settings > Privacy & Security >"
echo "     Microphone, Accessibility, Input Monitoring  -> add FlowDictate"
