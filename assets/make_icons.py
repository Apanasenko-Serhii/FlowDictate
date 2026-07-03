"""Generate app icons from the APANASENKO PRO roof mark (pure Pillow).

The roof path is a straight-line polygon, so we draw it directly — no SVG
rasterizer needed. Output (assets/): icon.png (512 branded square), app.ico.
"""

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
GOLD = (237, 187, 48)
DARK = (28, 31, 38)
SIZE = 512
SS = 4                      # supersample for smooth edges

# roof polygon vertices (from the logo SVG path)
ROOF = [
    (21.6226, 27.3991), (30.7758, 53.5302), (52.3103, 55.7547),
    (55.6976, 58.5849), (110.645, 37.6415), (115.09, 41.7623),
    (170.406, 11.0689), (208.681, 60.0312), (216.638, 56.2755),
    (170.924, 0.0), (103.291, 25.4547), (102.188, 17.3264),
    (96.175, 17.9094), (88.3319, 21.0085), (87.6272, 33.4387),
    (21.4379, 16.9811), (0.0, 68.7934), (6.69224, 68.0349),
]


def rounded_square(size, radius, color):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=color + (255,))
    return img


def main():
    big = SIZE * SS
    img = rounded_square(big, radius=int(0.22 * big), color=DARK)
    draw = ImageDraw.Draw(img)

    xs = [p[0] for p in ROOF]
    ys = [p[1] for p in ROOF]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    target_w = 0.74 * big
    scale = target_w / w
    ox = (big - w * scale) / 2 - min(xs) * scale
    oy = (big - h * scale) / 2 - min(ys) * scale
    pts = [(x * scale + ox, y * scale + oy) for x, y in ROOF]
    draw.polygon(pts, fill=GOLD + (255,))

    icon = img.resize((SIZE, SIZE), Image.LANCZOS)
    icon.save(HERE / "icon.png")
    icon.save(HERE / "app.ico",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                     (32, 32), (16, 16)])
    print("icon.png + app.ico written", icon.size)


if __name__ == "__main__":
    main()
