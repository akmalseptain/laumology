"""Refactor sekali pakai: pisahkan CSS & JS inline dari templates/index.html
ke file statis (static/css/app.css, static/js/app.js) agar halaman ringan
dan bisa dimanfaatkan cache. Jalankan: py tools/extract_frontend.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "templates" / "index.html"

html = TPL.read_text(encoding="utf-8")

m = re.search(r"<style>(.*?)</style>", html, re.S)
if not m:
    raise SystemExit("blok <style> tidak ditemukan")
css_dir = ROOT / "static" / "css"
css_dir.mkdir(parents=True, exist_ok=True)
(css_dir / "app.css").write_text(m.group(1).strip() + "\n", encoding="utf-8")
html = html[: m.start()] + '<link rel="stylesheet" href="/static/css/app.css">' + html[m.end():]

m = re.search(r"<script>(.*?)</script>", html, re.S)
if not m:
    raise SystemExit("blok <script> tidak ditemukan")
js_dir = ROOT / "static" / "js"
js_dir.mkdir(parents=True, exist_ok=True)
(js_dir / "app.js").write_text(m.group(1).strip() + "\n", encoding="utf-8")
html = html[: m.start()] + '<script src="/static/js/app.js"></script>' + html[m.end():]

TPL.write_text(html, encoding="utf-8")
print("OK: static/css/app.css, static/js/app.js dibuat; index.html dirampingkan")
print("index.html sekarang", len(html), "bytes")
