# Laumology

Sistem analisis & screening saham Bursa Efek Indonesia (IDX) berbasis Python/pandas, dengan prinsip utama **objektif dan kausal**: semua indikator bebas look-ahead, event didefinisikan a priori, tanpa tuning parameter yang menyesuaikan hasil.

Live: <https://laumology.vercel.app>

## Fitur

- **Indikator teknikal kausal** (`indicators.py`) — puluhan kolom (MA/EMA, RSI, MACD, ATR, Supertrend, Squeeze, Choppiness, PSAR, Bollinger, Donchian, VWAP anchored otomatis, Heikin Ashi, dll.). Pagar uji truncation-invariance memastikan tidak ada indikator yang bocor look-ahead.
- **Skoring & sinyal 0–100** (`signals.py`) — dari STRONG BUY sampai AVOID, lengkap dengan harga entry, stop loss, dan take profit.
- **Screening & universe** (`screener.py`, `universe.py`) — misalnya daftar LQ45.
- **Paper trading & track record** (`store.py`, `routes/trackrecord.py`, `templates/trackrecord.html`) — riwayat sinyal dan hasil paper trading: win rate, expectancy, payoff, Kelly, kurva ekuitas. Semua angka murni dari DB lokal, tanpa proyeksi.
- **Uji edge indikator** (`indicator_edge.py`) — event study 22 event a priori: hit rate vs baseline, uplift, stabilitas antar semester (worst-half hit rate), masking bar pemanasan.
- **Backtest & validasi** (`backtest.py`, `validation.py`, `consensus_backtest.py`) — desain walk-forward, jujur terhadap data.
- **Berita, fundamental & data eksternal** (`news.py`, `fundamentals.py`, `external.py`, `realtime.py`).
- **Web** (`webapp.py`, `routes/`, `templates/`, `static/`) — Flask, server-rendered, CSP ketat tanpa JS inline.

## Instalasi

```bash
git clone https://github.com/akmalseptain/laumology.git
cd laumology
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # isi kredensial sesuai kebutuhan (opsional untuk pengujian)
```

## Menjalankan

```bash
# Web (lokal)
python webapp.py

# Produksi
gunicorn webapp:app

# Scheduler (scan berkala)
python scheduler.py

# Uji edge indikator terhadap data IDX
python indicator_edge.py --list lq45 --horizon 5 --top 25 --out edge_report.json
```

## Pengujian

```bash
PYTHONPATH=. python -m unittest discover -s tests -p "test_*.py" -v
```

Suite di `tests/test_engine.py` memakai data sintetis dan mengosongkan `API_KEY` saat pengujian, sehingga bisa dijalankan tanpa kredensial. GitHub Actions menjalankan suite yang sama pada setiap push dan pull request.

## Struktur (ringkas)

| Berkas / direktori | Peran |
| --- | --- |
| `webapp.py` | Aplikasi Flask utama, mendaftar blueprint dari `routes/` |
| `routes/` | Blueprint API & halaman (screener, track record, dll.) |
| `indicators.py` | Seluruh indikator teknikal (kausal) |
| `signals.py` | Analisis & skoring sinyal 0–100 |
| `screener.py`, `universe.py` | Pemilihan watchlist & screening |
| `data.py` | Pengambilan OHLCV |
| `store.py` | SQLite: sinyal, scan, paper trading |
| `metrics.py` | Metrik risiko: Sharpe, Calmar, win rate, payoff, Kelly, expectancy |
| `indicator_edge.py` | Event study edge indikator |
| `backtest.py`, `validation.py` | Backtest & validasi |
| `scheduler.py` | Job scan berkala |
| `templates/`, `static/` | Tampilan web |

## Prinsip proyek

1. **Kausal** — tidak ada look-ahead; nilai bar ke-*t* hanya dari data sampai bar *t*.
2. **Objektif** — event/aturan didefinisikan a priori, bukan dipilih setelah melihat hasil.
3. **Jujur** — skor 0–100 tidak diubah tanpa bukti edge; angka track record hanya dari data nyata.
4. **Sadar pemanasan** — bar awal (warm-up) dibuang dari analisis edge/ML/backtest.

## Disclaimer

Output proyek ini bukan nasihat keuangan. Keputusan investasi sepenuhnya tanggung jawab masing-masing.

## Lisensi

[MIT](LICENSE)
