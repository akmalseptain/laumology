"""Konversi gambar ke ASCII gaya BLOK (monokrom) - senada logo LAUMOLOGY.

Rampa blok: ' ' < '░' < '▒' < '▓' < '█' (makin terang makin padat).
Jalankan: py -3.14 tools/warroom/make_mascot.py "<gambar>" -Width 60
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from matplotlib.image import imread

RAMP = " \u2591\u2592\u2593\u2588"  # space, light, medium, dark, full block


def render(src: Path, width: int, gamma: float = 0.75) -> str:
    img = imread(str(src))
    if img.dtype != np.float32 and img.dtype != np.float64:
        img = img.astype(float) / 255.0
    if img.ndim == 3 and img.shape[2] == 4:
        gray = (img[..., :3] * img[..., 3:4]).mean(axis=2)
    elif img.ndim == 3:
        gray = img[..., :3].mean(axis=2)
    else:
        gray = img

    h, w = gray.shape
    new_h = max(1, int(round(h / w * width * 0.5)))
    ys = np.linspace(0, h, new_h + 1).astype(int)
    xs = np.linspace(0, w, width + 1).astype(int)

    n = len(RAMP)
    lines: list[str] = []
    for i in range(new_h):
        row: list[str] = []
        for j in range(width):
            block = gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            v = float(block.mean()) if block.size else 0.0
            v = min(1.0, max(0.0, v)) ** gamma
            row.append(RAMP[min(n - 1, int(v * (n - 1)))])
        lines.append("".join(row).rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gambar -> ASCII gaya blok (mascot).")
    parser.add_argument("source")
    parser.add_argument("-Width", type=int, default=60)
    parser.add_argument("-Gamma", type=float, default=0.75)
    parser.add_argument("-Out", default=str(Path(__file__).resolve().parent / "mascot.txt"))
    args = parser.parse_args(argv)
    art = render(Path(args.source), args.Width, args.Gamma)
    Path(args.Out).write_text(art, encoding="utf-8")
    print(f"OK -> {args.Out} ({len(art.splitlines())} baris, lebar {args.Width})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
