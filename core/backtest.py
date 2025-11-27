import pandas as pd
import numpy as np

def backtest_yap(df, baslangic_bakiyesi=1000, tp_oran=0.008, sl_oran=0.004):
    """
    TP/SL seviyelerini kaydeder ve Detaylı İstatistik (Long/Short) tutar.
    """
    bakiye = baslangic_bakiyesi
    pozisyon = 0 
    giris_fiyati = 0
    islem_gecmisi = []
    
    # Grafik için sütunlar
    df['Trade_TP'] = np.nan
    df['Trade_SL'] = np.nan
    
    # --- DETAYLI SAYAÇLAR ---
    win_count = 0
    loss_count = 0
    
    long_total = 0
    long_win = 0
    short_total = 0
    short_win = 0
    
    current_tp = 0
    current_sl = 0

    for i in range(len(df)):
        row = df.iloc[i]
        signal = row['Signal']
        price = row['close']
        high = row['high']
        low = row['low']
        ts = row['timestamp']
        
        rsi_val = row.get('RSI', 0)
        adx_val = row.get('ADX', 0)

        # 1. AÇIK İŞLEMİ KONTROL ET
        if pozisyon != 0:
            # Çizgileri kaydet
            df.at[i, 'Trade_TP'] = current_tp
            df.at[i, 'Trade_SL'] = current_sl

            if pozisyon == 1: # LONG
                if low <= current_sl: # STOP
                    pozisyon = 0; bakiye *= (1 - sl_oran); loss_count += 1
                    long_total += 1 # Kayıp
                    islem_gecmisi.append({'Tarih': ts, 'Tür': 'STOP (Uzun)', 'Fiyat': current_sl, 'Kâr/Zarar': -sl_oran*100, 'Bakiye': round(bakiye, 2), 'RSI': round(rsi_val, 1), 'ADX': round(adx_val, 1)})
                elif high >= current_tp: # KAR
                    pozisyon = 0; bakiye *= (1 + tp_oran); win_count += 1
                    long_total += 1
                    long_win += 1   # Kazanç
                    islem_gecmisi.append({'Tarih': ts, 'Tür': 'TP (Uzun)', 'Fiyat': current_tp, 'Kâr/Zarar': tp_oran*100, 'Bakiye': round(bakiye, 2), 'RSI': round(rsi_val, 1), 'ADX': round(adx_val, 1)})

            elif pozisyon == -1: # SHORT
                if high >= current_sl: # STOP
                    pozisyon = 0; bakiye *= (1 - sl_oran); loss_count += 1
                    short_total += 1 # Kayıp
                    islem_gecmisi.append({'Tarih': ts, 'Tür': 'STOP (Kısa)', 'Fiyat': current_sl, 'Kâr/Zarar': -sl_oran*100, 'Bakiye': round(bakiye, 2), 'RSI': round(rsi_val, 1), 'ADX': round(adx_val, 1)})
                elif low <= current_tp: # KAR
                    pozisyon = 0; bakiye *= (1 + tp_oran); win_count += 1
                    short_total += 1
                    short_win += 1   # Kazanç
                    islem_gecmisi.append({'Tarih': ts, 'Tür': 'TP (Kısa)', 'Fiyat': current_tp, 'Kâr/Zarar': tp_oran*100, 'Bakiye': round(bakiye, 2), 'RSI': round(rsi_val, 1), 'ADX': round(adx_val, 1)})

        # 2. YENİ İŞLEM AÇ
        if pozisyon == 0:
            if signal == 1: # LONG GİRİŞ
                pozisyon = 1
                giris_fiyati = price
                current_sl = giris_fiyati * (1 - sl_oran)
                current_tp = giris_fiyati * (1 + tp_oran)
                islem_gecmisi.append({'Tarih': ts, 'Tür': 'AL (Giriş)', 'Fiyat': price, 'Kâr/Zarar': 0, 'Bakiye': round(bakiye, 2), 'RSI': round(rsi_val, 1), 'ADX': round(adx_val, 1)})
            
            elif signal == -1: # SHORT GİRİŞ
                pozisyon = -1
                giris_fiyati = price
                current_sl = giris_fiyati * (1 + sl_oran)
                current_tp = giris_fiyati * (1 - tp_oran)
                islem_gecmisi.append({'Tarih': ts, 'Tür': 'SAT (Giriş)', 'Fiyat': price, 'Kâr/Zarar': 0, 'Bakiye': round(bakiye, 2), 'RSI': round(rsi_val, 1), 'ADX': round(adx_val, 1)})

    # İstatistikler
    toplam_biten = win_count + loss_count
    win_rate = round((win_count / toplam_biten * 100), 2) if toplam_biten > 0 else 0
    
    # Long/Short Oranları (Sıfıra bölünme hatasını önleyerek)
    long_wr = round((long_win / long_total * 100), 1) if long_total > 0 else 0
    short_wr = round((short_win / short_total * 100), 1) if short_total > 0 else 0
    
    sonuc = {
        'yuzde': round(((bakiye - baslangic_bakiyesi) / baslangic_bakiyesi) * 100, 2),
        'toplam_islem': toplam_biten,
        'dogru_islem': win_count,
        'yanlis_islem': loss_count,
        'win_rate': win_rate,
        
        # Detaylı Veriler (Artık 0 dönmeyecek)
        'long_total': long_total,
        'long_win': long_win,
        'long_wr': long_wr,
        'short_total': short_total,
        'short_win': short_win,
        'short_wr': short_wr
    }
    
    return sonuc, islem_gecmisi, df