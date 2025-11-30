import ccxt
import pandas as pd
import streamlit as st


@st.cache_resource
def borsa_baglantisi():
    return ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})


@st.cache_data(ttl=5)
def veri_getir(symbol, timeframe):
    try:
        exchange = borsa_baglantisi()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=1000)
        if not ohlcv:
            return None, None

        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

        # ✅ DÜZELTME BURADA:
        # Eskiden: df["timestamp"] = df["timestamp"].astype("int") -> Bu API'de 1970 hatası yapıyordu.
        # Yeni: unit="ms" diyerek bunun milisaniye olduğunu belirttik. Tarihler artık doğru.
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        print("Veri çekme hatası:", e)
        return None, None


@st.cache_data(ttl=5)
def dort_buyuk_coin_getir():
    coins = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
    try:
        exchange = borsa_baglantisi()
        return exchange.fetch_tickers(coins)
    except:
        return {}


@st.cache_data(ttl=5)
def piyasa_genel_analiz():
    try:
        exchange = borsa_baglantisi()
        tickers = exchange.fetch_tickers()
        items = []
        for s, d in tickers.items():
            if (
                "/USDT" in s
                and "UP/" not in s
                and "DOWN/" not in s
                and d["quoteVolume"] > 10000000
            ):
                items.append(
                    {
                        "Coin": s.replace("/USDT", ""),
                        "Sembol": s,
                        "Fiyat": float(d["last"]),
                        "Değişim (%)": float(d["percentage"]),
                        "Hacim ($)": float(d["quoteVolume"]),
                        "Yüksek (24s)": float(d["high"]),
                        "Düşük (24s)": float(d["low"]),
                    }
                )
        df = pd.DataFrame(items)
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        yukselenler = df.sort_values("Değişim (%)", ascending=False).head(5)
        dusenler = df.sort_values("Değişim (%)", ascending=True).head(5)
        hacim_liderleri = df.sort_values("Hacim ($)", ascending=False).head(15)
        return yukselenler, dusenler, hacim_liderleri
    except Exception:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


@st.cache_data(ttl=300)
def top_50_coin_getir():
    try:
        exchange = borsa_baglantisi()
        tickers = exchange.fetch_tickers()
        usdt_pairs = {
            k: v
            for k, v in tickers.items()
            if k.endswith("/USDT") and "UP/" not in k and "DOWN/" not in k
        }
        sorted_pairs = sorted(
            usdt_pairs.items(), key=lambda item: item[1]["quoteVolume"], reverse=True
        )
        top_50 = [pair[0] for pair in sorted_pairs[:50]]
        return top_50
    except:
        return []
