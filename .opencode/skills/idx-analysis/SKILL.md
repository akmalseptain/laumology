---
name: idx-analysis
description: Use when reviewing LAUMOLOGY stock analysis, technical indicators, factor scoring, signals, backtests, or IDX market data handling. Covers look-ahead bias, the analysis modules, and golden-test constraints.
---

# Skill: Analisis Saham IDX (LAUMOLOGY)

Panduan domain untuk quant/technical analyst saat meninjau mesin analisis IDX.

## Mesin analisis
- Indikator teknikal: `indicators.py` (MA, RSI, MACD, ATR, Bollinger, SuperTrend, dll).
- Faktor & skor: `factors.py` (`score_frame`).
- Sinyal & keputusan: `signals.py`, `decision.py`.
- Kalibrasi & validasi: `calibration.py`, `validation.py`.
- Backtest & risiko: `backtest.py`, `risk.py`, `metrics.py`, `validation.py`.
- Data pasar: `market.py`, `universe.py`, `stock.py`.

## Prinsip kebenaran
- **Look-ahead bias**: perhitungan pada bar `t` hanya boleh memakai data sampai `t` (termasuk `shift(1)` untuk sinyal yang dieksekusi di bar berikutnya).
- **Non-finite**: jaga pembagian nol, `NaN`, `Inf`. Uji dengan input batas.
- **Signifikansi**: keputusan promosi faktor harus punya dasar statistik (mis. lower-bound, bukan sekadar win-rate mentah).
- **Sumber tunggal**: horizon/parameter sebaiknya satu sumber agar konsisten antar-modul.

## Batasan perubahan
- Jangan mengubah rumus keuangan tanpa bukti atau fixture uji yang jelas.
- Golden `tests/test_engine.py:TestLegacyRegression` wajib tetap hijau.
- Perubahan sebaiknya aditif (field/parameter baru) agar skor lama tak berubah tanpa sengaja.

## Verifikasi
- Jalankan `py -3.14 tools/quality_gate.py` (mencakup regresi `tests.test_engine`).
- Untuk perubahan indikator, tambah uji kasus batas dan bandingkan dengan nilai yang diketahui.
