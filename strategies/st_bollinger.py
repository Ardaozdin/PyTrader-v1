import pandas as pd
import numpy as np


def calistir(df):
    # --- 8. SMART BOLLINGER REVERSAL (DAHA DOĞRU SONUÇLAR) ---
    # Hedef: Sadece banda değmesi yetmez, fiyatın bandın içine
    # güçlü bir şekilde geri dönüp kapanmasını bekler.
    # Bu, "Bandı yırtıp giden" trendlerde terste kalmayı önler.

    req = ["BB_Upper", "BB_Lower", "BB_Mid"]

    if not all(col in df.columns for col in req):
        return df

    for i in range(1, len(df)):
        # Mum Verileri
        close = df["close"].iloc[i]
        open_p = df["open"].iloc[i]
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]

        # Bantlar
        bb_upper = df["BB_Upper"].iloc[i]
        bb_lower = df["BB_Lower"].iloc[i]

        # --- AL (LONG) SİNYALİ ---
        # 1. Temas: Fiyat Alt Banda değdi veya altına sarktı.
        # 2. Dönüş: Mum YEŞİL kapattı (Alıcılar geldi).
        # 3. Teyit: Kapanış fiyatı tekrar Alt Bandın ÜZERİNE çıktı (İçeri girdi).

        touched_lower = low <= bb_lower
        is_green = close > open_p
        closed_inside = close > bb_lower  # Bandın içinde kapattı

        if touched_lower and is_green and closed_inside:
            # Zaten işlemde değilsek AL
            if df["Signal"].iloc[i - 1] != 1:
                df.loc[df.index[i], "Signal"] = 1

        # --- SAT (SHORT) SİNYALİ ---
        # 1. Temas: Fiyat Üst Banda değdi veya üstüne çıktı.
        # 2. Dönüş: Mum KIRMIZI kapattı (Satıcılar geldi).
        # 3. Teyit: Kapanış fiyatı tekrar Üst Bandın ALTINA indi (İçeri girdi).

        touched_upper = high >= bb_upper
        is_red = close < open_p
        closed_inside_down = close < bb_upper  # Bandın içinde kapattı

        if touched_upper and is_red and closed_inside_down:
            # Zaten işlemde değilsek SAT
            if df["Signal"].iloc[i - 1] != -1:
                df.loc[df.index[i], "Signal"] = -1

    return df
