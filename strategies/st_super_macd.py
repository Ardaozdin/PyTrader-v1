import pandas as pd


def calistir(df):
    # --- SUPERTREND + MACD AGRESİF ---
    # Histogramın rengi açılsa bile (momentum azalsa bile) değil,
    # Histogram 0'ı kestiği an veya Supertrend döndüğü an.

    req = ["ST_Direction", "MACD_Hist"]
    if all(col in df.columns for col in req):
        for i in range(1, len(df)):
            st_dir = df["ST_Direction"].iloc[i]
            hist = df["MACD_Hist"].iloc[i]
            prev_hist = df["MACD_Hist"].iloc[i - 1]

            # Değişkenleri IF bloğundan önce tanımlıyoruz (Hata Çözümü)
            macd_improving = hist > prev_hist
            macd_worsening = hist < prev_hist

            # AL: (Supertrend Yeşil) VE (MACD Histogram Yükselişte)
            # Histogram negatiften pozitife geçiyor VEYA negatifte ama yükseliyor
            if (st_dir == 1) and macd_improving:
                # Histogram çok düşük değilse al
                if df["Signal"].iloc[i - 1] != 1:
                    df.loc[df.index[i], "Signal"] = 1

            # SAT: (Supertrend Kırmızı) VE (MACD Histogram Düşüşte)
            # elif bloğu artık doğrudan if'e bağlı
            elif (st_dir == -1) and macd_worsening:
                if df["Signal"].iloc[i - 1] != -1:
                    df.loc[df.index[i], "Signal"] = -1

    return df
