from __future__ import annotations

from dataclasses import dataclass


LQ45 = [
    "ACES", "ADMR", "ADRO", "AKRA", "AMRT", "ANTM", "ARTO", "ASII",
    "BBCA", "BBNI", "BBRI", "BBTN", "BRIS", "BRPT", "BUKA", "CPIN",
    "EMTK", "ERAA", "EXCL", "GOTO", "HRUM", "ICBP", "INCO", "INDF",
    "INKP", "INTP", "ITMG", "JPFA", "JSMR", "KLBF", "MDKA", "MEDC",
    "MIKA", "MNCN", "MTEL", "PGAS", "PGEO", "PTBA", "SIDO", "SMGR",
    "SMRA", "TLKM", "TOWR", "UNTR", "UNVR",
]

IDX30 = [
    "ACES", "ADRO", "AMRT", "ANTM", "ASII", "BBCA", "BBNI", "BBRI",
    "BBTN", "BMRI", "BRPT", "CPIN", "GOTO", "ICBP", "INDF", "INTP",
    "ITMG", "KLBF", "MDKA", "MTEL", "PGAS", "PGEO", "PTBA", "SMGR",
    "TLKM", "TOWR", "UNTR", "UNVR", "MEDC", "ADMR",
]

WATCHLIST_PRESETS = {
    "lq45": LQ45,
    "idx30": IDX30,
    "bluechip": ["BBCA", "BBRI", "BMRI", "TLKM", "ASII", "UNTR", "ICBP", "INDF", "KLBF", "UNVR"],
    "bank": ["BBCA", "BBRI", "BMRI", "BBNI", "BBTN", "BRIS", "ARTO", "BTPS"],
    "energi": ["ADRO", "PTBA", "ITMG", "HRUM", "MEDC", "PGAS", "PGEO", "AKRA", "INDY"],
    "tambang": ["ANTM", "INCO", "MDKA", "TINS", "PTBA", "ADRO", "HRUM", "NCKL"],
    "konsumer": ["ICBP", "INDF", "UNVR", "AMRT", "ACES", "SIDO", "CPIN", "JPFA", "MYOR", "GGRM"],
    "telko": ["TLKM", "EXCL", "ISAT", "TOWR", "MTEL"],
    "teknologi": ["GOTO", "BUKA", "EMTK", "DCII", "MTDL"],
    "properti": ["SMRA", "BSDE", "CTRA", "PWON", "ASRI"],
    "infrastruktur": ["JSMR", "TOWR", "MTEL", "PGAS", "PGEO"],
    "kesehatan": ["MIKA", "KLBF", "SIDO", "HEAL", "SILO"],
    "industri": ["ASII", "UNTR", "SMGR", "INTP", "BRPT", "TPIA"],
}

SECTORS = {
    "BBCA": "Perbankan", "BBRI": "Perbankan", "BMRI": "Perbankan", "BBNI": "Perbankan",
    "BBTN": "Perbankan", "BRIS": "Perbankan", "ARTO": "Perbankan", "BTPS": "Perbankan",
    "ICBP": "Konsumer", "INDF": "Konsumer", "UNVR": "Konsumer", "AMRT": "Konsumer",
    "ACES": "Konsumer", "SIDO": "Konsumer", "CPIN": "Konsumer", "JPFA": "Konsumer",
    "MYOR": "Konsumer", "GGRM": "Konsumer", "HMSP": "Konsumer", "KLBF": "Kesehatan",
    "MIKA": "Kesehatan", "HEAL": "Kesehatan", "SILO": "Kesehatan",
    "TLKM": "Telekomunikasi", "EXCL": "Telekomunikasi", "ISAT": "Telekomunikasi",
    "TOWR": "Telekomunikasi", "MTEL": "Telekomunikasi",
    "ADRO": "Energi", "PTBA": "Energi", "ITMG": "Energi", "HRUM": "Energi",
    "MEDC": "Energi", "PGAS": "Energi", "PGEO": "Energi", "AKRA": "Energi",
    "INDY": "Energi", "DSSA": "Energi",
    "ANTM": "Tambang", "INCO": "Tambang", "MDKA": "Tambang", "TINS": "Tambang",
    "NCKL": "Tambang", "BRMS": "Tambang", "PSAB": "Tambang",
    "INTP": "Semen & Material", "SMGR": "Semen & Material", "BRPT": "Petrokimia",
    "TPIA": "Petrokimia", "ADMR": "Batubara", "GOTO": "Teknologi", "BUKA": "Teknologi",
    "EMTK": "Teknologi", "DCII": "Teknologi", "MTDL": "Teknologi",
    "ASII": "Industri", "UNTR": "Industri", "JSMR": "Infrastruktur",
    "SMRA": "Properti", "BSDE": "Properti", "CTRA": "Properti", "PWON": "Properti",
    "ASRI": "Properti", "ERAA": "Perdagangan", "MNCN": "Media", "SCMA": "Media",
    "CPIN": "Peternakan", "JPFA": "Peternakan",
}


def sector_of(ticker: str) -> str:
    return SECTORS.get(ticker.upper().strip(), "Lainnya")



@dataclass
class Settings:
    period: str = "1y"
    interval: str = "1d"
    cache_dir: str = ".cache"
    cache_ttl_hours: float = 1.0
    quote_ttl_seconds: float = 10.0

    ma_short: int = 20
    ma_mid: int = 50
    ma_long: int = 200
    ema_short: int = 9
    ema_mid: int = 21
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    stoch_k: int = 14
    stoch_d: int = 3
    breakout_window: int = 20

    atr_sl_mult: float = 2.0
    tp1_rr: float = 1.5
    tp2_rr: float = 3.0
    tp3_rr: float = 4.5
    trail_mult: float = 3.0
    trail_period: int = 22

    capital: float = 100_000_000.0
    risk_pct: float = 1.5
    lot_size: int = 100

    benchmark: str = "^JKSE"
    benchmark_suffix: str = ""

    supertrend_period: int = 10
    supertrend_mult: float = 3.0
    adx_period: int = 14
    adx_trend_threshold: float = 25.0
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou: int = 52

    buy_score: int = 65
    strong_buy_score: int = 80
    sell_score: int = 40

    # --- Transaction costs & execution realism (IDX retail approx) ---
    fee_buy_pct: float = 0.15      # komisi beli
    fee_sell_pct: float = 0.25     # komisi jual + pajak penjualan
    slippage_pct: float = 0.10     # asumsi selip harga
    liquidity_max_pct: float = 1.0 # maksimum % dari rata-rata nilai transaksi 20 hari

    # --- Risk limits (portfolio governance) ---
    max_positions: int = 10
    max_sector_pct: float = 40.0
    max_position_pct: float = 20.0
    max_drawdown_alert: float = 15.0


settings = Settings()

# Serverless (Vercel) filesystem read-only: arahkan cache ke /tmp
import os as _os  # noqa: E402

if _os.environ.get("VERCEL") or _os.environ.get("VERCEL_ENV"):
    settings.cache_dir = "/tmp/.cache"
