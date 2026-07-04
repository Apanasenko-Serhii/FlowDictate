"""Standalone preview of the redesigned (Wispr-like) settings window.
Renders it, screenshots to assets/settings_preview.png, then closes."""

import sys
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageGrab

HERE = Path(__file__).parent
ICON = HERE / "assets" / "icon.png"
GOLD = "#EDBB30"
CARD = "#23262E"
SUB = "#9AA0AA"

DEMO = {
    "hotkey": "alt+shift", "hotkey_mode": "hold", "language": "auto",
    "model": "large-v3-turbo", "vocabulary": ["Апанасенко", "Blum", "ЛДСП"],
    "cleanup": True, "cleanup_model": "qwen2.5:7b", "cleanup_style": "light",
    "voice_punctuation": True, "preview": False, "sounds": False,
    "beep_on_record": False,
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def build(root, cfg):
    root.configure(fg_color="#171A20")
    F = ctk.CTkFont

    header = ctk.CTkFrame(root, fg_color="transparent")
    header.pack(fill="x", padx=22, pady=(20, 6))
    try:
        logo = ctk.CTkImage(Image.open(ICON), size=(46, 46))
        ctk.CTkLabel(header, image=logo, text="").pack(side="left")
    except Exception:
        pass
    tf = ctk.CTkFrame(header, fg_color="transparent")
    tf.pack(side="left", padx=14)
    ctk.CTkLabel(tf, text="FlowDictate", font=F(size=20, weight="bold"),
                 anchor="w").pack(anchor="w")
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
        ctk.CTkLabel(r, text=label, anchor="w",
                     font=F(size=13)).pack(side="left")
        return r

    vals = {}

    # Hotkey
    c = section("Гаряча клавіша")
    r = row(c, "Клавіша")
    vals["hotkey"] = ctk.CTkEntry(r, width=140)
    vals["hotkey"].insert(0, cfg["hotkey"])
    vals["hotkey"].pack(side="right")
    ctk.CTkButton(r, text="Записати", width=90, fg_color="#333842",
                  hover_color="#3d434f").pack(side="right", padx=8)
    r = row(c, "Режим")
    vals["mode"] = ctk.CTkOptionMenu(
        r, values=["тримати", "перемикач"], width=140,
        fg_color="#333842", button_color=GOLD, button_hover_color="#d9a92a")
    vals["mode"].set("тримати" if cfg["hotkey_mode"] == "hold" else "перемикач")
    vals["mode"].pack(side="right")

    # Recognition
    c = section("Розпізнавання")
    r = row(c, "Мова")
    vals["lang"] = ctk.CTkOptionMenu(r, values=["auto", "uk", "en", "ru"],
                                     width=140, button_color=GOLD)
    vals["lang"].set(cfg["language"])
    vals["lang"].pack(side="right")
    r = row(c, "Модель")
    vals["model"] = ctk.CTkOptionMenu(
        r, values=["large-v3-turbo", "large-v3", "medium", "small"],
        width=140, button_color=GOLD)
    vals["model"].set(cfg["model"])
    vals["model"].pack(side="right")
    ctk.CTkLabel(c, text="Словник (імена, терміни — по одному на рядок)",
                 text_color=SUB, font=F(size=12), anchor="w").pack(
        anchor="w", padx=14, pady=(4, 2))
    vals["vocab"] = ctk.CTkTextbox(c, height=76, corner_radius=8)
    vals["vocab"].insert("1.0", "\n".join(cfg["vocabulary"]))
    vals["vocab"].pack(fill="x", padx=14, pady=(0, 12))

    # AI cleanup
    c = section("AI-чистка тексту")
    r = row(c, "Увімкнути чистку (Ollama)")
    vals["cleanup"] = ctk.CTkSwitch(r, text="", progress_color=GOLD)
    (vals["cleanup"].select if cfg["cleanup"] else vals["cleanup"].deselect)()
    vals["cleanup"].pack(side="right")
    r = row(c, "Модель чистки")
    vals["cmodel"] = ctk.CTkOptionMenu(
        r, values=["qwen2.5:7b", "qwen2.5:3b"], width=140, button_color=GOLD)
    vals["cmodel"].set(cfg["cleanup_model"])
    vals["cmodel"].pack(side="right")
    r = row(c, "Стиль")
    vals["cstyle"] = ctk.CTkOptionMenu(r, values=["light", "full"], width=140,
                                       button_color=GOLD)
    vals["cstyle"].set(cfg["cleanup_style"])
    vals["cstyle"].pack(side="right")

    # Punctuation & insert
    c = section("Пунктуація та вставка")
    r = row(c, "Голосова пунктуація")
    vals["vp"] = ctk.CTkSwitch(r, text="", progress_color=GOLD)
    (vals["vp"].select if cfg["voice_punctuation"] else vals["vp"].deselect)()
    vals["vp"].pack(side="right")
    r = row(c, "Прев'ю перед вставкою")
    vals["preview"] = ctk.CTkSwitch(r, text="", progress_color=GOLD)
    (vals["preview"].select if cfg["preview"] else vals["preview"].deselect)()
    vals["preview"].pack(side="right")

    # Sound & system
    c = section("Звук та система")
    r = row(c, "Звук підтвердження")
    vals["sounds"] = ctk.CTkSwitch(r, text="", progress_color=GOLD)
    (vals["sounds"].select if cfg["sounds"] else vals["sounds"].deselect)()
    vals["sounds"].pack(side="right")
    r = row(c, "Запускати разом з Windows")
    vals["autostart"] = ctk.CTkSwitch(r, text="", progress_color=GOLD)
    vals["autostart"].select()
    vals["autostart"].pack(side="right")

    # Footer
    foot = ctk.CTkFrame(root, fg_color="transparent")
    foot.pack(fill="x", padx=20, pady=14)
    ctk.CTkButton(foot, text="Зберегти", fg_color=GOLD, text_color="#1A1A1A",
                  hover_color="#d9a92a", font=F(size=14, weight="bold"),
                  height=38).pack(side="right")
    ctk.CTkButton(foot, text="Скасувати", fg_color="#333842",
                  hover_color="#3d434f", height=38, width=110).pack(
        side="right", padx=10)
    return vals


def main():
    root = ctk.CTk()
    root.title("FlowDictate — Налаштування")
    root.geometry("480x780+80+40")
    build(root, DEMO)

    def shot():
        try:
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            w, h = root.winfo_width(), root.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(
                HERE / "assets" / "settings_preview.png")
            print("screenshot saved")
        except Exception as e:
            print("shot failed:", e)
        root.destroy()

    root.after(1100, shot)
    root.mainloop()


if __name__ == "__main__":
    main()
