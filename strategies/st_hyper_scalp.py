import pandas as pd
import pandas_ta as ta


def calistir(df):
    # --- 9. HYPER SCALP STRATEGY (WILLIAMS %R) ---
    # Hedef: 1 Dakikalık grafikte yüksek işlem hacmi (30-40 işlem/gün).
    # Mantık: Williams %R indikatörü ile mikro dönüşleri yakalar.

    # 1. Gerekli İndikatörleri Hesapla (Eğer yoksa)
    # Williams %R (14 Periyot)
    if "WILLR" not in df.columns:
        # pandas_ta ile hesaplama
        df["WILLR"] = ta.willr(df["high"], df["low"], df["close"], length=14)

    # EMA 50 (Trend Filtresi)
    if "EMA_50" not in df.columns:
        df["EMA_50"] = ta.ema(df["close"], length=50)

    # Veri Temizliği (Hesaplama sonrası oluşan boşluklar için)
    df["WILLR"] = df["WILLR"].fillna(-50)
    df["EMA_50"] = df["EMA_50"].fillna(method="bfill")

    for i in range(1, len(df)):
        close = df["close"].iloc[i]
        ema_trend = df["EMA_50"].iloc[i]

        # Williams %R Değerleri
        willr = df["WILLR"].iloc[i]
        prev_willr = df["WILLR"].iloc[i - 1]

        # --- AL (LONG) MANTIĞI ---
        # 1. Trend Yukarı (Fiyat > EMA 50)
        # 2. Williams %R, -80 seviyesini AŞAĞIDAN YUKARI kesti (Aşırı satımdan çıkış)

        trend_up = close > ema_trend
        willr_cross_up = (prev_willr < -80) and (willr > -80)

        if trend_up and willr_cross_up:
            # Sinyal tekrarını önemseme (Her fırsatta gir - Agresif)
            if df["Signal"].iloc[i - 1] != 1:
                df.loc[df.index[i], "Signal"] = 1

        # --- SAT (SHORT) MANTIĞI ---
        # 1. Trend Aşağı (Fiyat < EMA 50)
        # 2. Williams %R, -20 seviyesini YUKARIDAN AŞAĞI kesti (Aşırı alımdan dönüş)

        trend_down = close < ema_trend
        willr_cross_down = (prev_willr > -20) and (willr < -20)

        if trend_down and willr_cross_down:
            if df["Signal"].iloc[i - 1] != -1:
                df.loc[df.index[i], "Signal"] = -1

    return df
