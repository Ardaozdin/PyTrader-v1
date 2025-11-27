import pandas as pd


def calistir(df):
    # --- AGRESİF PIVOT REVERSAL ---
    # Sadece 3 muma bakar. Ortadaki mum en dip/tepe ise dönüş kabul eder.

    for i in range(2, len(df)):
        close = df["close"].iloc[i]
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]

        # Önceki mumlar
        l1 = df["low"].iloc[i - 1]
        l2 = df["low"].iloc[i - 2]
        h1 = df["high"].iloc[i - 1]
        h2 = df["high"].iloc[i - 2]

        # AL: V-Dönüşü (Bullish Pivot)
        # Mum(i-1) en dipteydi, Mum(i-2) ve Mum(i) daha yüksek
        pivot_low = (l1 < l2) and (l1 < low)

        if pivot_low:
            # Teyit: Fiyat pivot mumunun tepesini geçti mi?
            if close > h1:
                if df["Signal"].iloc[i - 1] != 1:
                    df.loc[df.index[i], "Signal"] = 1

        # SAT: Ters-V Dönüşü (Bearish Pivot)
        # Mum(i-1) en tepedeydi
        pivot_high = (h1 > h2) and (h1 > high)

        if pivot_high:
            # Teyit: Fiyat pivot mumunun dibini kırdı mı?
            if close < l1:
                if df["Signal"].iloc[i - 1] != -1:
                    df.loc[df.index[i], "Signal"] = -1

    return df
