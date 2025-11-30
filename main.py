import streamlit as st
import pandas as pd
import time
import datetime
import os
import streamlit.components.v1 as components  # ✅ React'i gömmek için gerekli kütüphane
from streamlit_lightweight_charts import renderLightweightCharts

# --- MODÜLLERİ GÜVENLİ ÇAĞIRMA ---
try:
    from core import veri_motoru as vm
    from core import teknik_analiz as ta
    from core import backtest as bm
    from core import db_manager as dbm  # YENİ: SQL Yöneticisi
    from strategies import strateji as sm
except ImportError as e:
    st.error(f"Modül Hatası: {e}")
    st.info(
        "Lütfen 'core' ve 'strategies' klasörlerinin doğru yerde olduğundan emin olun."
    )
    st.stop()

# --- VERİTABANI BAŞLATMA ---
# Bot her açıldığında veritabanı dosyasını kontrol eder/oluşturur
dbm.veritabanini_hazirla()

# --- CSS VE SAYFA AYARLARI ---
st.set_page_config(page_title="Pro Algo Bot", page_icon="💎", layout="wide")
st.markdown(
    """
    <style>
        /* FONT IMPORT */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');

        /* GENEL SAYFA AYARLARI */
        .stApp { 
            font-family: 'Inter', sans-serif;
        }

        /* --- MODERN DARK MODE ARKA PLANI --- */
        @media (prefers-color-scheme: dark) {
            .stApp {
                background: radial-gradient(circle at 50% -20%, #1c2536 0%, #0e1117 80%);
                background-attachment: fixed;
            }
        }
        
        /* --- SIDEBAR AYARLARI (GÜNCELLENDİ: DAHA AÇIK GRİ) --- */
        [data-testid="stSidebar"] {
            background-color: #1c2128 !important; /* İstediğin açık grimsi ton */
            border-right: 1px solid rgba(255, 255, 255, 0.1);
        }
        [data-testid="stSidebar"] label {
            font-size: 1.1rem !important;
            font-weight: 600 !important;
            color: #e6e6e6 !important;
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
            padding: 15px 10px !important;
            margin-bottom: 5px !important;
            border-radius: 8px;
            border: 1px solid rgba(128,128,128, 0.1);
            transition: background-color 0.2s;
            background-color: #21262d; /* Butonların kendi rengi */
        }
        [data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {
            background-color: #30363d;
        }
        [data-testid="stSidebar"] button {
            font-size: 1.1rem !important;
            padding: 0.75rem 1rem !important;
            font-weight: bold !important;
        }
        [data-testid="stSidebar"] [data-baseweb="select"] {
            font-size: 1.1rem !important;
        }
        
        /* MODERN KART STİLİ */
        .crypto-card {
            background-color: var(--secondary-background-color);
            border: 1px solid rgba(128, 128, 128, 0.1);
            border-radius: 16px;
            padding: 20px 15px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            transition: all 0.3s ease;
            height: 100%;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            backdrop-filter: blur(5px);
        }
        
        .crypto-card:hover {
            transform: translateY(-5px);
            border-color: var(--primary-color);
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
        }

        /* METİN STİLLERİ */
        .crypto-title { 
            color: var(--text-color); 
            opacity: 0.7;
            font-size: 0.85rem; 
            font-weight: 600; 
            margin-bottom: 10px; 
            text-transform: uppercase; 
            letter-spacing: 1.5px;
        }
        
        .crypto-price { 
            color: var(--text-color); 
            font-size: 1.8rem; 
            font-weight: 800; 
            margin: 0; 
        }
        
        /* RENKLER */
        .crypto-value-green { color: #2ea043; font-size: 1.5rem; font-weight: 700; }
        .crypto-value-red { color: #da3633; font-size: 1.5rem; font-weight: 700; }
        
        /* TREND KUTULARI */
        .prediction-box { 
            padding: 20px; 
            border-radius: 16px; 
            margin-bottom: 25px; 
            text-align: center; 
            font-weight: bold; 
            font-size: 1.1em; 
            border: 1px solid; 
            backdrop-filter: blur(5px);
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        
        .pred-bull { 
            background: linear-gradient(145deg, rgba(46, 160, 67, 0.1), rgba(46, 160, 67, 0.05));
            border-color: rgba(46, 160, 67, 0.3); 
            color: #2ea043; 
        }
        
        .pred-bear { 
            background: linear-gradient(145deg, rgba(218, 54, 51, 0.1), rgba(218, 54, 51, 0.05));
            border-color: rgba(218, 54, 51, 0.3); 
            color: #da3633; 
        }

        .sub-text { 
            font-size: 0.8em; 
            opacity: 0.8; 
            margin-top: 5px; 
            font-weight: normal; 
            color: var(--text-color); 
        }
        
        .crypto-change-up { 
            color: #3fb950; 
            font-size: 1.1rem; 
            font-weight: 600; 
            margin-top: 8px;
            background: rgba(63, 185, 80, 0.1);
            padding: 4px 12px;
            border-radius: 20px;
        }
        .crypto-change-down { 
            color: #f85149; 
            font-size: 1.1rem; 
            font-weight: 600; 
            margin-top: 8px;
            background: rgba(248, 81, 73, 0.1);
            padding: 4px 12px;
            border-radius: 20px;
        }

        /* HEADER & BAŞLIKLAR */
        .header-symbol {
            font-size: 2.5rem;
            font-weight: 900;
            background: -webkit-linear-gradient(45deg, var(--text-color), var(--primary-color));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 20px;
            letter-spacing: -1px;
        }
        
        /* CANLI NOKTA (LIVE DOT) */
        .live-dot {
            height: 12px;
            width: 12px;
            background-color: #ff5252;
            border-radius: 50%;
            display: inline-block;
            margin-right: 10px;
            animation: pulse-red 2s infinite; 
        }
        @keyframes pulse-red {
            0% { box-shadow: 0 0 0 0 rgba(255, 82, 82, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(255, 82, 82, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 82, 82, 0); }
        }

        /* --- YENİ BAŞLIK ANİMASYONU (SHINE EFFECT) --- */
        @keyframes shine {
            to {
                background-position: 200% center;
            }
        }
        .modern-header {
            font-size: 3rem;
            font-weight: 900;
            text-align: center;
            /* Sabit Beyaz ve Parlak Mavi Geçişi */
            background: linear-gradient(to right, #ffffff 20%, #58a6ff 40%, #58a6ff 60%, #ffffff 80%);
            background-size: 200% auto;
            color: #ffffff; /* Varsayılan renk beyaz */
            background-clip: text;
            text-fill-color: transparent;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: shine 4s linear infinite;
            margin-bottom: 10px;
            text-shadow: 0 0 20px rgba(88, 166, 255, 0.2);
        }
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

# 1. GLOBAL AYARLAR
oto_yenileme = st.sidebar.toggle("Canlı Veri Akışı", value=True)

# MOD SEÇİMİ
calisma_modu = st.sidebar.radio(
    "Çalışma Modu",
    [
        "Ana Sayfa (Dashboard)",
        "Tek Coin Analizi",
        "Top 50 Genel Rapor (Tüm Stratejiler)",
    ],
)

# ZAMAN SEÇİMİ (Ana Sayfa haricinde göster)
if calisma_modu != "Ana Sayfa (Dashboard)":
    zaman = st.sidebar.selectbox(
        "⏱️ Zaman", ["1m", "3m", "5m", "15m", "1h", "4h"], index=2
    )
else:
    zaman = "15m"

# AYARLAR (Sabit)
ayar_sozlugu = {
    "sma_aktif": True,
    "sma_len": 9,
    "bb_aktif": True,
    "cp_aktif": True,
    "ema_aktif": True,
    "adx_aktif": True,
}

# Strateji Listesi
STRATEJI_LISTESI = [
    "Pure_Supertrend_Strategy",
    "Normalized_MACD_Strategy",
    "EMA_RSI_Strategy",
    "HMA_Simple_Strategy",
    "Pivot_Reversal_Strategy",
    "AI_Trend_Predictor",
    "Ai_Scalp",
]

# BACKTEST AYARLARI
if calisma_modu == "Tek Coin Analizi":
    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Backtest Ayarları")
    user_tp = st.sidebar.number_input("Hedef Kâr (TP) %", 0.1, 20.0, 0.6, 0.1, "%.1f")
    user_sl = st.sidebar.number_input(
        "Zarar Durdur (SL) %", 0.1, 10.0, 1.0, 0.1, "%.1f"
    )
    tp_val = user_tp / 100
    sl_val = user_sl / 100

    strateji_secimi = st.sidebar.selectbox("🧠 Strateji Seç", STRATEJI_LISTESI)
    arama = (
        st.sidebar.text_input("🔍 Coin Ara (Örn: BTC)", key="arama_kodu")
        .upper()
        .strip()
    )
    analiz_baslat = st.sidebar.button("Analiz Et 🚀", use_container_width=True)
else:
    tp_val, sl_val, arama = 0.006, 0.01, None

# ==========================================
# MOD 1: TEK COIN ANALİZİ
# ==========================================
if calisma_modu == "Tek Coin Analizi" and arama:
    symbol = f"{arama}/USDT" if "/" not in arama else arama

    # Sadece ilk açılışta veya strateji değişince veri çek
    df, ticker = vm.veri_getir(symbol, zaman)

    if df is not None and not df.empty:
        df = ta.indikator_ekle(df, ayar_sozlugu)
        df.fillna(0, inplace=True)
        df = sm.sinyal_uret(df, strateji_secimi)
        sonuc, gecmis, df_final = bm.backtest_yap(
            df, 1000, tp_oran=tp_val, sl_oran=sl_val
        )

        # 1. BAŞLIK
        st.markdown(
            f'<div class="header-symbol">{symbol}</div>', unsafe_allow_html=True
        )

        # --- TREND ANALİZİ (DÜZELTİLDİ: HTML FORMATI GARANTİLENDİ) ---
        try:
            if "CP_Trend_Dir" in df.columns:
                last = df.iloc[-1]
                trend_dir = last["CP_Trend_Dir"]
                duration = int(last["CP_Duration"])
                avg_bull = float(last["CP_Avg_Bull"])
                avg_bear = float(last["CP_Avg_Bear"])
                adx_val = last.get("ADX", 0)

                # Trend Getirisi Hesabı
                trend_pnl = 0.0
                if duration > 0 and len(df) > duration:
                    try:
                        start_price = df["close"].iloc[-(duration + 1)]
                        curr_price = last["close"]
                        if start_price > 0:
                            trend_pnl = ((curr_price - start_price) / start_price) * 100
                    except:
                        trend_pnl = 0.0

                strength = (
                    "ZAYIF 💤"
                    if adx_val < 20
                    else ("ORTA ⚠️" if adx_val < 40 else "GÜÇLÜ 🔥")
                )

                # Tamamlanma Oranı
                avg_life = avg_bull if trend_dir == 1 else avg_bear
                if avg_life > 0:
                    completion = min(100, (duration / avg_life) * 100)
                    kalan = max(0, avg_life - duration)
                else:
                    completion = 0
                    kalan = 0

                if trend_dir == 1:
                    css = "pred-bull"
                    title_text = "📈 YÜKSELİŞ TRENDİ"
                    color_hex = "#2ea043"
                elif trend_dir == -1:
                    css = "pred-bear"
                    title_text = "📉 DÜŞÜŞ TRENDİ"
                    color_hex = "#da3633"
                else:
                    title_text = "⚪ PİYASA YATAY"
                    css = ""
                    color_hex = "#8b949e"

                if css:
                    # HTML İçeriğini Temiz Bir Şekilde Oluştur
                    msg = f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                        <div style="text-align:left;">
                            <span style="font-size:1.6em;">{title_text}</span><br>
                            <span style="opacity:0.8; font-size:0.9em;">Güç: <b>{strength}</b> (ADX: {adx_val:.1f})</span>
                        </div>
                        <div style="text-align:right;">
                            <span style="font-size:1.6em; font-weight:bold;">{'+' if trend_pnl>0 else ''}{trend_pnl:.2f}%</span><br>
                            <span style="opacity:0.8; font-size:0.9em;">Trend Getirisi</span>
                        </div>
                    </div>
                    <div style="display:flex; justify-content:space-between; background:rgba(0,0,0,0.05); padding:12px; border-radius:10px; margin-bottom:10px;">
                        <div style="text-align:center;">
                            <span style="font-size:0.85em; opacity:0.7;">GEÇEN SÜRE</span><br>
                            <span style="font-size:1.2em; font-weight:bold;">{duration} Mum</span>
                        </div>
                        <div style="text-align:center;">
                            <span style="font-size:0.85em; opacity:0.7;">ORT. ÖMÜR</span><br>
                            <span style="font-size:1.2em; font-weight:bold;">{avg_life:.0f} Mum</span>
                        </div>
                        <div style="text-align:center;">
                            <span style="font-size:0.85em; opacity:0.7;">TAHMİNİ KALAN</span><br>
                            <span style="font-size:1.2em; font-weight:bold;">~{kalan:.0f} Mum</span>
                        </div>
                    </div>
                    <div style="width:100%; background-color:rgba(128,128,128,0.2); height:8px; border-radius:4px; margin-top:8px;">
                        <div style="width:{completion}%; background-color:{color_hex}; height:100%; border-radius:4px; transition: width 0.5s;"></div>
                    </div>
                    """
                    st.markdown(
                        f'<div class="prediction-box {css}">{msg}</div>',
                        unsafe_allow_html=True,
                    )
        except Exception as e:
            pass

        # 2. PERFORMANS KARTLARI
        with st.container():
            kc1, kc2, kc3, kc4 = st.columns(4)

            kar_val = float(sonuc["yuzde"])
            kar_css = "crypto-value-green" if kar_val >= 0 else "crypto-value-red"
            kar_sign = "+" if kar_val >= 0 else ""
            win_val = float(sonuc["win_rate"])
            win_css = "crypto-value-green" if win_val >= 50 else "crypto-value-red"

            kc1.markdown(
                f"""<div class="crypto-card"><div class="crypto-title">SEÇİLEN COIN</div><div class="crypto-price">{symbol}</div></div>""",
                unsafe_allow_html=True,
            )
            kc2.markdown(
                f"""<div class="crypto-card"><div class="crypto-title">TOPLAM KÂR</div><div class="{kar_css}">{kar_sign}{kar_val}%</div></div>""",
                unsafe_allow_html=True,
            )
            kc3.markdown(
                f"""<div class="crypto-card"><div class="crypto-title">İŞLEM SAYISI</div><div class="crypto-price">{sonuc['toplam_islem']}</div></div>""",
                unsafe_allow_html=True,
            )
            kc4.markdown(
                f"""<div class="crypto-card"><div class="crypto-title">BAŞARI ORANI</div><div style="font-size:1.2em; font-weight:bold; margin-bottom:5px;"><span style="color:#3fb950">{sonuc['dogru_islem']} ✅</span> / <span style="color:#f85149">{sonuc['yanlis_islem']} ❌</span></div><div class="{win_css}" style="font-size:1.1em;">%{win_val}</div></div>""",
                unsafe_allow_html=True,
            )

        # 3. GRAFİK (REACT)
        react_url = f"http://localhost:3000/?symbol={symbol}&zaman={zaman}"
        st.markdown(
            f'<iframe src="{react_url}" width="100%" height="600" style="border:none; margin-top:20px;"></iframe>',
            unsafe_allow_html=True,
        )

        # 4. TABLO
        with st.expander("📜 Detaylı İşlem Geçmişi (Tablo)"):
            if gecmis:
                st.dataframe(pd.DataFrame(gecmis), use_container_width=True)
                for islem in gecmis:
                    islem["Coin"] = symbol
                    islem["Zaman_Dilimi"] = zaman
                    islem["Strateji"] = strateji_secimi
                dbm.loglari_kaydet(gecmis)
            else:
                st.info("Henüz işlem yok.")
    else:
        st.error("Veri yok.")

# ==========================================
# MOD 2: TOP 50 GENEL RAPOR
# ==========================================
elif calisma_modu == "Top 50 Genel Rapor (Tüm Stratejiler)":
    st.title(f"📊 Günlük Strateji Karnesi ({zaman})")

    col1, col2 = st.columns([1, 3])
    if col1.button("🚀 GÜNLÜK TARAMAYI BAŞLAT", type="primary"):
        coin_listesi = vm.top_50_coin_getir()
        if not coin_listesi:
            st.error("Coin listesi alınamadı.")
            st.stop()

        progress_bar = st.progress(0)
        status_text = st.empty()
        total_ops = len(coin_listesi) * len(STRATEJI_LISTESI)
        counter = 0

        for symbol in coin_listesi:
            df, _ = vm.veri_getir(symbol, zaman)
            if df is not None and not df.empty:
                try:
                    df = ta.indikator_ekle(df, ayar_sozlugu)
                    df.fillna(0, inplace=True)
                    for strateji_adi in STRATEJI_LISTESI:
                        status_text.text(f"Analiz ediliyor: {symbol} - {strateji_adi}")
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
                        progress_bar.progress(min(counter / total_ops, 1.0))
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
            st.warning("Bugün henüz hiçbir işlem kaydedilmedi.")

# ==========================================
# MOD 3: ANA SAYFA (DASHBOARD) - ULTRA MODERN & HIZLI ⚡
# ==========================================
else:
    # --- BAŞLIK (DÜZELTİLDİ VE ANİMASYONLU) ---
    st.markdown(
        """
        <div style="text-align: center;">
            <h1 class="modern-header" style="margin-bottom: 5px;">
                💰 Kripto Piyasa Merkezi
            </h1>
            <div style="display: flex; align-items: center; justify-content: center; margin-bottom: 20px;">
                <span class="live-dot"></span>
                <span style="color: var(--text-color); font-weight: 600; opacity: 0.8;">CANLI PİYASA AKIŞI</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # 1. HIZLI BÖLGE: 4 BÜYÜK COIN
    @st.cache_data(ttl=5, show_spinner=False, persist="disk")
    def get_top_coins_cached():
        return vm.dort_buyuk_coin_getir()

    v = get_top_coins_cached()
    if v:
        with st.container():
            cols = st.columns(4)
            coin_labels = [
                "Bitcoin (BTC)",
                "Ethereum (ETH)",
                "Solana (SOL)",
                "Binance Coin (BNB)",
            ]
            coin_keys = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]

            for i, col in enumerate(cols):
                symbol = coin_keys[i]
                if symbol in v:
                    price = float(v[symbol]["last"])
                    change = float(v[symbol]["percentage"])
                    color_class = (
                        "crypto-change-up" if change >= 0 else "crypto-change-down"
                    )
                    sign = "▲ " if change >= 0 else "▼ "

                    col.markdown(
                        f"""
                    <div class="crypto-card">
                        <div class="crypto-title">{coin_labels[i]}</div>
                        <div class="crypto-price">${price:,.2f}</div>
                        <div class="{color_class}">{sign}{change:.2f}%</div>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

    st.markdown("---")

    # 2. YAVAŞ BÖLGE (24s Disk Cache - show_spinner=False ile Hızlı Hissiyat)
    @st.cache_data(ttl=86400, show_spinner=False, persist="disk")
    def get_market_data_24h():
        return vm.piyasa_genel_analiz()

    def color_green(val):
        return "color: #3fb950"

    def color_red(val):
        return "color: #f85149"

    def color_change(val):
        return (
            f'color: {"#3fb950" if val > 0 else "#f85149"}'
            if isinstance(val, (int, float))
            else ""
        )

    try:
        yukselenler, dusenler, hacim15 = get_market_data_24h()
        st.subheader("📊 Piyasa Genel Bakış (Günlük)")

        tab1, tab2, tab3 = st.tabs(
            ["🚀 En Çok Yükselenler", "🩸 En Çok Düşenler", "🔥 Hacim Liderleri"]
        )

        with tab1:
            if not yukselenler.empty:
                st.dataframe(
                    yukselenler.style.format(
                        {
                            "Fiyat": "${:.4f}",
                            "Değişim (%)": "%{:.2f}",
                            "Hacim ($)": "${:,.0f}",
                        }
                    ).map(color_green, subset=["Coin", "Değişim (%)"]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Veri bekleniyor...")

        with tab2:
            if not dusenler.empty:
                st.dataframe(
                    dusenler.style.format(
                        {
                            "Fiyat": "${:.4f}",
                            "Değişim (%)": "%{:.2f}",
                            "Hacim ($)": "${:,.0f}",
                        }
                    ).map(color_red, subset=["Coin", "Değişim (%)"]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Veri bekleniyor...")

        with tab3:
            if not hacim15.empty:
                st.dataframe(
                    hacim15.style.format(
                        {
                            "Fiyat": "${:.4f}",
                            "Değişim (%)": "%{:.2f}",
                            "Hacim ($)": "${:,.0f}",
                        }
                    ).map(color_change, subset=["Değişim (%)"]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Veri bekleniyor...")

    except Exception as e:
        st.error(f"Piyasa verileri: {e}")

    # YENİLEME DÖNGÜSÜ: 5 SANİYE
    if oto_yenileme:
        time.sleep(5)
        st.rerun()
