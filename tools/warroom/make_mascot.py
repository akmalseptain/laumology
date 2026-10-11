"""Konversi gambar (PNG/JPG) menjadi ASCII art untuk mascot War Room.

Jalankan:
  py -3.14 tools/warroom/make_mascot.py "<gambar>" [-Width 110] [-Out tools/warroom/mascot.txt]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from matplotlib.image import imread


def convert(src: Path, width: int, ramp: str, agg: str = "max", gamma: float = 0.8) -> str:
    img = imread(str(src))
    if img.dtype != np.float32 and img.dtype != np.float64:
        img = img.astype(float) / 255.0

    if img.ndim == 3 and img.shape[2] == 4:
        rgb = img[..., :3]
        alpha = img[..., 3:4]
        gray = (rgb * alpha).mean(axis=2)  # komposit di atas hitam
    elif img.ndim == 3:
        gray = img[..., :3].mean(axis=2)
    else:
        gray = img

    h, w = gray.shape
    new_h = max(1, int(round(h / w * width * 0.5)))  # koreksi aspek karakter terminal
    ys = np.linspace(0, h, new_h + 1).astype(int)
    xs = np.linspace(0, w, width + 1).astype(int)

    n = len(ramp)
    lines: list[str] = []
    for i in range(new_h):
        chars: list[str] = []
        for j in range(width):
            block = gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            if block.size == 0:
                v = 0.0
            elif agg == "max":
                v = float(block.max())
            else:
                v = float(block.mean())
            v = min(1.0, max(0.0, v)) ** gamma
            chars.append(ramp[min(n - 1, int(v * (n - 1)))])
        lines.append("".join(chars).rstrip())
    # buang baris kosong berlebih di atas/bawah
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PNG/JPG -> ASCII art (mascot).")
    parser.add_argument("source")
    parser.add_argument("-Width", type=int, default=110)
    parser.add_argument("-Agg", choices=["max", "mean"], default="max")
    parser.add_argument("-Out", default=str(Path(__file__).resolve().parent / "mascot.txt"))
    args = parser.parse_args(argv)

    art = convert(Path(args.source), args.Width, " .:-=+*#%@", agg=args.Agg)
    Path(args.Out).write_text(art, encoding="utf-8")
    print(f"OK -> {args.Out} ({len(art.splitlines())} baris, lebar {args.Width}, agg={args.Agg})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
