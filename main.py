import streamlit as st
import pandas as pd
import time
import datetime
import os
from streamlit_lightweight_charts import renderLightweightCharts

# =============================================================================
# 1. MODÜL VE STRATEJİ YÜKLEME (GÜVENLİ ALAN)
# =============================================================================
try:
    from core import veri_motoru as vm
    from core import teknik_analiz as ta
    from core import backtest as bm
    from core import db_manager as dbm
    from strategies import strateji as sm  # Ana yönetici modül
except ImportError as e:
    st.error(f"Çekirdek Modül Hatası: {e}")
    st.stop()

# --- Dinamik Strateji Listesi Oluşturma ---
# Bu liste, sadece başarıyla import edilen stratejileri içerir.
MEVCUT_STRATEJILER = []

# 1. AÇIK STRATEJİLER (GitHub'da var)
try:
    from strategies import st_pure_supertrend
    from strategies import st_HMA_simple
    from strategies import st_bollinger

    MEVCUT_STRATEJILER.extend(
        [
            "Pure_Supertrend_Strategy",
            "HMA_Simple_Strategy",
            "Bollinger_Reversal_Strategy",
        ]
    )
except ImportError:
    # Eğer bu dosyalar yoksa bile program çökmesin (gerçi bunlar public ama önlem)
    pass

# 2. GİZLİ STRATEJİLER (Sadece sende var)
# Tek tek deniyoruz. Dosya varsa listeye ekliyoruz.

try:
    from strategies import st_ema_rsi

    MEVCUT_STRATEJILER.append("EMA_RSI_Strategy")
except ImportError:
    pass

try:
    from strategies import st_norm_macd

    MEVCUT_STRATEJILER.append("Normalized_MACD_Strategy")
except ImportError:
    pass

try:
    from strategies import st_ai_scalp

    MEVCUT_STRATEJILER.append("Ai_Scalp")
except ImportError:
    pass

try:
    from strategies import st_pivot_rev

    MEVCUT_STRATEJILER.append("Pivot_Reversal_Strategy")
except ImportError:
    pass

try:
    from strategies import st_ai_trend

    MEVCUT_STRATEJILER.append("AI_Trend_Predictor")
except ImportError:
    pass

try:
    from strategies import st_hyper_scalp

    MEVCUT_STRATEJILER.append("Hyper_Scalp_Strategy")
except ImportError:
    pass

# =============================================================================
# VERİTABANI VE ARAYÜZ BAŞLANGICI
# =============================================================================

# --- VERİTABANI BAŞLATMA ---
dbm.veritabanini_hazirla()

# --- CSS ---
st.set_page_config(page_title="Pro Algo Bot", page_icon="💎", layout="wide")
st.markdown(
    """
<style>
    .stApp { background-color: #0e1117; }
    div[data-testid="stMetric"] { background: linear-gradient(145deg, #1e2329, #161b22); border: 1px solid #333; border-radius: 12px; padding: 10px; }
    .neon-text { color: #fff; text-shadow: 0 0 10px rgba(0, 212, 255, 0.7); }
    .prediction-box { padding: 15px; border-radius: 15px; margin-bottom: 20px; text-align: center; font-weight: bold; font-size: 1.1em; border: 2px solid; }
    .pred-bull { background-color: rgba(0, 255, 0, 0.05); border-color: #00FF00; color: #00FF00; }
    .pred-bear { background-color: rgba(255, 0, 0, 0.05); border-color: #FF0000; color: #FF0000; }
    .sub-text { font-size: 0.8em; opacity: 0.8; margin-top: 5px; font-weight: normal; color: #ddd; }
</style>
""",
    unsafe_allow_html=True,
)

if "arama_kodu" not in st.session_state:
    st.session_state.arama_kodu = ""


def aramayi_temizle():
    st.session_state.arama_kodu = ""


# --- SIDEBAR ---
st.sidebar.title("🎛️ Kontrol Paneli")
if st.sidebar.button("🏠 ANA DASHBOARD", use_container_width=True):
    aramayi_temizle()
st.sidebar.markdown("---")

# MOD SEÇİMİ
calisma_modu = st.sidebar.radio(
    "Çalışma Modu",
    [
        "Ana Sayfa (Dashboard)",
        "Tek Coin Analizi",
        "Top 50 Genel Rapor (Tüm Stratejiler)",
    ],
)

zaman = st.sidebar.selectbox("⏱️ Zaman", ["1m", "3m", "5m", "15m", "1h", "4h"], index=2)

# AYARLAR
ayar_sozlugu = {
    "sma_aktif": True,
    "sma_len": 9,
    "bb_aktif": True,
    "cp_aktif": True,
    "ema_aktif": True,
    "adx_aktif": True,
}

# ARTIK STRATEJİ LİSTESİ DİNAMİK OLARAK YUKARIDAN GELİYOR
STRATEJI_LISTESI = MEVCUT_STRATEJILER

# BACKTEST AYARLARI
if calisma_modu == "Tek Coin Analizi":
    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Backtest Ayarları")
    user_tp = st.sidebar.number_input(
        "Hedef Kâr (TP) %",
        min_value=0.1,
        max_value=20.0,
        value=0.6,
        step=0.1,
        format="%.1f",
    )
    user_sl = st.sidebar.number_input(
        "Zarar Durdur (SL) %",
        min_value=0.1,
        max_value=10.0,
        value=0.8,
        step=0.1,
        format="%.1f",
    )
    tp_val = user_tp / 100
    sl_val = user_sl / 100

    # Tek Coin için Strateji Seçimi
    strateji_secimi = st.sidebar.selectbox("🧠 Strateji Seç", STRATEJI_LISTESI)

    arama = (
        st.sidebar.text_input("🔍 Coin Ara (Örn: BTC)", key="arama_kodu")
        .upper()
        .strip()
    )
    analiz_baslat = st.sidebar.button("Analiz Et 🚀", use_container_width=True)
    oto_yenileme = st.sidebar.toggle("Canlı Veri Akışı", value=True)

    # Görünürlük
    st.sidebar.markdown("---")
    st.sidebar.subheader("Görünürlük")
    sma_vis = st.sidebar.checkbox("HMA 9", True)
    bb_vis = st.sidebar.checkbox("Bollinger", True)
    stoch_vis = st.sidebar.checkbox("StochRSI Paneli", True)
    adx_vis = st.sidebar.checkbox("ADX Paneli", True)
else:
    # Scanner Modunda sabit ayarlar (Hız için)
    tp_val = 0.006  # %0.6
    sl_val = 0.008  # %1.0
    arama = None

# ==========================================
# MOD 1: TEK COIN ANALİZİ
# ==========================================
if calisma_modu == "Tek Coin Analizi" and arama:
    symbol = f"{arama}/USDT" if "/" not in arama else arama

    if oto_yenileme:
        df, ticker = vm.veri_getir(symbol, zaman)
    else:
        with st.spinner(f"⚡ {symbol} analiz ediliyor..."):
            df, ticker = vm.veri_getir(symbol, zaman)

    if df is not None and not df.empty:
        df = ta.indikator_ekle(df, ayar_sozlugu)
        df.fillna(0, inplace=True)

        df = sm.sinyal_uret(df, strateji_secimi)
        sonuc, gecmis, df_final = bm.backtest_yap(
            df, 1000, tp_oran=tp_val, sl_oran=sl_val
        )

        # TREND BİLGİSİ
        if "CP_Trend_Dir" in df.columns:
            last = df.iloc[-1]
            trend_dir = last["CP_Trend_Dir"]
            duration = int(last["CP_Duration"])
            avg_bull = float(last["CP_Avg_Bull"])
            avg_bear = float(last["CP_Avg_Bear"])
            adx_val = last.get("ADX", 0)

            try:
                start_price = df["close"].iloc[-duration]
                curr_price = last["close"]
                trend_pnl = ((curr_price - start_price) / start_price) * 100
            except:
                trend_pnl = 0.0

            strength = (
                "ZAYIF 💤"
                if adx_val < 20
                else ("ORTA ⚠️" if adx_val < 40 else "GÜÇLÜ 🔥")
            )

            if trend_dir == 1:
                kalan = max(0, avg_bull - duration)
                completion = (
                    min(100, (duration / avg_bull) * 100) if avg_bull > 0 else 0
                )
                css = "pred-bull"
                msg = f"""<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;"><div style="text-align:left;"><span style="font-size:1.4em;">📈 YÜKSELİŞ TRENDİ</span><br><span style="color:#fff;opacity:0.8;">Güç: <b>{strength}</b> (ADX: {adx_val:.1f})</span></div><div style="text-align:right;"><span style="font-size:1.4em;">+{trend_pnl:.2f}%</span><br><span style="color:#fff;opacity:0.8;">Trend Getirisi</span></div></div><div style="display:flex;justify-content:space-between;background:rgba(0,0,0,0.2);padding:10px;border-radius:8px;margin-bottom:5px;"><div style="text-align:center;"><span style="font-size:0.8em;color:#ddd;">GEÇEN SÜRE</span><br><span style="font-size:1.1em;font-weight:bold;">{duration} Mum</span></div><div style="text-align:center;"><span style="font-size:0.8em;color:#ddd;">ORT. ÖMÜR</span><br><span style="font-size:1.1em;font-weight:bold;">{avg_bull:.0f} Mum</span></div><div style="text-align:center;"><span style="font-size:0.8em;color:#ddd;">TAHMİNİ KALAN</span><br><span style="font-size:1.1em;font-weight:bold;">~{kalan:.0f} Mum</span></div></div><div style="width:100%;background-color:rgba(255,255,255,0.2);height:6px;border-radius:3px;margin-top:5px;"><div style="width:{completion}%;background-color:#00E676;height:100%;border-radius:3px;"></div></div>"""
            elif trend_dir == -1:
                kalan = max(0, avg_bear - duration)
                completion = (
                    min(100, (duration / avg_bear) * 100) if avg_bear > 0 else 0
                )
                css = "pred-bear"
                msg = f"""<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;"><div style="text-align:left;"><span style="font-size:1.4em;">📉 DÜŞÜŞ TRENDİ</span><br><span style="color:#fff;opacity:0.8;">Güç: <b>{strength}</b> (ADX: {adx_val:.1f})</span></div><div style="text-align:right;"><span style="font-size:1.4em;">{trend_pnl:.2f}%</span><br><span style="color:#fff;opacity:0.8;">Trend Getirisi</span></div></div><div style="display:flex;justify-content:space-between;background:rgba(0,0,0,0.2);padding:10px;border-radius:8px;margin-bottom:5px;"><div style="text-align:center;"><span style="font-size:0.8em;color:#ddd;">GEÇEN SÜRE</span><br><span style="font-size:1.1em;font-weight:bold;">{duration} Mum</span></div><div style="text-align:center;"><span style="font-size:0.8em;color:#ddd;">ORT. ÖMÜR</span><br><span style="font-size:1.1em;font-weight:bold;">{avg_bear:.0f} Mum</span></div><div style="text-align:center;"><span style="font-size:0.8em;color:#ddd;">TAHMİNİ KALAN</span><br><span style="font-size:1.1em;font-weight:bold;">~{kalan:.0f} Mum</span></div></div><div style="width:100%;background-color:rgba(255,255,255,0.2);height:6px;border-radius:3px;margin-top:5px;"><div style="width:{completion}%;background-color:#FF1744;height:100%;border-radius:3px;"></div></div>"""
            else:
                msg = "⚪ PİYASA YATAY"
                css = ""
            st.markdown(
                f'<div class="prediction-box {css}">{msg}</div>', unsafe_allow_html=True
            )

        c1, c2, c3, c4 = st.columns(4)
        if ticker:
            c1.metric(f"{symbol}", f"${float(ticker['last']):,.4f}")
        c2.metric("Kâr", f"%{sonuc['yuzde']}")
        c3.metric("İşlem", f"{sonuc['toplam_islem']}")

        basari_text = f"{sonuc['dogru_islem']} / {sonuc['toplam_islem']}"
        c4.metric("Başarı (D/T)", basari_text, f"%{sonuc['win_rate']}")

        # --- GRAFİK ---
        price_series = []
        price_series.append(
            {
                "type": "Candlestick",
                "data": [
                    {
                        "time": int(r["timestamp"].timestamp()),
                        "open": r["open"],
                        "high": r["high"],
                        "low": r["low"],
                        "close": r["close"],
                    }
                    for i, r in df_final.iterrows()
                ],
                "options": {
                    "upColor": "#26a69a",
                    "downColor": "#ef5350",
                    "borderVisible": False,
                    "wickUpColor": "#26a69a",
                    "wickDownColor": "#ef5350",
                },
                "markers": [],
            }
        )

        # HMA 9 Çizgisi
        if "HMA_9" in df.columns:
            hma_data = [
                {"time": int(r["timestamp"].timestamp()), "value": r["HMA_9"]}
                for i, r in df.iterrows()
                if r["HMA_9"] != 0
            ]
            price_series.append(
                {
                    "type": "Line",
                    "data": hma_data,
                    "options": {
                        "color": "#9C27B0",
                        "lineWidth": 2,
                        "visible": sma_vis,
                        "title": "HMA 9",
                    },
                }
            )

        # Bollinger
        if "BB_Upper" in df.columns:
            bb_up = [
                {"time": int(r["timestamp"].timestamp()), "value": r["BB_Upper"]}
                for i, r in df.iterrows()
                if r["BB_Upper"] != 0
            ]
            bb_low = [
                {"time": int(r["timestamp"].timestamp()), "value": r["BB_Lower"]}
                for i, r in df.iterrows()
                if r["BB_Lower"] != 0
            ]
            price_series.append(
                {
                    "type": "Line",
                    "data": bb_up,
                    "options": {
                        "color": "#9C27B0",
                        "lineWidth": 2,
                        "visible": bb_vis,
                        "title": "",
                    },
                }
            )
            price_series.append(
                {
                    "type": "Line",
                    "data": bb_low,
                    "options": {
                        "color": "#9C27B0",
                        "lineWidth": 2,
                        "visible": bb_vis,
                        "title": "",
                    },
                }
            )

        markers = []
        for islem in gecmis:
            ts = int(islem["Tarih"].timestamp())
            tur = islem["Tür"]
            if "AL (Giriş)" in tur:
                markers.append(
                    {
                        "time": ts,
                        "position": "belowBar",
                        "color": "#00E676",
                        "shape": "arrowUp",
                        "text": "GİR",
                        "size": 2,
                    }
                )
            elif "SAT (Giriş)" in tur:
                markers.append(
                    {
                        "time": ts,
                        "position": "aboveBar",
                        "color": "#FF1744",
                        "shape": "arrowDown",
                        "text": "GİR",
                        "size": 2,
                    }
                )
            elif "TP" in tur:
                markers.append(
                    {
                        "time": ts,
                        "position": "aboveBar" if "Uzun" in tur else "belowBar",
                        "color": "#00E676",
                        "shape": "circle",
                        "text": "",
                        "size": 1,
                    }
                )
            elif "STOP" in tur:
                markers.append(
                    {
                        "time": ts,
                        "position": "belowBar" if "Uzun" in tur else "aboveBar",
                        "color": "#FF1744",
                        "shape": "square",
                        "text": "",
                        "size": 1,
                    }
                )
        price_series[0]["markers"] = markers

        charts = [
            {
                "chart": {
                    "height": 450,
                    "layout": {
                        "textColor": "#d1d4dc",
                        "background": {"type": "solid", "color": "#131722"},
                    },
                    "grid": {
                        "vertLines": {"color": "rgba(0,0,0,0)"},
                        "horzLines": {"color": "rgba(0,0,0,0)"},
                    },
                    "crosshair": {"mode": 1},
                },
                "series": price_series,
            }
        ]

        # Paneller
        if stoch_vis and "Stoch_K" in df.columns:
            stoch_series = [
                {
                    "type": "Line",
                    "data": [
                        {"time": int(r["timestamp"].timestamp()), "value": r["Stoch_K"]}
                        for i, r in df.iterrows()
                    ],
                    "options": {"color": "#2962FF", "lineWidth": 2, "title": "Stoch K"},
                },
                {
                    "type": "Line",
                    "data": [
                        {"time": int(r["timestamp"].timestamp()), "value": r["Stoch_D"]}
                        for i, r in df.iterrows()
                    ],
                    "options": {"color": "#FF6D00", "lineWidth": 2, "title": "Stoch D"},
                },
            ]
            charts.append(
                {
                    "chart": {
                        "height": 150,
                        "layout": {
                            "textColor": "#d1d4dc",
                            "background": {"type": "solid", "color": "#131722"},
                        },
                        "grid": {
                            "vertLines": {"color": "rgba(0,0,0,0)"},
                            "horzLines": {"color": "rgba(0,0,0,0)"},
                        },
                        "crosshair": {"mode": 1},
                    },
                    "series": stoch_series,
                }
            )

        if adx_vis and "ADX" in df.columns:
            adx_series = [
                {
                    "type": "Line",
                    "data": [
                        {"time": int(r["timestamp"].timestamp()), "value": r["ADX"]}
                        for i, r in df.iterrows()
                        if r["ADX"] != 0
                    ],
                    "options": {"color": "#FF9800", "lineWidth": 2, "title": "ADX"},
                }
            ]
            charts.append(
                {
                    "chart": {
                        "height": 150,
                        "layout": {
                            "textColor": "#d1d4dc",
                            "background": {"type": "solid", "color": "#131722"},
                        },
                        "grid": {
                            "vertLines": {"color": "rgba(0,0,0,0)"},
                            "horzLines": {"color": "rgba(0,0,0,0)"},
                        },
                        "crosshair": {"mode": 1},
                    },
                    "series": adx_series,
                }
            )

        renderLightweightCharts(charts, key="main_chart")

        # SQL KAYIT (Otomatik)
        with st.expander("📜 Detaylı İşlem Geçmişi"):
            if gecmis:
                st.dataframe(pd.DataFrame(gecmis))
                for islem in gecmis:
                    islem["Coin"] = symbol
                    islem["Zaman_Dilimi"] = zaman
                    islem["Strateji"] = strateji_secimi
                dbm.loglari_kaydet(gecmis)
                st.success(f"💾 {len(gecmis)} işlem veritabanına kaydedildi.")
            else:
                st.info("Henüz işlem yok.")

        if oto_yenileme:
            time.sleep(60)
            st.rerun()
    else:
        st.error("Veri yok.")

# ==========================================
# MOD 2: TOP 50 GENEL RAPOR (SQL)
# ==========================================
elif calisma_modu == "Top 50 Genel Rapor (Tüm Stratejiler)":
    st.title(f"📊 Günlük Strateji Karnesi ({zaman})")

    if st.button("🚀 GÜNLÜK TARAMAYI BAŞLAT", type="primary"):
        coin_listesi = vm.top_50_coin_getir()
        if not coin_listesi:
            st.error("Coin listesi alınamadı.")
            st.stop()

        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(coin_listesi) * len(STRATEJI_LISTESI)
        counter = 0

        for symbol in coin_listesi:
            df, _ = vm.veri_getir(symbol, zaman)
            if df is not None and not df.empty:
                try:
                    df = ta.indikator_ekle(df, ayar_sozlugu)
                    df.fillna(0, inplace=True)

                    for strateji_adi in STRATEJI_LISTESI:
                        status_text.text(f"Analiz: {symbol} - {strateji_adi}")
                        df_strat = sm.sinyal_uret(df.copy(), strateji_adi)
                        _, gecmis, _ = bm.backtest_yap(
                            df_strat, 1000, tp_oran=tp_val, sl_oran=sl_val
                        )

                        if gecmis:
                            for islem in gecmis:
                                islem["Coin"] = symbol
                                islem["Zaman_Dilimi"] = zaman
                                islem["Strateji"] = strateji_adi
                            dbm.loglari_kaydet(gecmis)
                        counter += 1
                        progress_bar.progress(min(counter / total, 1.0))
                except:
                    pass

        progress_bar.empty()
        status_text.success("✅ Analiz ve SQL Kaydı Tamamlandı!")

        bugun_baslangic = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        df_rapor = dbm.gunluk_ozet_raporu_al(bugun_baslangic)

        if not df_rapor.empty:
            st.subheader(
                f"📋 {datetime.datetime.now().strftime('%d-%m-%Y')} Performans Raporu"
            )
            st.dataframe(df_rapor, use_container_width=True)
        else:
            st.warning("Bugün henüz işlem kaydedilmedi.")

# ==========================================
# MOD 3: ANA SAYFA (DASHBOARD)
# ==========================================
else:
    st.title("💰 Kripto Piyasa Merkezi")
    with st.spinner("Piyasa verileri taranıyor..."):
        v = vm.dort_buyuk_coin_getir()
        if v:
            c1, c2, c3, c4 = st.columns(4)

            def k(col, s, n):
                if s in v:
                    col.metric(
                        n,
                        f"${float(v[s]['last']):,.2f}",
                        f"%{float(v[s]['percentage']):.2f}",
                    )

            k(c1, "BTC/USDT", "Bitcoin")
            k(c2, "ETH/USDT", "Ethereum")
            k(c3, "SOL/USDT", "Solana")
            k(c4, "BNB/USDT", "Binance Coin")

    st.markdown("---")
    yukselenler, dusenler, hacim15 = vm.piyasa_genel_analiz()
    if not yukselenler.empty:
        col_up, col_down = st.columns(2)
        with col_up:
            st.markdown("### 🚀 24s En Çok Yükselenler")
            st.dataframe(yukselenler, hide_index=True, use_container_width=True)
        with col_down:
            st.markdown("### 🩸 24s En Çok Düşenler")
            st.dataframe(dusenler, hide_index=True, use_container_width=True)
        st.markdown("---")
        st.subheader("🔥 Hacim Liderleri")
        st.dataframe(hacim15, use_container_width=True)
    else:
        st.info("Piyasa verileri yükleniyor...")

    time.sleep(5)
    st.rerun()
