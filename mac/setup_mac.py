"""py2app build config — run ON a Mac: `python setup_mac.py py2app`.

Produces dist/FlowDictate.app (a menu-bar agent app, no Dock icon).
"""

from setuptools import setup

APP = ["flowdictate_mac.py"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "FlowDictate",
        "CFBundleDisplayName": "FlowDictate",
        "CFBundleIdentifier": "pro.apanasenko.flowdictate",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        # Menu-bar agent: no Dock icon, no app-switcher entry
        "LSUIElement": True,
        # Required so macOS shows the microphone permission prompt
        "NSMicrophoneUsageDescription":
            "FlowDictate records your voice to transcribe it locally on-device.",
    },
    "packages": [
        "faster_whisper", "ctranslate2", "pynput", "rumps",
        "sounddevice", "numpy", "tokenizers", "huggingface_hub",
    ],
}

setup(
    app=APP,
    name="FlowDictate",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
