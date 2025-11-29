import pandas as pd

# --- HATA ÇÖZÜMÜ: GÜVENLİ İMPORT ---
# main.py ana dizinden çalıştığı için, alt modülleri "strategies.modul_adi" olarak çağırıyoruz.
try:
    from strategies import st_pure_supertrend
    from strategies import st_ema_rsi
    from strategies import st_norm_macd
    from strategies import st_HMA_simple
    from strategies import st_ai_scalp
    from strategies import st_pivot_rev
    from strategies import st_ai_trend
    from strategies import st_bollinger
    from strategies import st_hyper_scalp
except ImportError:
    # Eğer dosya kendi içinden test ediliyorsa direkt import et
    import st_pure_supertrend
    import st_ema_rsi
    import st_norm_macd
    import st_HMA_simple
    import st_ai_scalp
    import st_pivot_rev
    import st_ai_trend
    import st_bollinger
    import st_hyper_scalp


def sinyal_uret(df, strateji_tipi):
    """
    YÖNETİCİ FONKSİYON:
    Seçilen strateji tipine göre ilgili dosyadaki 'calistir' fonksiyonunu çağırır.
    """
    df["Signal"] = 0  # Sinyal sütununu sıfırla

    if strateji_tipi == "Pure_Supertrend_Strategy":
        return st_pure_supertrend.calistir(df)

    elif strateji_tipi == "EMA_RSI_Strategy":
        return st_ema_rsi.calistir(df)

    elif strateji_tipi == "Normalized_MACD_Strategy":
        return st_norm_macd.calistir(df)

    elif strateji_tipi == "HMA_Simple_Strategy":  # Menüdeki isim HMA ise buraya eşle
        return st_HMA_simple.calistir(df)
    # Eski isimle de gelebilir diye güvenlik:
    elif strateji_tipi == "HMA_simple_Strategy":
        return st_HMA_simple.calistir(df)

    elif strateji_tipi == "Ai_Scalp":
        return st_ai_scalp.calistir(df)

    elif strateji_tipi == "Pivot_Reversal_Strategy":
        return st_pivot_rev.calistir(df)

    elif strateji_tipi == "AI_Trend_Predictor":
        return st_ai_trend.calistir(df)

    elif strateji_tipi == "Bollinger_Reversal_Strategy":  # YENİ EKLENDİ
        return st_bollinger.calistir(df)

    elif strateji_tipi == "Hyper_Scalp_Strategy":  # YENİ
        return st_hyper_scalp.calistir(df)

    return df
