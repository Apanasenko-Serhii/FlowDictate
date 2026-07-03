"""Unit tests for v2 text processing: voice punctuation, commands, initial
prompt, and (live) Ollama cleanup if the model is available."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import flowdictate as fd  # noqa: E402

failures = []


def check(name, cond, got=None):
    print(f"{name}: {'PASS' if cond else 'FAIL'}" + (f"  got={got!r}" if not cond else ""))
    if not cond:
        failures.append(name)


# voice punctuation
check("comma", fd.apply_voice_punctuation("привіт кома як справи")
      == "привіт, як справи", fd.apply_voice_punctuation("привіт кома як справи"))
check("period", fd.apply_voice_punctuation("добре крапка")
      == "добре.", fd.apply_voice_punctuation("добре крапка"))
check("question", fd.apply_voice_punctuation("ти тут знак питання")
      == "ти тут?", fd.apply_voice_punctuation("ти тут знак питання"))
r = fd.apply_voice_punctuation("перший рядок з нового рядка другий")
check("newline", r == "перший рядок\nдругий", r)
r2 = fd.apply_voice_punctuation("список двокрапка перший кома другий крапка")
check("multi", r2 == "список: перший, другий.", r2)
check("no-op empty", fd.apply_voice_punctuation("") == "")
# 'крапка з комою' must win over 'крапка'
r3 = fd.apply_voice_punctuation("а крапка з комою б")
check("semicolon-before-period", r3 == "а; б", r3)

# commands
check("cmd undo", fd.detect_command("видали останнє") == "undo")
check("cmd undo trailing dot", fd.detect_command("Скасувати.") == "undo")
check("cmd none", fd.detect_command("привіт світ") is None)

# initial prompt with vocabulary
cfg = dict(fd.DEFAULT_CONFIG)
cfg["vocabulary"] = ["Апанасенко", "Blum"]
ip = fd.build_initial_prompt(cfg)
check("vocab in prompt", "Апанасенко" in ip and "Blum" in ip, ip)

# live Ollama cleanup (skip gracefully if unavailable)
cfg2 = dict(fd.DEFAULT_CONFIG)
cfg2["cleanup"] = True
cfg2["cleanup_style"] = "light"
raw = "ну еее привіт як би це тест диктування без пунктуації типу"
cleaned = fd.Cleaner(cfg2).cleanup(raw)
print(f"CLEANUP raw={raw!r}")
print(f"CLEANUP out={cleaned!r}")
# It must return SOMETHING (either cleaned, or raw on fallback) — never crash
check("cleanup returns text", isinstance(cleaned, str) and len(cleaned) > 0)
if cleaned != raw:
    # if the model actually ran, fillers should mostly be gone
    print("  (Ollama responded — cleanup active)")
else:
    print("  (Ollama fallback — raw text returned)")

print("SMOKE=PASS" if not failures else f"SMOKE=FAIL {failures}")
sys.exit(0 if not failures else 1)
