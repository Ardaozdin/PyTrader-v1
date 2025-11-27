import pandas as pd


def calistir(df):
    # --- HMA 9 AGRESİF SCALP ---
    # SMA dosya adı altında HMA 9 çalışır.
    # Kapanışı beklemez, fiyata dokunduğu an girer.

    hma_col = "HMA_9"
    # HMA 9 yoksa HMA 14'e bak, yoksa çık
    if hma_col not in df.columns:
        if "HMA_14" in df.columns:
            hma_col = "HMA_14"
        else:
            return df

    for i in range(1, len(df)):
        high = df["high"].iloc[i]
        low = df["low"].iloc[i]
        hma = df[hma_col].iloc[i]

        # --- AL (LONG) ---
        # Fiyatın tepesi HMA'yı geçtiği an AL
        if high > hma:
            # Filtre: Önceki mum HMA'nın altındaysa (Kırılım yeni)
            if df["close"].iloc[i - 1] < df[hma_col].iloc[i - 1]:
                if df["Signal"].iloc[i - 1] != 1:
                    df.loc[df.index[i], "Signal"] = 1

        # --- SAT (SHORT) ---
        # Fiyatın dibi HMA'yı kırdığı an SAT
        elif low < hma:
            if df["close"].iloc[i - 1] > df[hma_col].iloc[i - 1]:
                if df["Signal"].iloc[i - 1] != -1:
                    df.loc[df.index[i], "Signal"] = -1

    return df
