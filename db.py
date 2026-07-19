#!/usr/bin/env python3
"""
db.py — İşlem kaydı (SQLite + CSV)

Her işlem açılış/kapanış ve her kritik olay kalıcı olarak yazılır.
Amaç: hiçbir kayıp bir daha "açıklanamaz" olmasın; backtest kalibrasyonu
ve analiz (WR/PF/beklenti) için gerçek fill verisi birikir.

Tüm fonksiyonlar try/except ile sarılıdır — kayıt hatası ASLA işlemi bloklamaz.
"""

import csv
import os
import sqlite3
from datetime import datetime, timezone, timedelta

import config

_TZ_TR = timezone(timedelta(hours=3))


def _now():
    return datetime.now(_TZ_TR).strftime("%Y-%m-%d %H:%M:%S")


def _conn():
    return sqlite3.connect(config.TRADE_DB, timeout=10)


def init():
    """Tabloları oluştur (idempotent)."""
    try:
        con = _conn()
        cur = con.cursor()
        cur.execute(
            """CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket INTEGER,
                symbol TEXT,
                yon TEXT,
                entry_type TEXT,
                giris REAL,
                sl REAL,
                tp REAL,
                lot REAL,
                riske REAL,
                risk_pct REAL,
                worst_case REAL,
                acilis_ts TEXT,
                cikis_ts TEXT,
                cikis_fiyat REAL,
                sonuc TEXT,
                pnl REAL,
                slippage_R REAL,
                partial_done INTEGER DEFAULT 0,
                breakeven INTEGER DEFAULT 0,
                bakiye_acilis REAL,
                bakiye_kapanis REAL,
                durum TEXT DEFAULT 'OPEN'
            )"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, tur TEXT, mesaj TEXT
            )"""
        )
        con.commit()
        con.close()
    except Exception as e:
        print(f"WARN db.init: {e}", flush=True)


def log_open(ot: dict):
    """İşlem açılışını kaydet (durum=OPEN)."""
    try:
        con = _conn()
        con.execute(
            """INSERT INTO trades
               (ticket, symbol, yon, entry_type, giris, sl, tp, lot, riske,
                risk_pct, worst_case, acilis_ts, bakiye_acilis, durum)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'OPEN')""",
            (
                ot.get("ticket"), ot.get("symbol"), ot.get("yon"),
                ot.get("entry_type"), ot.get("giris"), ot.get("sl"),
                ot.get("tp"), ot.get("lot"), ot.get("riske"),
                ot.get("risk_pct"), ot.get("worst_case"),
                ot.get("acilis_ts") or _now(), ot.get("balance_at_open"),
            ),
        )
        con.commit()
        con.close()
    except Exception as e:
        print(f"WARN db.log_open: {e}", flush=True)


def log_partial(ticket: int):
    try:
        con = _conn()
        con.execute(
            "UPDATE trades SET partial_done=1, breakeven=1 WHERE ticket=? AND durum='OPEN'",
            (ticket,),
        )
        con.commit()
        con.close()
    except Exception as e:
        print(f"WARN db.log_partial: {e}", flush=True)


def log_close(ticket: int, sonuc: str, pnl: float, cikis_fiyat=None,
              slippage_R=None, bakiye_kapanis=None):
    """İşlem kapanışını kaydet + CSV'ye ekle."""
    try:
        con = _conn()
        con.execute(
            """UPDATE trades SET durum='CLOSED', sonuc=?, pnl=?, cikis_ts=?,
               cikis_fiyat=?, slippage_R=?, bakiye_kapanis=?
               WHERE ticket=? AND durum='OPEN'""",
            (sonuc, pnl, _now(), cikis_fiyat, slippage_R, bakiye_kapanis, ticket),
        )
        con.commit()
        # CSV export (kapanan satır)
        row = con.execute(
            "SELECT symbol,yon,entry_type,giris,sl,tp,lot,riske,acilis_ts,"
            "cikis_ts,cikis_fiyat,sonuc,pnl,slippage_R FROM trades WHERE ticket=?",
            (ticket,),
        ).fetchone()
        con.close()
        if row:
            _append_csv(row)
    except Exception as e:
        print(f"WARN db.log_close: {e}", flush=True)


def _append_csv(row):
    try:
        header = [
            "symbol", "yon", "entry_type", "giris", "sl", "tp", "lot", "riske",
            "acilis_ts", "cikis_ts", "cikis_fiyat", "sonuc", "pnl", "slippage_R",
        ]
        yeni = not os.path.exists(config.TRADE_CSV)
        with open(config.TRADE_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if yeni:
                w.writerow(header)
            w.writerow(row)
    except Exception as e:
        print(f"WARN db._append_csv: {e}", flush=True)


def log_event(tur: str, mesaj: str):
    try:
        con = _conn()
        con.execute(
            "INSERT INTO events (ts, tur, mesaj) VALUES (?,?,?)",
            (_now(), tur, mesaj),
        )
        con.commit()
        con.close()
    except Exception as e:
        print(f"WARN db.log_event: {e}", flush=True)
