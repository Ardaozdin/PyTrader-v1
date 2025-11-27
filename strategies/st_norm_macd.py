import pandas as pd


def calistir(df):
    # --- AGRESİF NORMALIZED MACD ---
    # 0 çizgisini beklemez. MACD'nin yönünü (eğimini) takip eder.
    # StochRSI ile hızlı teyit alır.

    req = ["Norm_MACD", "Stoch_K", "Stoch_D"]
    if all(col in df.columns for col in req):
        for i in range(2, len(df)):
            # Veriler
            norm_macd = df["Norm_MACD"].iloc[i]
            prev_norm_macd = df["Norm_MACD"].iloc[i - 1]

            k = df["Stoch_K"].iloc[i]
            d = df["Stoch_D"].iloc[i]
            prev_k = df["Stoch_K"].iloc[i - 1]
            prev_d = df["Stoch_D"].iloc[i - 1]

            # Kesişimler
            stoch_cross_up = (prev_k < prev_d) and (k > d)
            stoch_cross_down = (prev_k > prev_d) and (k < d)

            # Eğim (Slope) Kontrolü
            macd_turning_up = norm_macd > prev_norm_macd
            macd_turning_down = norm_macd < prev_norm_macd

            # --- AL (LONG) ---
            # MACD yukarı dönüyor VE Stoch yukarı kesiyor
            # (MACD negatifte olsa bile alır - "Dip Avcısı")
            if macd_turning_up and stoch_cross_up:
                # Çok aşırı tepede değilse al (K < 90)
                if k < 90:
                    if df["Signal"].iloc[i - 1] != 1:
                        df.loc[df.index[i], "Signal"] = 1

            # --- SAT (SHORT) ---
            # MACD aşağı dönüyor VE Stoch aşağı kesiyor
            elif macd_turning_down and stoch_cross_down:
                # Çok aşırı dipte değilse sat (K > 10)
                if k > 10:
                    if df["Signal"].iloc[i - 1] != -1:
                        df.loc[df.index[i], "Signal"] = -1

    return df
