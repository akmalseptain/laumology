"""Factor engine: penskoran & konfluensi (inti + kandidat indikator mutakhir).

Modul ini HANYA berisi definisi faktor dan cara menghitungnya dari DataFrame
yang sudah diperkaya `indicators.add_indicators`. Dipakai oleh `signals`,
`validation`, dan `ml` supaya daftar faktor tidak terduplikasi.
"""
from __future__ import annotations

import pandas as pd

from config import settings

SCORE_COMPONENTS = ["tren", "momentum", "kekuatan", "volume", "setup", "risiko", "konfluensi"]
COMPONENT_MAX = {
    "tren": 20, "momentum": 20, "kekuatan": 15, "volume": 15,
    "setup": 15, "risiko": 15, "konfluensi": 15,
}

# Faktor inti (20) yang membentuk skor & confidence saat ini.
FACTOR_KEYS = [
    "harga>ma50", "ma50>ma200", "harga>ma200", "supertrend_up", "di_atas_cloud",
    "macd_bull", "macd_hist>0", "rsi_50_78", "adx_di_bull", "volume_surge",
    "obv_up", "cmf>0", "breakout_20", "candle_bull", "mfi>50",
    "squeeze_release", "momentum_up", "above_avwap", "chop_trend", "adr_sehat",
]

# Indikator mutakhir (HMA/KAMA/Aroon/Vortex/AO/UO/RVOL) sebagai KANDIDAT.
# Belum masuk skor; diuji dulu lewat validation.calibrate / ml.predict
# sebelum dipromosikan (lihat catatan Turn 25 D).
# W-0012: indikator yang sebelumnya "orphan" (dihitung tapi tak punya boolean
# terukur) kini dijadikan kandidat agar edge swing-nya bisa diuji pada horizon
# yang sama tanpa menyentuh `score_frame`/rumus.
CANDIDATE_FACTORS = [
    "harga>hma20", "hma20_naik", "harga>kama", "kama_naik",
    "aroon_bull", "vortex_bull", "ao>0", "ao_naik", "uo_bull", "rvol>1.2",
    "williams_r_bull", "stoch_k_cross", "cci_bull", "efi_bull", "gk_vol_rendah",
    "psar_bull", "harga>ema50", "ema21>ema50", "ha_bull", "bb_pct>0.5",
]

CANDIDATE_LABELS = {
    "harga>hma20": "Harga > HMA20",
    "hma20_naik": "HMA20 menanjak",
    "harga>kama": "Harga > KAMA",
    "kama_naik": "KAMA menanjak",
    "aroon_bull": "Aroon bullish (Up≥70)",
    "vortex_bull": "Vortex+ ≥ Vortex-",
    "ao>0": "Awesome Oscillator > 0",
    "ao_naik": "Awesome Oscillator naik",
    "uo_bull": "Ultimate Osc bullish (50-70)",
    "rvol>1.2": "RVOL > 1.2x",
    "williams_r_bull": "Williams %R > -50 (separuh atas)",
    "stoch_k_cross": "Stochastic %K ≥ %D (bullish)",
    "cci_bull": "CCI > 100 (tren kuat)",
    "efi_bull": "Elder Force Index > signal",
    "gk_vol_rendah": "Volatilitas GK < median 60-bar",
    "psar_bull": "Parabolic SAR di bawah harga",
    "harga>ema50": "Harga > EMA50",
    "ema21>ema50": "EMA21 di atas EMA50",
    "ha_bull": "Heikin Ashi naik",
    "bb_pct>0.5": "Bollinger %B > 0.5 (di atas pita tengah)",
}

# Ambang boolean kandidat baru — didokumentasikan (bukan angka sihir):
# - Williams %R ∈ [-100, 0]; > -50 berarti close di separuh atas rentang 14-bar.
# - CCI > 100 = tren naik kuat (klasik), beda dari `cci > 0` yang sudah di skor inti.
# - gk_vol dibanding median 60-bar dirinya sendiri (adaptif, tanpa ambang absolut).
# - psar_bull: arah Wilder = 1 (titik SAR di bawah harga). AF 0.02 / 0.20.
# - EMA50 dan EMA21 memakai rumus EMA yang sama dengan ema9/ema21.
# - ha_bull: close Heikin Ashi di atas open-nya (lilin naik).
# - bb_pct>0.5: harga di atas garis tengah Bollinger, bukan di luar pita.
WILLIAMS_R_BULL = -50.0
CCI_BULL = 100.0
GK_VOL_WINDOW = 60


def score_frame(d: pd.DataFrame) -> pd.DataFrame:
    idx = d.index
    close = d["Close"]

    tren = pd.Series(0.0, index=idx)
    tren += (close > d["ma20"]).astype(float) * 3.0
    tren += (d["ma20"] > d["ma50"]).astype(float) * 3.0
    tren += (d["ma50"] > d["ma200"]).astype(float) * 4.0
    tren += (close > d["ma200"]).astype(float) * 3.0
    tren += (d["st_dir"] == 1).astype(float) * 4.0
    tren += ((close > d["senkou_a"]) & (close > d["senkou_b"])).astype(float) * 3.0
    tren = tren.clip(0, 20)

    mom = pd.Series(0.0, index=idx)
    mom += ((d["rsi"] >= 50) & (d["rsi"] <= 70)).astype(float) * 4.0
    mom += (d["rsi"] > 70).astype(float) * 1.0
    mom += (d["rsi"] < 30).astype(float) * 2.0
    mom += (d["macd"] > d["macd_signal"]).astype(float) * 4.0
    mom += (d["macd_hist"] > 0).astype(float) * 4.0
    mom += (d["macd_hist"] > d["macd_hist"].shift(1)).astype(float) * 3.0
    mom += ((d["stoch_rsi_k"] > 0.5) & (d["stoch_rsi_k"] > d["stoch_rsi_d"])).astype(float) * 1.0
    mom += (d["cci"] > 0).astype(float) * 1.0
    mom = mom.clip(0, 20)

    kekuatan = pd.Series(0.0, index=idx)
    kekuatan += ((d["adx"] >= settings.adx_trend_threshold) & (d["plus_di"] > d["minus_di"])).astype(float) * 8.0
    kekuatan += ((d["adx"] >= 20) & (d["adx"] < settings.adx_trend_threshold) & (d["plus_di"] > d["minus_di"])).astype(float) * 4.0
    kekuatan += (d["adx"] > d["adx"].shift(3)).astype(float) * 3.0
    kekuatan = kekuatan.clip(0, 15)

    volume = pd.Series(0.0, index=idx)
    volume += (d["Volume"] > 1.2 * d["vol_ma20"]).astype(float) * 5.0
    volume += (d["obv"] > d["obv_ma20"]).astype(float) * 4.0
    volume += (d["cmf"] > 0).astype(float) * 3.0
    volume += (d["mfi"] > 50).astype(float) * 3.0
    volume = volume.clip(0, 15)

    setup = pd.Series(0.0, index=idx)
    setup += (close >= d["high20"] * 0.99).astype(float) * 5.0
    setup += d["cp_bullish"].astype(float) * 4.0
    setup += ((close > d["ema21"]) & (close <= d["ema21"] * 1.02) & (d["st_dir"] == 1)).astype(float) * 3.0
    setup += (close >= d["bb_upper"] * 0.995).astype(float) * 3.0
    setup = setup.clip(0, 15)

    risiko = pd.Series(0.0, index=idx)
    risiko += (d["atr_pct"] < 3).astype(float) * 6.0
    risiko += ((d["atr_pct"] >= 3) & (d["atr_pct"] < 5)).astype(float) * 3.0
    risiko += (d["rsi"] < 78).astype(float) * 3.0
    risiko += (close > d["ma50"]).astype(float) * 3.0
    risiko = risiko.clip(0, 15)

    konf = pd.Series(0.0, index=idx)
    konf += (d["squeeze_off"] & (d["sqz_mom"] > 0) & (d["sqz_dir"] > 0)).astype(float) * 4.0
    konf += (close > d["avwap"]).astype(float) * 3.0
    konf += (d["chop"] < 50).astype(float) * 3.0
    konf += ((d["adr_pct"] >= 1.5) & (d["adr_pct"] <= 8)).astype(float) * 3.0
    konf += (d["atr_pctl"] <= 80).astype(float) * 2.0
    konf = konf.clip(0, 15)

    out = pd.DataFrame(
        {
            "tren": tren,
            "momentum": mom,
            "kekuatan": kekuatan,
            "volume": volume,
            "setup": setup,
            "risiko": risiko,
            "konfluensi": konf,
        },
        index=idx,
    )
    out["score"] = out[SCORE_COMPONENTS].sum(axis=1).clip(0, 100)
    return out


def confluence_frame(d: pd.DataFrame) -> pd.DataFrame:
    close = d["Close"]
    idx = d.index
    f = pd.DataFrame(index=idx)
    f["harga>ma50"] = close > d["ma50"]
    f["ma50>ma200"] = d["ma50"] > d["ma200"]
    f["harga>ma200"] = close > d["ma200"]
    f["supertrend_up"] = d["st_dir"] == 1
    f["di_atas_cloud"] = (close > d["senkou_a"]) & (close > d["senkou_b"])
    f["macd_bull"] = d["macd"] > d["macd_signal"]
    f["macd_hist>0"] = d["macd_hist"] > 0
    f["rsi_50_78"] = (d["rsi"] >= 50) & (d["rsi"] <= 78)
    f["adx_di_bull"] = (d["adx"] >= 20) & (d["plus_di"] > d["minus_di"])
    f["volume_surge"] = d["Volume"] > 1.2 * d["vol_ma20"]
    f["obv_up"] = d["obv"] > d["obv_ma20"]
    f["cmf>0"] = d["cmf"] > 0
    f["breakout_20"] = close >= d["high20"] * 0.99
    f["candle_bull"] = d["cp_bullish"]
    f["mfi>50"] = d["mfi"] > 50
    f["squeeze_release"] = d["squeeze_off"] & (d["sqz_mom"] > 0)
    f["momentum_up"] = d["sqz_dir"] > 0
    f["above_avwap"] = close > d["avwap"]
    f["chop_trend"] = d["chop"] < 50
    f["adr_sehat"] = (d["adr_pct"] >= 1.5) & (d["adr_pct"] <= 8)
    f["confidence"] = f[FACTOR_KEYS].sum(axis=1) / len(FACTOR_KEYS) * 100.0
    return f


def candidate_frame(d: pd.DataFrame) -> pd.DataFrame:
    """Faktor dari indikator mutakhir (kandidat, di luar skor inti)."""
    close = d["Close"]
    idx = d.index
    f = pd.DataFrame(index=idx)
    f["harga>hma20"] = close > d["hma20"]
    f["hma20_naik"] = d["hma20"] > d["hma20"].shift(1)
    f["harga>kama"] = close > d["kama"]
    f["kama_naik"] = d["kama"] > d["kama"].shift(3)
    f["aroon_bull"] = (d["aroon_up"] >= 70) & (d["aroon_up"] >= d["aroon_down"])
    f["vortex_bull"] = d["vortex_plus"] >= d["vortex_minus"]
    f["ao>0"] = d["ao"] > 0
    f["ao_naik"] = d["ao"] > d["ao"].shift(1)
    f["uo_bull"] = (d["uo"] >= 50) & (d["uo"] <= 70)
    f["rvol>1.2"] = d["rvol"] > 1.2
    f["williams_r_bull"] = d["williams_r"] > WILLIAMS_R_BULL
    f["stoch_k_cross"] = d["stoch_k"] >= d["stoch_d"]
    f["cci_bull"] = d["cci"] > CCI_BULL
    f["efi_bull"] = d["efi"] > d["efi_signal"]
    f["gk_vol_rendah"] = d["gk_vol"] < d["gk_vol"].rolling(
        GK_VOL_WINDOW, min_periods=GK_VOL_WINDOW // 3
    ).median()
    f["psar_bull"] = d["psar_dir"] == 1
    f["harga>ema50"] = close > d["ema50"]
    f["ema21>ema50"] = d["ema21"] > d["ema50"]
    f["ha_bull"] = d["ha_close"] > d["ha_open"]
    f["bb_pct>0.5"] = d["bb_pct"] > 0.5
    f["confidence"] = f[CANDIDATE_FACTORS].sum(axis=1) / len(CANDIDATE_FACTORS) * 100.0
    return f
