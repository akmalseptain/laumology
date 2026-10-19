"""Laporan PDF track record LAUMOLOGY - resmi, rapih, dan jujur.

Dibuat dengan reportlab (canvas) dari data DB lokal yang sama dengan
halaman /track-record: tidak ada proyeksi atau angka yang tidak bisa
dibuktikan. Setiap halaman memuat wordmark LAUMOLOGY di header, kredit
"Dibuat oleh Akmal Putra Septian", dan disclaimer bukan nasihat finansial
di footer.
"""
from __future__ import annotations

import datetime as _dt
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as _canvas

_BRAND = colors.HexColor("#16a34a")
_DARK = colors.HexColor("#0f172a")
_MUTED = colors.HexColor("#64748b")
_LINE = colors.HexColor("#cbd5e1")

_W, _H = A4
_MARGIN = 40.0

_AUTHOR = "Akmal Putra Septian"
_DISCLAIMER = (
    "Disclaimer: laporan ini bukan nasihat finansial dan bukan ajakan membeli/menjual "
    "efek. Seluruh angka berasal dari paper trading internal LAUMOLOGY; data "
    "historis tidak menjamin hasil di masa depan."
)


class _Doc:
    """Kanvas PDF dengan header (logo) + footer (pembuat & disclaimer) tiap halaman."""

    def __init__(self, c):
        self.c = c
        self.page = 0
        self.y = 0.0

    def _header_footer(self):
        c = self.c
        # --- Header: logo blok + wordmark LAUMOLOGY
        c.setFillColor(_BRAND)
        c.rect(_MARGIN, _H - 64, 24, 24, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(_MARGIN + 12, _H - 57, "L")
        c.setFillColor(_DARK)
        c.setFont("Helvetica-Bold", 19)
        x = _MARGIN + 32
        c.drawString(x, _H - 57, "LAUMO")
        x += stringWidth("LAUMO", "Helvetica-Bold", 19)
        c.setFillColor(_BRAND)
        c.drawString(x, _H - 57, "LOGY")
        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(_MARGIN + 33, _H - 70, "ANALISIS SAHAM IDX  -  LAPORAN TRACK RECORD RESMI")
        c.drawRightString(
            _W - _MARGIN, _H - 70,
            "Dicetak " + _dt.datetime.now(_dt.timezone.utc).strftime("%d %b %Y %H:%M UTC"),
        )
        c.setStrokeColor(_LINE)
        c.setLineWidth(1)
        c.line(_MARGIN, _H - 78, _W - _MARGIN, _H - 78)
        # --- Footer: pembuat + disclaimer + nomor halaman
        c.setFillColor(_DARK)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(_MARGIN, 36, "Dibuat oleh " + _AUTHOR)
        c.setFillColor(_MUTED)
        c.drawRightString(_W - _MARGIN, 36, "Halaman " + str(self.page))
        c.setFont("Helvetica", 7)
        y = 26
        for ln in simpleSplit(_DISCLAIMER, "Helvetica", 7, _W - 2 * _MARGIN):
            c.drawString(_MARGIN, y, ln)
            y -= 8.5

    def new_page(self):
        self.page += 1
        self._header_footer()
        self.y = _H - 100

    def check_space(self, need=40.0):
        if self.y - need < 100:
            self.c.showPage()
            self.new_page()

    def section(self, txt):
        self.check_space(60)
        c = self.c
        c.setFont("Helvetica-Bold", 11.5)
        c.setFillColor(_BRAND)
        c.drawString(_MARGIN, self.y, txt)
        self.y -= 6
        c.setStrokeColor(_LINE)
        c.line(_MARGIN, self.y, _W - _MARGIN, self.y)
        self.y -= 14

    def kv_grid(self, pairs):
        """Baris label/nilai, dua kolom per baris."""
        i = 0
        while i < len(pairs):
            self.check_space(46)
            for col in (0, 1):
                if i >= len(pairs):
                    break
                lab, val = pairs[i]
                x = _MARGIN if col == 0 else _W / 2.0 + 10
                self.c.setFont("Helvetica", 7.5)
                self.c.setFillColor(_MUTED)
                self.c.drawString(x, self.y, str(lab).upper())
                self.c.setFont("Helvetica-Bold", 12)
                self.c.setFillColor(_DARK)
                self.c.drawString(x, self.y - 12, str(val))
                i += 1
            self.y -= 30

    def table(self, heads, xs, rows):
        c = self.c
        for row in rows:
            if self.y - 13 < 100:
                c.showPage()
                self.new_page()
            if self.y >= _H - 105:  # halaman baru: gambar kepala tabel lagi
                c.setFont("Helvetica-Bold", 7.5)
                c.setFillColor(_MUTED)
                for h, x in zip(heads, xs):
                    c.drawString(x, self.y, h)
                self.y -= 12
            c.setFont("Helvetica", 8.5)
            c.setFillColor(_DARK)
            for v, x in zip(row, xs):
                c.drawString(x, self.y, str(v))
            self.y -= 13
        self.y -= 6

    def note(self, txt):
        self.check_space(30)
        self.c.setFont("Helvetica-Oblique", 9)
        self.c.setFillColor(_MUTED)
        self.c.drawString(_MARGIN, self.y, txt)
        self.y -= 20


def build_track_record_pdf(data: dict) -> bytes:
    """Bangun PDF dari dict summary() — tanpa proyeksi, angka apa adanya."""
    buf = BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    doc = _Doc(c)
    doc.new_page()

    # Judul
    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(_DARK)
    c.drawString(_MARGIN, doc.y, "LAPORAN TRACK RECORD")
    doc.y -= 18
    c.setFont("Helvetica", 9)
    c.setFillColor(_MUTED)
    c.drawString(_MARGIN, doc.y,
                 "Diterbitkan otomatis oleh sistem LAUMOLOGY - setiap angka berasal dari data sinyal & paper trading tercatat.")
    doc.y -= 22

    outcomes = data.get("outcomes") or {}
    verdicts = data.get("verdicts") or {}
    last_scan = data.get("last_scan")

    doc.section("RINGKASAN")
    pairs = [
        ("Sinyal tercatat", data.get("n_signals", 0)),
        ("Posisi ditutup", data.get("n_closed", 0)),
        ("Win rate paper", "{:.1f}%".format(float(data.get("win_rate") or 0.0) * 100.0)),
        ("Expectancy / trade", "{:+.2f}%".format(float(data.get("expectancy_pct") or 0.0))),
        ("Payoff", "{:.2f}".format(float(data.get("payoff") or 0.0))),
        ("Total PnL paper", "{:+,.0f}".format(float(data.get("total_pnl") or 0.0))),
        ("Sinyal dievaluasi (H+5)", outcomes.get("n", 0)),
        ("Return positif H+5", "{:.1f}%".format(float(outcomes.get("win_rate") or 0.0))),
    ]
    if last_scan:
        pairs.append(("Scan terakhir", str(last_scan.get("ts") or "-")))
    doc.kv_grid(pairs)

    v_pct = verdicts.get("verdict_pct") or {}
    if verdicts.get("n"):
        doc.section("VONIS SINYAL (SADAR-ARAH, H+5)")
        doc.kv_grid([
            ("Benar nyata", "{:.1f}%".format(float(v_pct.get("benar_nyata") or 0.0))),
            ("Untung, ikut pasar", "{:.1f}%".format(float(v_pct.get("untung_ikut_pasar") or 0.0))),
            ("Salah relatif oke", "{:.1f}%".format(float(v_pct.get("salah_relatif_ok") or 0.0))),
            ("Salah", "{:.1f}%".format(float(v_pct.get("salah") or 0.0))),
        ])

    doc.section("RIWAYAT SINYAL TERBARU")
    signals = data.get("signals") or []
    xs = [_MARGIN, _MARGIN + 92, _MARGIN + 160, _MARGIN + 268,
          _MARGIN + 316, _MARGIN + 366, _MARGIN + 418]
    heads = ["WAKTU", "KODE", "AKSI", "SKOR", "CONF", "GRADE", "HARGA"]
    if signals:
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(_MUTED)
        for h, x in zip(heads, xs):
            c.drawString(x, doc.y, h)
        doc.y -= 12
        rows = []
        for s in signals[:45]:
            price = s.get("price")
            rows.append([
                str(s.get("ts") or "?")[:16],
                str(s.get("ticker") or "?"),
                str(s.get("action") or s.get("signal") or "?"),
                s.get("score") if s.get("score") is not None else "-",
                s.get("confidence") if s.get("confidence") is not None else "-",
                str(s.get("grade") or "-"),
                "{:.2f}".format(float(price)) if price else "-",
            ])
        doc.table(heads, xs, rows)
    else:
        doc.note("Belum ada sinyal tercatat - laporan ini terisi otomatis seiring sistem memindai bursa.")

    doc.note("Sumber: DB lokal LAUMOLOGY (sinyal + paper trading). Bukan hasil trading uang sungguhan.")

    c.save()
    return buf.getvalue()
