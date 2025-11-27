# config/settings.py

# --- BOT GENEL AYARLARI ---
APP_NAME = "Pro Algo Bot"
PAGE_ICON = "💎"
LAYOUT = "wide"

# --- VARSAYILAN BACKTEST DEĞERLERİ ---
DEFAULT_TP = 0.6  # Hedef Kâr (%)
DEFAULT_SL = 0.8  # Zarar Durdur (%)
DEFAULT_BALANCE = 1000  # Başlangıç Bakiyesi ($)

# --- ZAMAN DİLİMLERİ ---
TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h", "4h"]
DEFAULT_TIMEFRAME_INDEX = 2  # "5m" varsayılan olsun (Listede 3. sırada)

# --- COIN LİSTESİ ---
# Buraya sık kullandığın coinleri ekleyebilirsin (İleride selectbox için)
FAVORITE_COINS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "AVAX/USDT",
    "XRP/USDT",
]

# --- STRATEJİ LİSTESİ ---
STRATEGIES = [
    "Pure_Supertrend_Strategy",
    "Normalized_MACD_Strategy",
    "EMA_RSI_Strategy",
    "Simple_SMA_Strategy",
    "Supertrend_MACD_Strategy",
    "Pivot_Reversal_Strategy",
    "AI_Trend_Strategy",
]

# --- GÖRÜNÜRLÜK AYARLARI (Varsayılan) ---
DEFAULT_VISIBILITY = {
    "sma": True,
    "bollinger": True,
    "stoch": True,
    "macd": False,
    "adx": False,
}

# --- İNDİKATÖR PARAMETRELERİ ---
INDICATOR_SETTINGS = {
    "sma_len": 9,
    "ema_len_fast": 8,
    "ema_len_mid": 20,
    "ema_len_slow": 50,
    "rsi_len": 14,
    "bb_len": 20,
    "bb_std": 2.0,
    "st_len": 10,
    "st_mul": 3.0,
    "cp_len": 50,
}
