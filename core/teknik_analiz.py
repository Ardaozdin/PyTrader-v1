import pandas_ta as ta
import numpy as np
import pandas as pd

def indikator_ekle(df, ayarlar):
    """
    TÜM İNDİKATÖRLER:
    HMA 9 (YENİ), SMA 9, EMA, Supertrend, RSI, MACD, StochRSI, ChartPrime, KAMA, Bollinger, Pivotlar, ADX
    """
    
    # --- 1. SMA 9 (Eski Referans) ---
    sma_len = ayarlar.get('sma_len', 9)
    df[f'SMA_{sma_len}'] = ta.sma(df['close'], length=sma_len)

   # --- 2. HMA 14 (GÜNCELLENDİ) ---
    # Kullanıcı isteği üzerine 9'dan 14'e çıkarıldı.
    hma_len = ayarlar.get('hma_len', 14)
    df[f'HMA_{hma_len}'] = ta.hma(df['close'], length=hma_len)

    # --- 3. EMA HESAPLAMALARI ---
    df['EMA_8']  = ta.ema(df['close'], length=8)
    df['EMA_20'] = ta.ema(df['close'], length=20)
    df['EMA_21'] = ta.ema(df['close'], length=21)
    df['EMA_50'] = ta.ema(df['close'], length=50)

    # --- 4. SUPERTREND ---
    st_len = 10; st_mul = 3.0
    supertrend = ta.supertrend(df['high'], df['low'], df['close'], length=st_len, multiplier=st_mul)
    if supertrend is not None:
        df['ST_Line'] = supertrend[f'SUPERT_{st_len}_{st_mul}']
        df['ST_Direction'] = supertrend[f'SUPERTd_{st_len}_{st_mul}']

    # --- 5. RSI ---
    df['RSI'] = ta.rsi(df['close'], length=14)

    # --- 6. MACD & NORMALIZED MACD ---
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df['MACD_Line'] = macd.iloc[:, 0]
        df['MACD_Hist'] = macd.iloc[:, 1]
        df['MACD_Signal'] = macd.iloc[:, 2]
        
        norm_len = 50
        roll_min = df['MACD_Line'].rolling(norm_len).min()
        roll_max = df['MACD_Line'].rolling(norm_len).max()
        denom = (roll_max - roll_min).replace(0, 0.000001)
        df['Norm_MACD'] = ((df['MACD_Line'] - roll_min) / denom * 100) - 50
        df['Norm_Signal'] = ((df['MACD_Signal'] - roll_min) / denom * 100) - 50

    # --- 7. STOCH RSI ---
    stochrsi = ta.stochrsi(df['close'], length=14, rsi_length=14, k=3, d=3)
    if stochrsi is not None:
        df['Stoch_K'] = stochrsi.iloc[:, 0]
        df['Stoch_D'] = stochrsi.iloc[:, 1]

    # --- 8. CHARTPRIME ---
    if ayarlar.get('cp_aktif', True):
        length = 50; trend_len = 3
        df['CP_HMA'] = ta.hma(df['close'], length=length)
        
        trend_series = [0]*len(df); duration_col = [0]*len(df)
        avg_bull_col = [0.0]*len(df); avg_bear_col = [0.0]*len(df)
        bull_runs = []; bear_runs = []
        current_trend = 0; current_duration = 0
        hma_diff = df['CP_HMA'].diff()
        for i in range(trend_len, len(df)):
            is_rising = all(hma_diff.iloc[i-k] > 0 for k in range(trend_len))
            is_falling = all(hma_diff.iloc[i-k] < 0 for k in range(trend_len))
            if is_rising: current_trend = 1
            elif is_falling: current_trend = -1
            trend_series[i] = current_trend
            if current_trend != 0:
                if i>0 and trend_series[i] == trend_series[i-1]: current_duration += 1
                else:
                    if trend_series[i-1] == 1: bull_runs.append(current_duration)
                    elif trend_series[i-1] == -1: bear_runs.append(current_duration)
                    current_duration = 1
            duration_col[i] = current_duration
            avg_bull_col[i] = np.mean(bull_runs[-10:]) if bull_runs else 15.0
            avg_bear_col[i] = np.mean(bear_runs[-10:]) if bear_runs else 15.0
        
        df['CP_Trend_Dir'] = trend_series
        df['CP_Duration'] = duration_col
        df['CP_Avg_Bull'] = avg_bull_col
        df['CP_Avg_Bear'] = avg_bear_col

    # --- 9. KAMA ---
    df['KAMA'] = ta.kama(df['close'], length=10)

    # --- 10. ADX ---
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None: df['ADX'] = adx.iloc[:, 0]
    else: df['ADX'] = 0

    # --- 11. PIVOTLAR ---
    df['Local_Low_5'] = df['low'].rolling(window=5).min()
    df['Local_High_5'] = df['high'].rolling(window=5).max()

    # --- 12. BOLLINGER & WAVETREND ---
    if ayarlar.get('bb_aktif'):
        bb = ta.bbands(df['close'], length=20, std=2.0)
        if bb is not None:
            df['BB_Lower'] = bb.iloc[:, 0]; df['BB_Upper'] = bb.iloc[:, 2]; df['BB_Mid'] = bb.iloc[:, 1]

    hlc3 = (df['high'] + df['low'] + df['close']) / 3
    esa = ta.ema(hlc3, length=10)
    d = ta.ema((hlc3 - esa).abs(), length=10).replace(0, 0.000001)
    ci = (hlc3 - esa) / (0.015 * d)
    df['WT1'] = ta.ema(ci, length=21)
    df['WT2'] = ta.sma(df['WT1'], length=4)

    return df