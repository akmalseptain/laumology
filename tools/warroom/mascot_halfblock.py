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


def detect_crop(src: Path) -> tuple[float, float, float, float]:
    """Deteksi wajah (Haar) lalu kembalikan crop (fraksi) yang mencakup kepala+bahu."""
    import cv2
    img = cv2.imread(str(src))
    if img is None:
        return (0.2, 0.02, 0.8, 0.9)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hgt, wid = gray.shape
    best = None
    minsz = max(40, wid // 12)
    for xml in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        try:
            c = cv2.CascadeClassifier(cv2.data.haarcascades + xml)
            faces = c.detectMultiScale(gray, 1.1, 5, minSize=(minsz, minsz))
        except Exception:
            faces = ()
        if len(faces):
            best = max(faces, key=lambda f: f[2] * f[3])
            break
    if best is None:
        return (0.20, 0.02, 0.80, 0.92)  # fallback: tengah
    x, y, w, h = best
    x0 = max(0, x - 0.35 * w)
    y0 = max(0, y - 0.80 * h)
    x1 = min(wid, x + 1.35 * w)
    y1 = min(hgt, y + 1.55 * h)
    return (x0 / wid, y0 / hgt, x1 / wid, y1 / hgt)


def render(src: Path, width: int, crop: tuple[float, float, float, float] | None = None) -> str:
    img = to_rgb(imread(str(src)))
    h, w = img.shape[:2]
    if crop is not None:
        x0, y0, x1, y1 = crop
        img = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
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
    parser.add_argument("-Height", type=int, default=0, help="target jumlah baris karakter (menimpa -Width)")
    parser.add_argument("-Crop", default="", help="x0,y0,x1,y1 (fraksi 0..1)")
    parser.add_argument("-AutoFace", action="store_true", help="deteksi wajah lalu crop otomatis")
    parser.add_argument("-Out", default=str(Path(__file__).resolve().parent / "mascot.txt"))
    args = parser.parse_args(argv)

    src = Path(args.source)
    crop = None
    if args.AutoFace:
        crop = detect_crop(src)
    elif args.Crop:
        crop = tuple(float(v) for v in args.Crop.split(","))
        if len(crop) != 4:
            print("Crop harus 4 angka: x0,y0,x1,y1")
            return 1

    width = args.Width
    if args.Height > 0:
        if crop is not None:
            cw = max(1e-6, crop[2] - crop[0])
            ch = max(1e-6, crop[3] - crop[1])
        else:
            from matplotlib.image import imread as _im
            sh = _im(str(src)).shape
            cw, ch = 1.0, sh[0] / sh[1]
        width = max(20, int(round(args.Height * 2 * cw / ch)))

    art = render(src, width, crop)
    Path(args.Out).write_text(art, encoding="utf-8")
    print(f"OK -> {args.Out} ({len(art.splitlines())} baris, lebar {width}, crop={crop if crop else '-'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
