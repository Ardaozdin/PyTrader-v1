import sqlite3
import pandas as pd
import os
import streamlit as st

# --- AYARLAR ---
DB_PATH = "data/trade_history.db"

# ==========================================
#      VERİTABANI YÖNETİMİ FONKSİYONLARI
# ==========================================


def veritabanini_hazirla():
    """
    Bot ilk açıldığında çalışır. Klasör yoksa oluşturur, tablo yoksa yaratır.
    """
    klasor_yolu = os.path.dirname(DB_PATH)
    if klasor_yolu and not os.path.exists(klasor_yolu):
        try:
            os.makedirs(klasor_yolu)
        except OSError:
            pass

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Tabloyu oluştur (Eğer yoksa)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_logs (
            Tarih TEXT, 
            Coin TEXT, 
            Strateji TEXT, 
            Zaman_Dilimi TEXT,
            Tur TEXT, 
            Fiyat REAL, 
            Kar_Zarar REAL, 
            Bakiye REAL
        )
        """
    )
    conn.commit()
    conn.close()


def loglari_kaydet(islem_gecmisi):
    """
    İşlem listesini alır, sütun isimlerini SQL formatına çevirir ve kaydeder.
    """
    # Yeni kayıt yapıldığında cache'i temizle ki raporlar güncel olsun
    st.cache_data.clear()

    if not islem_gecmisi:
        return

    df = pd.DataFrame(islem_gecmisi)

    # Türkçe sütun isimlerini İngilizce/SQL uyumlu hale getir
    rename_map = {"Tür": "Tur", "Kâr/Zarar": "Kar_Zarar"}
    df.rename(columns=rename_map, inplace=True)

    # Tarih formatını string'e çevir (SQLite datetime desteklemez)
    if "Tarih" in df.columns:
        df["Tarih"] = df["Tarih"].apply(
            lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if not isinstance(x, str) else x
        )

    # Klasör kontrolü (Silinmişse tekrar oluştur)
    klasor_yolu = os.path.dirname(DB_PATH)
    if klasor_yolu and not os.path.exists(klasor_yolu):
        os.makedirs(klasor_yolu)

    conn = sqlite3.connect(DB_PATH)
    try:
        # Sadece veritabanında tanımlı sütunları seçip gönder (Hata önleyici)
        target_cols = [
            "Tarih",
            "Coin",
            "Strateji",
            "Zaman_Dilimi",
            "Tur",
            "Fiyat",
            "Kar_Zarar",
            "Bakiye",
        ]
        # Sadece kesişen sütunları al
        df_to_save = df[df.columns.intersection(target_cols)]

        # Veriyi ekle (append modu)
        df_to_save.to_sql("trade_logs", conn, if_exists="append", index=False)

    except Exception as e:
        print(f"Veritabanı Kayıt Hatası: {e}")
    finally:
        conn.close()


# ttl=60 -> Raporu çektikten sonra 60 saniye boyunca hafızada tutar.
# Her saniye veritabanını yormaz, sayfa geçişleri hızlı olur.
@st.cache_data(ttl=60)
def gunluk_ozet_raporu_al(baslangic_tarihi):
    """
    Belirli bir tarihten sonraki işlemleri çeker ve özet rapor oluşturur.
    """
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)

    # SQL ile özet tabloyu oluştur (Python yerine SQL'e yük bindiriyoruz - Daha Hızlı)
    query = f"""
    SELECT 
        Coin, 
        Strateji, 
        Zaman_Dilimi, 
        COUNT(*) AS Toplam,
        SUM(CASE WHEN Kar_Zarar > 0 THEN 1 ELSE 0 END) AS Dogru,
        SUM(CASE WHEN Kar_Zarar <= 0 THEN 1 ELSE 0 END) AS Yanlis,
        SUM(Kar_Zarar) AS Net_Kar
    FROM trade_logs 
    WHERE Tarih >= '{baslangic_tarihi}'
    GROUP BY Coin, Strateji, Zaman_Dilimi 
    HAVING Toplam > 0
    ORDER BY Net_Kar DESC;
    """

    try:
        df_rapor = pd.read_sql_query(query, conn)
    except:
        conn.close()
        return pd.DataFrame()

    conn.close()

    if not df_rapor.empty:
        # Yüzdelik hesaplamalar
        df_rapor["Başarı (%)"] = round(
            (df_rapor["Dogru"] / df_rapor["Toplam"]) * 100, 1
        )
        df_rapor["Net Kâr (%)"] = round(df_rapor["Net_Kar"] * 100, 2)

        # Sütun sırasını düzenle
        sutunlar = [
            "Coin",
            "Strateji",
            "Zaman_Dilimi",
            "Toplam",
            "Başarı (%)",
            "Doğru",
            "Yanlis",
            "Net Kâr (%)",
        ]
        # DataFrame içinde bu sütunlar varsa seçip döndür
        return df_rapor[[c for c in sutunlar if c in df_rapor.columns]]

    return pd.DataFrame()
