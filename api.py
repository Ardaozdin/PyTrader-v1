from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
from core.veri_motoru import veri_getir

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/data")
def get_data(symbol: str, timeframe: str):
    try:
        # 1. Veriyi Çek
        df, ticker = veri_getir(symbol, timeframe)

        if df is None or df.empty:
            return []

        # 2. Tarih Formatını Düzenle
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()

        df.columns = [c.lower() for c in df.columns]

        # Tarih sütununu bul
        date_col = None
        for name in ["date", "datetime", "tarih", "time", "timestamp"]:
            if name in df.columns:
                date_col = name
                break

        if date_col:
            df[date_col] = pd.to_datetime(df[date_col])
            df["time"] = df[date_col].astype("int64") // 10**9  # Saniye
        else:
            return []

        # 3. İNDİKATÖR (SMA 9 - İsteğine Göre Güncellendi)
        df["sma"] = df["close"].rolling(window=9).mean()

        # 4. AL/SAT SİNYALLERİ (SMA Kesişimi)
        df["signal"] = 0  # 0: Yok, 1: AL, -1: SAT

        df["prev_close"] = df["close"].shift(1)
        df["prev_sma"] = df["sma"].shift(1)

        # AL: Fiyat SMA'yı aşağıdan yukarı keserse
        df.loc[
            (df["close"] > df["sma"]) & (df["prev_close"] <= df["prev_sma"]), "signal"
        ] = 1

        # SAT: Fiyat SMA'yı yukarıdan aşağı keserse
        df.loc[
            (df["close"] < df["sma"]) & (df["prev_close"] >= df["prev_sma"]), "signal"
        ] = -1

        # 5. Temizlik ve Sıralama
        df = df.sort_values("time", ascending=True)
        df = df.drop_duplicates(subset=["time"], keep="last")
        df = df.fillna(0)

        # Gerekli sütunları seç
        final_df = df[["time", "open", "high", "low", "close", "sma", "signal"]]

        return final_df.to_dict(orient="records")

    except Exception as e:
        print(f"API Hatası: {e}")
        return []


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
