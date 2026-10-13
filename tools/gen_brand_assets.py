"""Generator aset brand LAUMOLOGY (W-0025 — kartu berbagi & ikon).

Menghasilkan PNG ke ``static/``:
  - ``og-cover.png``        1200x630  kartu Open Graph / Twitter (bukan SVG!)
  - ``icon-192.png``        192x192   ikon PWA
  - ``icon-512.png``        512x512   ikon PWA
  - ``apple-touch-icon.png``180x180   ikon iOS (opaque, tanpa alpha)

Pillow TIDAK ada di ``requirements.txt`` (image runtime Linux/Render) sehingga
skrip ini HANYA untuk dev: jalankan lokal lalu commit PNG hasilnya. Font Arial
di ``C:\\Windows\\Fonts`` tak tersedia di Linux; jangan jalankan di buildCommand.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

# Palet brand (konsisten dengan templates/index.html + manifest).
BG_DARK = (15, 23, 18)
BG_DARKER = (9, 14, 11)
GREEN = (22, 163, 74)
GREEN_LIGHT = (74, 222, 128)
TEXT = (232, 245, 238)
MUTED = (159, 179, 168)

# Kandidat font: Windows (dev) dulu, lalu Linux (defensif bila dijalankan di CI).
_FONT_CANDIDATES = {
    "bold": (
        r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
    "regular": (
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ),
}


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES["bold" if bold else "regular"]:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _vgradient(size: tuple[int, int]) -> Image.Image:
    """Latar gradien vertikal halus dari BG_DARK ke BG_DARKER."""
    w, h = size
    img = Image.new("RGB", (w, 1))
    px = img.load()
    for x in range(w):
        t = x / max(1, w - 1)
        px[x, 0] = tuple(round(a + (b - a) * t) for a, b in zip(BG_DARK, BG_DARKER))
    return img.resize((w, h), Image.BILINEAR)


def _centered(draw: ImageDraw.ImageDraw, text: str, font, y: int, fill, width: int) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2 - box[0], y), text, font=font, fill=fill)


def _candles(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int) -> None:
    """Glyph 4 bar naik + panah tren, dipakai pada ikon."""
    n = 4
    gap = (x1 - x0) / (n * 2 - 1)
    base = y1
    for i in range(n):
        bh = (y1 - y0) * (0.35 + 0.18 * i)
        bw = gap * 1.35
        bx = x0 + i * gap * 2
        top = base - bh
        draw.rounded_rectangle([bx, top, bx + bw, base], radius=bw * 0.2, fill=GREEN_LIGHT)
        wick_x = bx + bw / 2
        draw.line([wick_x, top - bh * 0.18, wick_x, base + bh * 0.10], fill=GREEN_LIGHT, width=max(1, int(bw * 0.12)))
    # Panah tren (naik) dari kiri-bawah ke kanan-atas.
    ax0, ay0 = x0 - gap * 0.2, y1 - (y1 - y0) * 0.30
    ax1, ay1 = x1 + gap * 0.3, y0 - (y1 - y0) * 0.05
    lw = max(2, int((x1 - x0) * 0.05))
    draw.line([ax0, ay0, ax1, ay1], fill=TEXT, width=lw)
    head = lw * 2.2
    draw.line([ax1, ay1, ax1 - head, ay1], fill=TEXT, width=lw)
    draw.line([ax1, ay1, ax1, ay1 + head], fill=TEXT, width=lw)


def make_icon(size: int, *, opaque_bg: bool) -> Image.Image:
    """Ikon persegi: latar hijau membulat + glyph candle naik."""
    scale = 4  # supersample lalu downscale → tepi halus
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = s * 0.06
    radius = s * 0.22
    if opaque_bg:
        draw.rectangle([0, 0, s, s], fill=GREEN)
    else:
        draw.rounded_rectangle([pad, pad, s - pad, s - pad], radius=radius, fill=GREEN)
    inner_pad = s * 0.20
    _candles(draw, int(inner_pad), int(inner_pad * 1.15), int(s - inner_pad), int(s - inner_pad))
    return img.resize((size, size), Image.LANCZOS).convert("RGBA")


def make_og_cover() -> Image.Image:
    """Kartu 1200x630: wordmark + tagline + grafik naik di kanan."""
    w, h = 1200, 630
    img = _vgradient((w, h)).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Aksen hijau tepi kiri.
    draw.rectangle([0, 0, 14, h], fill=GREEN)

    # Garis grid tipis.
    grid = (26, 38, 30)
    for gx in range(80, w, 80):
        draw.line([gx, 0, gx, h], fill=grid, width=1)
    for gy in range(70, h, 70):
        draw.line([0, gy, w, gy], fill=grid, width=1)

    # Grafik naik di sisi kanan (dekoratif, tak menabrak teks).
    pts = [(902, 586), (968, 546), (1032, 480), (1096, 400), (1156, 266)]
    draw.line(pts, fill=GREEN, width=10, joint="curve")
    for px, py in pts[1:]:
        draw.ellipse([px - 9, py - 9, px + 9, py + 9], fill=GREEN_LIGHT)

    # Teks.
    _centered(draw, "LAUMOLOGY", _font(104, bold=True), 150, TEXT, w)
    _centered(draw, "IDX TRADING TERMINAL", _font(38, bold=True), 290, GREEN_LIGHT, w)
    _centered(draw, "Sinyal · Screener · Backtest · Akurasi", _font(32), 380, MUTED, w)
    _centered(draw, "Analisis teknikal saham IDX berbasis evidence", _font(28), 440, MUTED, w)
    return img


def _png_dims(data: bytes) -> tuple[int, int]:
    return struct.unpack(">II", data[16:24])


def main() -> int:
    STATIC.mkdir(parents=True, exist_ok=True)
    outputs = {
        "og-cover.png": make_og_cover(),
        "icon-512.png": make_icon(512, opaque_bg=True),
        "icon-192.png": make_icon(192, opaque_bg=True),
        "apple-touch-icon.png": make_icon(180, opaque_bg=True),
    }
    for name, im in outputs.items():
        path = STATIC / name
        im.save(path, "PNG", optimize=True)
        dims = _png_dims(path.read_bytes())
        print(f"OK  {name:22s} {dims[0]}x{dims[1]}  {path.stat().st_size/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
