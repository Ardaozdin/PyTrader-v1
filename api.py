from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
import sys
import os

# Core modülleri görebilmesi için yol ayarı
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# SENİN MODÜLLERİN
from core import veri_motoru as vm
from core import teknik_analiz as ta
from core import backtest as bm
from strategies import strateji as sm

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standart Ayarlar
AYARLAR = {
    "sma_aktif": True,
    "sma_len": 9,
    "bb_aktif": True,
    "cp_aktif": True,
    "ema_aktif": True,
    "adx_aktif": True,
}


@app.get("/data")
def get_data(
    symbol: str,
    timeframe: str,
    strategy: str = "Pure_Supertrend_Strategy",
    tp: float = 0.006,
    sl: float = 0.01,
):
    print(
        f"📡 İSTEK GELDİ: {symbol} | {timeframe} | {strategy}"
    )  # Terminalde görmek için

    try:
        # 1. VERİYİ ÇEK
        df, ticker = vm.veri_getir(symbol, timeframe)

        if df is None or df.empty:
            print("❌ Veri boş geldi.")
            return []

        # 2. FORMAT DÜZELTME VE SIRALAMA (Çok Önemli)
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

        # VERİYİ ESKİDEN YENİYE SIRALA (TradingView Kuralı)
        df = df.sort_values("time", ascending=True)
        df = df.reset_index(drop=True)

        # 3. İNDİKATÖRLERİ EKLE
        df = ta.indikator_ekle(df, AYARLAR)
        df.fillna(0, inplace=True)

        # 4. STRATEJİ SİNYALLERİNİ ÜRET
        try:
            df = sm.sinyal_uret(df, strategy)
        except:
            # Hata olursa varsayılanı kullan
            df = sm.sinyal_uret(df, "Pure_Supertrend_Strategy")

        # 5. BACKTEST YAP (Gerçek İşlemleri Bul)
        # Backtest motoru da sıralı veri ister, veri zaten sıralı.
        sonuc, gecmis, df_final = bm.backtest_yap(
            df, 1000, tp_oran=float(tp), sl_oran=float(sl)
        )

        # 6. İŞLEM GEÇMİŞİNİ GRAFİK SİNYALİNE ÇEVİR
        # Sadece Backtest'in onayladığı (Giriş/Çıkış) noktalarına ok koyuyoruz.
        df_final["signal"] = 0

        if gecmis:
            trades_df = pd.DataFrame(gecmis)
            # Tarih formatını eşle
            trades_df["timestamp"] = pd.to_datetime(trades_df["Tarih"])

            for _, trade in trades_df.iterrows():
                # İşlemin olduğu mumu bul
                match = df_final[df_final["time"] == trade["timestamp"].timestamp()]
                if not match.empty:
                    idx = match.index[0]
                    tur = trade["Tür"]

                    # Sinyal kodları: 1=AL(Yeşil Ok), -1=SAT(Kırmızı Ok)
                    if "AL" in tur:
                        df_final.at[idx, "signal"] = 1
                    elif "SAT" in tur or "TP" in tur or "STOP" in tur:
                        df_final.at[idx, "signal"] = -1

        # 7. GEREKSİZ VERİYİ TEMİZLE VE GÖNDER
        # SMA yoksa kapanış fiyatını koy (Çizgi düzgün görünsün)
        if "HMA_9" in df_final.columns:
            df_final["sma"] = df_final["HMA_9"]
        elif "SMA" in df_final.columns:
            df_final["sma"] = df_final["SMA"]
        else:
            df_final["sma"] = df_final["close"]

        df_final = df_final.fillna(0)

        export_cols = ["time", "open", "high", "low", "close", "sma", "signal"]
        return df_final[export_cols].to_dict(orient="records")

    except Exception as e:
        print(f"🔥 API Hatası: {e}")
        return []


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
