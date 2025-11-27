import pandas as pd


def calistir(df):
    # --- AGRESİF EMA + RSI ---
    # Fiyat EMA'nın üzerindeyken RSI'daki her düşüşü alım fırsatı bilir.

    if "EMA_20" in df.columns and "RSI" in df.columns:
        for i in range(1, len(df)):
            # Anlık Fiyat (High/Low) Kullanımı
            high = df["high"].iloc[i]
            low = df["low"].iloc[i]
            close = df["close"].iloc[i]

            ema = df["EMA_20"].iloc[i]
            rsi = df["RSI"].iloc[i]
            prev_rsi = df["RSI"].iloc[i - 1]

            # --- AL (LONG) ---
            # 1. Fiyat EMA 20'nin üstünde (Trend)
            # 2. RSI 45'i yukarı kesti (Düzeltme bitti, güçleniyor)
            #    VEYA Fiyat EMA'yı yukarı kırdı

            trend_up = close > ema
            rsi_rebound = (prev_rsi < 50) and (rsi > 50)  # 50 Kırılımı
            price_breakout = (df["close"].iloc[i - 1] < df["EMA_20"].iloc[i - 1]) and (
                high > ema
            )

            if (trend_up and rsi_rebound) or price_breakout:
                if rsi < 80:  # Tepede değilse
                    if df["Signal"].iloc[i - 1] != 1:
                        df.loc[df.index[i], "Signal"] = 1

            # --- SAT (SHORT) ---
            trend_down = close < ema
            rsi_drop = (prev_rsi > 50) and (rsi < 50)
            price_breakdown = (df["close"].iloc[i - 1] > df["EMA_20"].iloc[i - 1]) and (
                low < ema
            )

            if (trend_down and rsi_drop) or price_breakdown:
                if rsi > 20:
                    if df["Signal"].iloc[i - 1] != -1:
                        df.loc[df.index[i], "Signal"] = -1

    return df
