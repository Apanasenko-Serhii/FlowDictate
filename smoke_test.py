"""Smoke test: transcribe a wav through the same engine the app uses.

Usage: python smoke_test.py <path-to-wav> [expected-substring]
Exits 0 if transcription succeeds (and contains the substring, if given).
"""

import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from flowdictate import DEFAULT_CONFIG, Engine, setup_cuda_dlls  # noqa: E402


def read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        assert w.getsampwidth() == 2, "expected 16-bit PCM"
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    audio = data.astype(np.float32) / 32768.0
    if rate != 16000:
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate))
        audio = audio[idx.astype(np.int64)]
    return audio


def main():
    wav = sys.argv[1]
    expected = sys.argv[2].lower() if len(sys.argv) > 2 else None
    setup_cuda_dlls()
    cfg = dict(DEFAULT_CONFIG)
    cfg["initial_prompt"] = ""
    eng = Engine(cfg)
    eng.load()
    audio = read_wav(wav)
    import time
    t0 = time.time()
    text = eng.transcribe(audio)
    dt = time.time() - t0
    print(f"DEVICE={eng.device}")
    print(f"SECONDS={dt:.2f}")
    print(f"TEXT={text}")
    if expected and expected not in text.lower():
        print("SMOKE=FAIL (expected substring missing)")
        sys.exit(1)
    print("SMOKE=PASS")


if __name__ == "__main__":
    main()
