"""Laporan PDF resmi track record LAUMOLOGY.

Format mengikuti kaidah dokumen resmi konservatif (ala surat dinas): A4
margin 2,5 cm, font serif Times, palet hitam/abu netral (hijau hanya logo),
logo vektor asli LAUMOLOGY (replika persis /static/laumology.svg),
garis ganda kop, nomor dokumen, seksi bernomor romawi, tabel bergaris
kepala, blok pengesahan bertanda tangan penerbit (gambar signature.png), serta footer
"Halaman X dari Y" + disclaimer bukan nasihat finansial di setiap
halaman. Semua angka murni dari summary() DB lokal - tanpa proyeksi.
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as _canvas

_BRAND = colors.HexColor("#16a34a")  # hijau hanya di logo (identitas)
_DARK = colors.HexColor("#000000")
_MUTED = colors.HexColor("#444444")
_LINE = colors.HexColor("#8a8a8a")
_RULE = colors.HexColor("#c8c8c8")
_FAINT = colors.HexColor("#f2f2f2")

_W, _H = A4
_MARGIN = 70.87  # 2,5 cm kiri/kanan (kaidah dokumen resmi A4)

_AUTHOR = "Akmal Putra Septian"
_ROLE = "Pengembang LAUMOLOGY"
_SITE = "laumology.onrender.com"
_DISCLAIMER = (
    "Disclaimer: laporan ini bukan nasihat finansial dan bukan ajakan membeli/menjual "
    "efek. Seluruh angka berasal dari paper trading internal LAUMOLOGY; data "
    "historis tidak menjamin hasil di masa depan."
)

_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
          "Agustus", "September", "Oktober", "November", "Desember")


def _wib() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=7)


def _tanggal(t: _dt.datetime) -> str:
    return "{} {} {}".format(t.day, _BULAN[t.month - 1], t.year)


_SIGNATURE_PATH = Path(__file__).resolve().parent / "signature.png"
_SIGNATURE_MAX_H = 46.0    # tinggi maksimum gambar tanda tangan (pt)
_SIGNATURE_MAX_W = 120.0   # lebar maksimum gambar tanda tangan (pt)


def _signature_image():
    """Muat signature.png (tanda tangan penerbit), buang margin transparan.

    Return ImageReader siap digambar; None bila file/PIL tidak tersedia
    (blok pengesahan tetap terbit tanpa gambar - PDF tidak boleh gagal).
    """
    try:
        from PIL import Image
        from reportlab.lib.utils import ImageReader
        if not _SIGNATURE_PATH.is_file():
            return None
        im = Image.open(_SIGNATURE_PATH)
        im.load()
        if im.mode not in ("RGBA", "LA", "PA"):
            im = im.convert("RGBA")
        try:
            bbox = im.getchannel("A").getbbox() if im.mode in ("RGBA", "LA", "PA") else None
        except Exception:
            bbox = None
        if bbox:
            im = im.crop(bbox)
        return ImageReader(im)
    except Exception:
        return None


def _draw_logo(c, x: float, y: float, h: float) -> None:
    """Logo asli LAUMOLOGY dalam vektor (replika /static/laumology.svg).

    (x, y) = titik kiri-bawah area logo, h = tinggi logo (poin).
    Koordinat SVG (y ke bawah, viewBox 92x64) dibalik ke sumbu PDF (y ke atas).
    """
    s = h / 64.0
    c.saveState()
    c.translate(x, y)
    c.scale(s, s)
    c.setStrokeColor(_BRAND)
    c.setFillColor(_BRAND)
    # sumbu lilin (wick) - garis tipis
    c.setLineWidth(1.6)
    c.setLineCap(0)
    for lx, ya, yb in ((12, 34, 2), (30, 42, 4), (49, 50, 6), (68, 56, 8)):
        c.line(lx, ya, lx, yb)
    # badan lilin - kotak sudut membulat
    for rx, ry, rw, rh in ((7, 10, 10, 14), (25, 12, 10, 20),
                           (44, 14, 10, 26), (63, 16, 10, 32)):
        c.roundRect(rx, ry, rw, rh, 1.6, fill=1, stroke=0)
    # garis tren + mata panah
    c.setLineWidth(2.4)
    c.setLineCap(1)
    c.setLineJoin(1)
    c.line(4, 12, 88, 58)
    ph = c.beginPath()
    ph.moveTo(73, 58)
    ph.lineTo(88, 58)
    ph.lineTo(88, 43)
    c.drawPath(ph, fill=0)
    c.restoreState()


def _kop(c, nomor: str, tanggal: str) -> None:
    """Kop dokumen resmi (halaman pertama): logo, identitas, nomor, garis ganda."""
    _draw_logo(c, _MARGIN, _H - 78, 42)
    lx = _MARGIN + 92 * (42 / 64.0) + 11
    c.setFont("Times-Bold", 21)
    c.setFillColor(_DARK)
    c.drawString(lx, _H - 51, "LAUMO")
    x2 = lx + stringWidth("LAUMO", "Times-Bold", 21)
    c.setFillColor(_DARK)
    c.drawString(x2, _H - 51, "LOGY")
    c.setFillColor(_MUTED)
    c.setFont("Times-Roman", 9)
    c.drawString(lx, _H - 63, "Analisis Saham Bursa Efek Indonesia (IDX)")
    c.setFont("Times-Roman", 7.5)
    c.drawString(lx, _H - 73, _SITE + "  -  sistem analisis & paper trading transparan")
    # blok nomor dokumen & waktu cetak (kanan atas, kaidah surat resmi)
    c.setFillColor(_DARK)
    c.setFont("Times-Bold", 8)
    c.drawRightString(_W - _MARGIN, _H - 42, "NOMOR: " + nomor)
    c.setFillColor(_MUTED)
    c.setFont("Times-Roman", 7.5)
    c.drawRightString(_W - _MARGIN, _H - 52, "Dicetak " + tanggal)
    # garis ganda kop: tebal gelap + tipis brand
    c.setStrokeColor(_DARK)
    c.setLineWidth(1.6)
    c.line(_MARGIN, _H - 86, _W - _MARGIN, _H - 86)
    c.setStrokeColor(_DARK)
    c.setLineWidth(0.8)
    c.line(_MARGIN, _H - 90, _W - _MARGIN, _H - 90)


def _kop_lanjutan(c, nomor: str) -> None:
    """Kop ringkas untuk halaman lanjutan."""
    _draw_logo(c, _MARGIN, _H - 50, 14)
    x = _MARGIN + 92 * (14 / 64.0) + 8
    c.setFont("Times-Bold", 9)
    c.setFillColor(_DARK)
    c.drawString(x, _H - 44, "LAPORAN RESMI TRACK RECORD  -  LAUMOLOGY")
    c.setFillColor(_MUTED)
    c.setFont("Times-Roman", 7.5)
    c.drawRightString(_W - _MARGIN, _H - 44, "Nomor: " + nomor)
    c.setStrokeColor(_LINE)
    c.setLineWidth(0.8)
    c.line(_MARGIN, _H - 56, _W - _MARGIN, _H - 56)


def _footer(c) -> None:
    c.setStrokeColor(_LINE)
    c.setLineWidth(0.75)
    c.line(_MARGIN, 54, _W - _MARGIN, 54)
    c.setFillColor(_DARK)
    c.setFont("Times-Bold", 8)
    c.drawString(_MARGIN, 43, "Dibuat oleh " + _AUTHOR + "  -  " + _ROLE)
    c.setFillColor(_MUTED)
    c.setFont("Times-Roman", 6.8)
    y = 33
    for ln in simpleSplit(_DISCLAIMER, "Times-Roman", 6.8, _W - 2 * _MARGIN):
        c.drawString(_MARGIN, y, ln)
        y -= 8



class _Doc:
    """Kanvas PDF dengan kop resmi + footer tiap halaman."""

    def __init__(self, c, nomor, tanggal, total=0):
        self.c = c
        self.nomor = nomor
        self.tanggal = tanggal
        self.total = total
        self.page = 0
        self.y = 0.0

    def new_page(self):
        self.page += 1
        if self.page == 1:
            _kop(self.c, self.nomor, self.tanggal)
            self.y = _H - 112
        else:
            _kop_lanjutan(self.c, self.nomor)
            self.y = _H - 72
        _footer(self.c)
        c = self.c
        c.setFont("Times-Roman", 8)
        c.setFillColor(_MUTED)
        if self.total:
            c.drawRightString(_W - _MARGIN, 43,
                              "Halaman {} dari {}".format(self.page, self.total))
        else:
            c.drawRightString(_W - _MARGIN, 43, "Halaman {}".format(self.page))

    def check_space(self, need=40.0):
        if self.y - need < 64:
            self.c.showPage()
            self.new_page()

    def section(self, txt):
        self.check_space(56)
        c = self.c
        c.setFont("Times-Bold", 11.5)
        c.setFillColor(_DARK)
        c.drawString(_MARGIN, self.y, txt)
        self.y -= 7
        c.setStrokeColor(_DARK)
        c.setLineWidth(0.9)
        c.line(_MARGIN, self.y, _W - _MARGIN, self.y)
        self.y -= 16

    def kv_grid(self, pairs):
        """Baris label/nilai dua kolom dengan garis pemisah tipis (kaidah tabel resmi)."""
        i = 0
        while i < len(pairs):
            self.check_space(48)
            c = self.c
            c.setStrokeColor(_RULE)
            c.setLineWidth(0.5)
            c.line(_MARGIN, self.y + 6, _W - _MARGIN, self.y + 6)
            for col in (0, 1):
                if i >= len(pairs):
                    break
                lab, val = pairs[i]
                x = _MARGIN + col * 235
                c.setFont("Times-Roman", 7)
                c.setFillColor(_MUTED)
                c.drawString(x, self.y, str(lab).upper())
                c.setFont("Times-Bold", 12)
                c.setFillColor(_DARK)
                c.drawString(x, self.y - 13, str(val))
                i += 1
            self.y -= 30
        self.c.setStrokeColor(_RULE)
        self.c.setLineWidth(0.5)
        self.c.line(_MARGIN, self.y + 13, _W - _MARGIN, self.y + 13)

    def _head_band(self, heads, cols):
        self.check_space(34)
        c = self.c
        c.setFillColor(_FAINT)
        c.rect(_MARGIN, self.y - 4.5, _W - 2 * _MARGIN, 14, fill=1, stroke=0)
        c.setStrokeColor(_LINE)
        c.setLineWidth(0.6)
        c.line(_MARGIN, self.y - 5.5, _W - _MARGIN, self.y - 5.5)
        c.setFont("Times-Bold", 7.5)
        c.setFillColor(_DARK)
        for h, (x, al) in zip(heads, cols):
            if al == "r":
                c.drawRightString(_MARGIN + x, self.y, h)
            else:
                c.drawString(_MARGIN + x, self.y, h)
        self.y -= 20

    def table(self, heads, cols, rows):
        """Tabel dengan kepala bergaris, garis pemisah baris, kolom rata kiri/kanan."""
        c = self.c
        self._head_band(heads, cols)
        for i, row in enumerate(rows):
            if self.y - 13 < 64:
                c.showPage()
                self.new_page()
                self._head_band(heads, cols)
            c.setStrokeColor(_RULE)
            c.setLineWidth(0.4)
            c.line(_MARGIN, self.y - 3.5, _W - _MARGIN, self.y - 3.5)
            c.setFont("Times-Roman", 9)
            c.setFillColor(_DARK)
            for v, (x, al) in zip(row, cols):
                if al == "r":
                    c.drawRightString(_MARGIN + x, self.y, str(v))
                else:
                    c.drawString(_MARGIN + x, self.y, str(v))
            self.y -= 13
        self.y -= 8

    def note(self, txt):
        self.check_space(30)
        self.c.setFont("Times-Italic", 9)
        self.c.setFillColor(_MUTED)
        self.c.drawString(_MARGIN, self.y, txt)
        self.y -= 18

    def signature(self):
        """Blok pengesahan penerbit (kaidah surat resmi: tanggal, ruang ttd, nama, jabatan)."""
        self.check_space(130)
        c = self.c
        cx = _W - _MARGIN - 100
        c.setFont("Times-Roman", 9)
        c.setFillColor(_MUTED)
        c.drawCentredString(cx, self.y, "Diterbitkan secara daring,")
        c.drawCentredString(cx, self.y - 12, _tanggal(_wib()))
        img = _signature_image()
        if img is not None:
            iw, ih = img.getSize()
            h_img = _SIGNATURE_MAX_H
            w_img = h_img * iw / ih if ih else 0.0
            if w_img > _SIGNATURE_MAX_W:
                w_img = _SIGNATURE_MAX_W
                h_img = w_img * ih / iw if iw else 0.0
            if w_img > 0 and h_img > 0:
                c.drawImage(img, cx - w_img / 2.0, self.y - 13 - h_img,
                            w_img, h_img, mask="auto")
        c.setFont("Times-Bold", 10)
        c.setFillColor(_DARK)
        c.drawCentredString(cx, self.y - 68, _AUTHOR)
        c.setStrokeColor(_DARK)
        c.setLineWidth(0.75)
        c.line(cx - 70, self.y - 71, cx + 70, self.y - 71)
        c.setFont("Times-Roman", 8)
        c.setFillColor(_MUTED)
        c.drawCentredString(cx, self.y - 81, _ROLE)
        self.y -= 101


def _render(data: dict, nomor: str, tanggal: str, total: int) -> bytes:
    """Satu kali render PDF (total=0 berarti pass hitung: nomor tanpa 'dari Y')."""
    buf = BytesIO()
    c = _canvas.Canvas(buf, pagesize=A4)
    doc = _Doc(c, nomor, tanggal, total)
    doc.new_page()

    # Blok judul resmi (hanya halaman pertama)
    c.setFont("Times-Bold", 15)
    c.setFillColor(_DARK)
    c.drawCentredString(_W / 2.0, doc.y, "LAPORAN RESMI TRACK RECORD")
    doc.y -= 16
    c.setFont("Times-Roman", 9)
    c.setFillColor(_MUTED)
    c.drawCentredString(
        _W / 2.0, doc.y,
        "Diterbitkan otomatis oleh sistem LAUMOLOGY - setiap angka berasal dari basis data sinyal & paper trading tercatat")
    doc.y -= 26

    outcomes = data.get("outcomes") or {}
    verdicts = data.get("verdicts") or {}
    last_scan = data.get("last_scan")

    doc.section("I. RINGKASAN")
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
        doc.section("II. VONIS SINYAL (SADAR-ARAH, H+5)")
        doc.kv_grid([
            ("Benar nyata", "{:.1f}%".format(float(v_pct.get("benar_nyata") or 0.0))),
            ("Untung, ikut pasar", "{:.1f}%".format(float(v_pct.get("untung_ikut_pasar") or 0.0))),
            ("Salah relatif oke", "{:.1f}%".format(float(v_pct.get("salah_relatif_ok") or 0.0))),
            ("Salah", "{:.1f}%".format(float(v_pct.get("salah") or 0.0))),
        ])

    doc.section("III. RIWAYAT SINYAL TERBARU")
    signals = data.get("signals") or []
    cols = [(0, "l"), (80, "l"), (122, "l"), (268, "r"),
            (316, "r"), (344, "l"), (453, "r")]
    heads = ["WAKTU", "KODE", "AKSI", "SKOR", "CONF", "GRADE", "HARGA"]
    if signals:
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
        doc.table(heads, cols, rows)
    else:
        doc.note("Belum ada sinyal tercatat - laporan ini terisi otomatis seiring sistem memindai bursa.")

    doc.section("IV. PENGESAHAN")
    doc.note("Laporan diterbitkan otomatis oleh sistem tanpa intervensi manual atas angka apa pun.")
    doc.note("Sumber: basis data lokal LAUMOLOGY (sinyal + paper trading). Bukan hasil trading uang sungguhan.")
    doc.signature()

    c.save()
    return buf.getvalue()


def _count_pages(pdf: bytes) -> int:
    """Hitung objek halaman pada PDF jadi (stabil antar versi reportlab)."""
    return len(_re.findall(rb"/Type\s*/Page\b", pdf))


def build_track_record_pdf(data: dict) -> bytes:
    """Bangun PDF dari dict summary() - tanpa proyeksi, angka apa adanya.

    Render dua-tahap agar footer bisa mencantumkan 'Halaman X dari Y':
    pass 1 menghitung total halaman, pass 2 menggambar final. Footer
    posisinya tetap (tidak memengaruhi pergantian halaman), jadi jumlah
    halaman kedua pass identik.
    """
    now_wib = _wib()
    nomor = "LTR/{}".format(now_wib.strftime("%Y%m%d/%H%M"))
    tanggal = "{}, {} WIB".format(_tanggal(now_wib), now_wib.strftime("%H:%M"))
    total = _count_pages(_render(data, nomor, tanggal, 0)) or 1
    return _render(data, nomor, tanggal, total)
