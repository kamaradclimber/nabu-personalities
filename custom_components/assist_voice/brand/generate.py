"""Generate the placeholder brands icon/logo for the Assist Voice integration.

Outputs icon.png (256x256) and logo.png (512x512) alongside this script.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent
BG = (44, 47, 110, 255)  # deep indigo
FG = (232, 234, 246, 255)  # near-white
ACCENT = (255, 159, 67, 255)  # orange accent

# Normalized waveform heights, 10 bars.
HEIGHTS = [0.25, 0.45, 0.70, 0.90, 0.60, 0.80, 0.95, 0.75, 0.50, 0.35]


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=size * 245 // 1000, fill=BG
    )
    bar_w = size * 56 // 1000
    gap = size * 20 // 1000
    total = len(HEIGHTS) * bar_w + (len(HEIGHTS) - 1) * gap
    x = (size - total) // 2
    mid = size // 2
    for i, h in enumerate(HEIGHTS):
        bar_h = int(size * h)
        color = ACCENT if i == len(HEIGHTS) // 2 else FG
        draw.rounded_rectangle(
            [x, mid - bar_h // 2, x + bar_w, mid + bar_h // 2],
            radius=bar_w // 2,
            fill=color,
        )
        x += bar_w + gap
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    render(256).save(OUT / "icon.png")
    render(512).save(OUT / "logo.png")
    print(f"Wrote {OUT / 'icon.png'} and {OUT / 'logo.png'}")


if __name__ == "__main__":
    main()
