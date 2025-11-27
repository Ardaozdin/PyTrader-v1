import sqlite3
import pandas as pd
import datetime
import os

# --- 2. VERİTABANI DOSYASININ YERİ ---
DB_PATH = "data/trade_history.db"


# --- 3. VERİTABANINI KURMA FONKSİYONU ---
def veritabanini_hazirla():
    """
    Bot ilk açıldığında çalışır. Klasör ve tabloyu oluşturur.
    """
    klasor_yolu = os.path.dirname(DB_PATH)
    if klasor_yolu and not os.path.exists(klasor_yolu):
        try:
            os.makedirs(klasor_yolu)
        except OSError:
            pass

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Tabloyu oluştur
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


# --- 4. İŞLEM KAYDETME FONKSİYONU ---
def loglari_kaydet(islem_gecmisi):
    """
    İşlem listesini alır, sütun isimlerini düzeltir ve SQLite'a kaydeder.
    """
    if not islem_gecmisi:
        return

    df = pd.DataFrame(islem_gecmisi)

    # Sütun İsimlerini Eşle (Türkçe -> İngilizce/SQL)
    rename_map = {"Tür": "Tur", "Kâr/Zarar": "Kar_Zarar"}
    df.rename(columns=rename_map, inplace=True)

    # Tarih formatını düzelt
    if "Tarih" in df.columns:
        df["Tarih"] = df["Tarih"].apply(
            lambda x: x.strftime("%Y-%m-%d %H:%M:%S") if not isinstance(x, str) else x
        )

    klasor_yolu = os.path.dirname(DB_PATH)
    if klasor_yolu and not os.path.exists(klasor_yolu):
        os.makedirs(klasor_yolu)

    conn = sqlite3.connect(DB_PATH)

    try:
        # Sadece veritabanında tanımlı olan sütunları seçip gönder
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
        df_to_save = df[df.columns.intersection(target_cols)]

        df_to_save.to_sql("trade_logs", conn, if_exists="append", index=False)

    except Exception as e:
        print(f"Kayıt Hatası: {e}")
    finally:
        conn.close()


# --- 5. RAPOR ÇEKME FONKSİYONU ---
def gunluk_ozet_raporu_al(baslangic_tarihi):
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()

    conn = sqlite3.connect(DB_PATH)

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
        df_rapor["Başarı (%)"] = round(
            (df_rapor["Dogru"] / df_rapor["Toplam"]) * 100, 1
        )
        df_rapor["Net Kâr (%)"] = round(df_rapor["Net_Kar"] * 100, 2)

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
        mevcut = [c for c in sutunlar if c in df_rapor.columns]
        return df_rapor[mevcut]

    return pd.DataFrame()
