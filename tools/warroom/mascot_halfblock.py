"""Render gambar sebagai half-block truecolor (tanpa huruf) - tajam untuk mascot terminal.

Tiap sel karakter = 2 piksel vertikal via '▀' (fg=atas, bg=bawah). Butuh terminal
truecolor (Windows Terminal). Hasil: string dengan kode ANSI, tulis ke mascot-ansi.txt.

Jalankan:
  py -3.14 tools/warroom/mascot_halfblock.py "<gambar>" -Width 70
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from matplotlib.image import imread


def to_rgb(img: np.ndarray) -> np.ndarray:
    if img.dtype != np.float32 and img.dtype != np.float64:
        img = img.astype(float) / 255.0
    if img.ndim == 3 and img.shape[2] == 4:
        rgb = img[..., :3]
        alpha = img[..., 3:4]
        return rgb * alpha  # komposit di atas hitam
    if img.ndim == 3:
        return img[..., :3]
    return np.dstack([img, img, img])


def render(src: Path, width: int) -> str:
    img = to_rgb(imread(str(src)))
    h, w = img.shape[:2]
    px_rows = max(2, int(round(width * h / w)))  # tinggi piksel (2x baris karakter)
    if px_rows % 2 == 1:
        px_rows += 1
    ys = np.linspace(0, h, px_rows, endpoint=False).astype(int)
    xs = np.linspace(0, w, width, endpoint=False).astype(int)
    small = img[ys][:, xs]  # (px_rows, width, 3) float 0..1
    small = np.clip(small * 255.0, 0, 255).astype(int)

    out_lines: list[str] = []
    for i in range(px_rows // 2):
        parts: list[str] = []
        for j in range(width):
            r1, g1, b1 = small[2 * i, j]
            r2, g2, b2 = small[2 * i + 1, j]
            parts.append(f"\x1b[38;2;{r1};{g1};{b1}m\x1b[48;2;{r2};{g2};{b2}m\u2580")
        out_lines.append("".join(parts) + "\x1b[0m")
    return "\n".join(out_lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gambar -> half-block truecolor (mascot).")
    parser.add_argument("source")
    parser.add_argument("-Width", type=int, default=70)
    parser.add_argument("-Out", default=str(Path(__file__).resolve().parent / "mascot.txt"))
    args = parser.parse_args(argv)

    art = render(Path(args.source), args.Width)
    Path(args.Out).write_text(art, encoding="utf-8")
    print(f"OK -> {args.Out} ({len(art.splitlines())} baris, lebar {args.Width})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
