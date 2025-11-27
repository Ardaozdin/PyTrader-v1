import pandas as pd


def calistir(df):
    # --- AGRESİF SUPERTREND ---
    # 1. Trend Dönüşlerini Anında Yakalar (High/Low Kırılımı ile)
    # 2. Trend İçi Düzeltmelerde (Pullback) Tekrar Alım Yapar

    if "ST_Direction" in df.columns and "ST_Line" in df.columns:
        df["ST_Direction"] = df["ST_Direction"].fillna(0)

        # MTF Verisi Varsa Kullan (Daha güvenli agresiflik)
        has_mtf = "HTF_Direction" in df.columns
        if has_mtf:
            df["HTF_Direction"] = df["HTF_Direction"].fillna(method="ffill").fillna(0)

        for i in range(1, len(df)):
            # Anlık Fiyatlar
            close = df["close"].iloc[i]
            high = df["high"].iloc[i]
            low = df["low"].iloc[i]

            # İndikatörler
            st_dir = df["ST_Direction"].iloc[i]
            st_prev = df["ST_Direction"].iloc[i - 1]
            st_line = df["ST_Line"].iloc[i - 1]

            # RSI (Momentum Teyidi - Varsayılan 50)
            rsi = df["RSI"].iloc[i] if "RSI" in df.columns else 50

            # MTF Filtresi (Varsa)
            if has_mtf:
                htf_dir = df["HTF_Direction"].iloc[i]
                # Agresiflik: RSI çok güçlüyse (>65) ana trendi takma
                filter_buy = (htf_dir == 1) or (rsi > 65)
                filter_sell = (htf_dir == -1) or (rsi < 35)
            else:
                filter_buy = True
                filter_sell = True

            # --- AL (LONG) FIRSATLARI ---
            # 1. Klasik Dönüş
            buy_reversal = (st_dir == 1) and (st_prev == -1)
            # 2. Erken Kırılım (Mum kapanmadan ST çizgisini deldi)
            buy_breakout = (st_prev == -1) and (high > st_line)
            # 3. Trend İçi Fırsat (Trend Yeşil, Fiyat ST çizgisine yaklaştı ve sekti)
            buy_pullback = (
                (st_dir == 1) and (low <= st_line * 1.002) and (close > st_line)
            )

            if (buy_reversal or buy_breakout or buy_pullback) and filter_buy:
                if df["Signal"].iloc[i - 1] != 1:
                    df.loc[df.index[i], "Signal"] = 1

            # --- SAT (SHORT) FIRSATLARI ---
            sell_reversal = (st_dir == -1) and (st_prev == 1)
            sell_breakout = (st_prev == 1) and (low < st_line)
            sell_pullback = (
                (st_dir == -1) and (high >= st_line * 0.998) and (close < st_line)
            )

            if (sell_reversal or sell_breakout or sell_pullback) and filter_sell:
                if df["Signal"].iloc[i - 1] != -1:
                    df.loc[df.index[i], "Signal"] = -1

    return df
