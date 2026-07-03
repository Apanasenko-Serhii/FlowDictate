# PyInstaller spec — builds FlowDictate.app on macOS (used by CI).
# Run on a Mac:  pyinstaller --noconfirm --clean flowdictate_mac.spec
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "sounddevice", "rumps",
            "pynput", "tokenizers", "huggingface_hub"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["flowdictate_mac.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="FlowDictate", console=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas, name="FlowDictate",
)
app = BUNDLE(
    coll,
    name="FlowDictate.app",
    icon=None,
    bundle_identifier="pro.apanasenko.flowdictate",
    info_plist={
        "LSUIElement": True,  # menu-bar agent, no Dock icon
        "NSMicrophoneUsageDescription":
            "FlowDictate records your voice to transcribe it locally on-device.",
        "CFBundleShortVersionString": "1.0.0",
    },
)
