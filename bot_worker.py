#!/usr/bin/env python3

"""
bot_worker.py — SOFiNARD SMT Divergence BOT v2
MT5 üzerinden gerçek/demo hesapta işlem açar.

Çalıştırmak için:
  python bot_worker.py

VPS için arka planda:
  nohup python bot_worker.py > bot.log 2>&1 &
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

# --- Encoding fix (madde 1): Windows cp1252 konsolda Türkçe/emoji/kutu
#     karakterleri UnicodeEncodeError verip ana döngüyü çökertiyordu.
#     stdout/stderr'i UTF-8'e zorla; desteklemeyen karakterleri değiştir. ---
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

TZ_TR = timezone(timedelta(hours=3))

# Broker sunucu saatinin UTC offset'i. Başlangıçta MT5'ten tespit edilir.
# Session/haftasonu kontrolü bununla yapılır → backtest (mum saati) ile BİREBİR parite.
_BROKER_OFFSET_H = 3


def _now_tr():
    return datetime.now(TZ_TR)


def _broker_now():
    """Broker sunucu saatiyle şu an — backtest'in mum zaman damgasıyla AYNI kaynak.
    Session 09:00–20:00 böylece canlı ve backtest'te birebir aynı pencereye denk gelir."""
    return (datetime.now(timezone.utc) + timedelta(hours=_BROKER_OFFSET_H)).replace(tzinfo=None)


try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ── strategy.py'den strateji bileşenleri ──
from strategy import (
    PROP_FIRM,
    SMT_PAIRS,
    CORR_GROUPS,
    SESSION_START,
    SESSION_END,
    SPREAD_TABLE,
    FIXED_RISK,
    SETUP_MAX_WAIT,
    _in_session,
    _atr,
    _htf_trend,
    _find_sweep,
    _smt_divergence,
    _entry_signal,
    _calc_sl,
    _calc_tp,
)

import config
import db
import notifier

# ══════════════════════════════════════════════
# BOT AYARLARI
# ══════════════════════════════════════════════

# İşlem açılacak semboller (EURUSD sadece SMT çifti, işlem açılmaz)
TRADE_SYMBOLS = [
    "US500",
    "US100",
    "US30",
    "GBPUSD",
    "GBPJPY",
    "EURJPY",
    "UK100",
    "XAUUSD",
    "USDJPY",
    "GER40",
]

BOT_PROP_FIRM = PROP_FIRM

MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

STATE_FILE = "bot_state.json"
LOG_FILE = "bot.log"
SCAN_INTERVAL = 60  # saniye — 5M mum kapanışını bekle

MAX_DAILY_LOSS_PCT = config.DAILY_LOSS_PCT  # günlük kayıp limiti (config)
MAX_OPEN = config.MAX_OPEN  # aynı anda max pozisyon (config)

# ══════════════════════════════════════════════
# DURUM
# ══════════════════════════════════════════════

_STATE_DEFAULTS: Dict = {
    "balance": 10_000.0,
    "starting_balance": 0.0,  # 0 = başlangıçta gerçek bakiyeden anchor edilecek
    "pf_peak": 10_000.0,
    "pf_floor": 9_400.0,
    "day_sl_count": 0,
    "day_sl_total": 0.0,
    "day_tp_count": 0,
    "day_date": "",
    "day_start_balance": 10_000.0,
    "dyn_risk": config.RISK_PCT,
    "consec_tp": 0,
    "payout_count": 0,
    "total_payouts": 0.0,
    "blown": False,
}

state: Dict = dict(_STATE_DEFAULTS)

# Açık pozisyonlar: symbol → {ticket, symbol, yon, giris, sl, tp, riske, lot, ...}
open_trades: Dict[str, Dict] = {}

# Aktif setup'lar: sweep+SMT tespit edildi, giriş bekleniyor
# symbol → {trend, bars_waited, sweep_idx}
active_setups: Dict[str, Dict] = {}

# SL vurulduktan sonra o gün işlem açılmayacak semboller (backtest ile aynı mantık)
day_traded_syms: set = set()
_day_traded_date: str = ""

_mt5_ok = False

# ══════════════════════════════════════════════
# LOG
# ══════════════════════════════════════════════


def _log(msg: str):
    ts = _now_tr().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(f"\n{line}", flush=True)  # \n: durum satırının üzerine yazılmasını önler
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


_HEARTBEAT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "bot_heartbeat.txt"
)


def _touch_heartbeat():
    """Watchdog için canlılık damgası (madde 37). Döngü donarsa dosya eskir."""
    try:
        with open(_HEARTBEAT_FILE, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except Exception:
        pass


_alarm_gecmis: Dict[str, float] = {}


def _alarm_kisitli(anahtar: str, mesaj: str, saniye: int = 1800):
    """Aynı türden alarmı en fazla 'saniye'de bir gönder (Telegram spam'ini önler).
    Ana döngü hatası / MT5 kopması gibi tekrar eden durumlar için."""
    now = time.time()
    if now - _alarm_gecmis.get(anahtar, 0) >= saniye:
        _alarm_gecmis[anahtar] = now
        try:
            notifier.alarm(mesaj)
        except Exception:
            pass


def _rotate_log():
    """Log dosyası MAX_LOG_MB'yi aşarsa .1 olarak arşivle (madde 26)."""
    try:
        if os.path.exists(LOG_FILE) and \
                os.path.getsize(LOG_FILE) > config.MAX_LOG_MB * 1024 * 1024:
            bak = LOG_FILE + ".1"
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(LOG_FILE, bak)
    except Exception:
        pass


# ══════════════════════════════════════════════
# STATE KAYIT / YÜKLEME
# ══════════════════════════════════════════════


def _save_state():
    try:
        data = {
            "state": state,
            "open_trades": open_trades,
            "day_traded_syms": sorted(day_traded_syms),
            "day_traded_date": _day_traded_date,
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        _log(f"WARN state kaydetme: {e}")


def _load_state():
    global state, open_trades, day_traded_syms, _day_traded_date
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Önce default değerleri yükle, sonra dosyadan üzerine yaz — eksik key olmaz
        loaded = dict(_STATE_DEFAULTS)
        loaded.update(data.get("state", {}))
        state.update(loaded)
        open_trades = data.get("open_trades", {})
        # SL engel listesini geri yükle — ama sadece AYNI GÜNSE.
        # Yeni gün başladıysa restart sonrası liste boş başlamalı (backtest mantığı).
        saved_date = data.get("day_traded_date", "")
        if saved_date and saved_date == _now_tr().strftime("%Y-%m-%d"):
            day_traded_syms = set(data.get("day_traded_syms", []))
            _day_traded_date = saved_date
            if day_traded_syms:
                _log(f"Bugun engelli semboller geri yuklendi: {day_traded_syms}")
        _log(
            f"State yuklendi: bakiye=${state['balance']:.2f} | "
            f"acik islem: {len(open_trades)}"
        )
    except FileNotFoundError:
        _log("State dosyasi yok, sifirdan baslanıyor.")
    except Exception as e:
        _log(f"WARN state yukleme: {e}")


# ══════════════════════════════════════════════
# MT5 BAĞLANTI
# ══════════════════════════════════════════════


def _init_mt5(force: bool = False) -> bool:
    global _mt5_ok
    if _mt5_ok and not force:
        return True
    try:
        import MetaTrader5 as mt5

        if not mt5.initialize():
            _log(f"MT5 baslatılamadı: {mt5.last_error()}")
            _mt5_ok = False
            return False
        if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
            ok = mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
            if not ok:
                _log(f"MT5 login hatası: {mt5.last_error()}")
                _mt5_ok = False
                return False
        info = mt5.account_info()
        if info is None:
            _log("MT5 hesap bilgisi alinamadi.")
            _mt5_ok = False
            return False
        print(
            f"  MT5 baglandi: {info.name} | {info.server} | "
            f"Bakiye: {info.balance:.2f} {info.currency}",
            flush=True,
        )
        _mt5_ok = True
        return True
    except ImportError:
        _log("MetaTrader5 paketi yok. pip install MetaTrader5")
        return False
    except Exception as e:
        _log(f"MT5 init hatasi: {e}")
        _mt5_ok = False
        return False


def _get_mt5_balance() -> float:
    try:
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is not None:
            return info.balance
        # Bağlantı kopmuş olabilir — yeniden bağlan
        _log("WARN MT5 account_info None — yeniden baglaniyor...")
        if _init_mt5(force=True):
            info = mt5.account_info()
            return info.balance if info else state["balance"]
        return state["balance"]
    except Exception:
        return state["balance"]


def _get_mt5_equity() -> float:
    """Anlık equity (yüzen zarar dahil) — prop günlük DD equity üzerinden ölçülür."""
    try:
        import MetaTrader5 as mt5

        info = mt5.account_info()
        return float(info.equity) if info is not None else state["balance"]
    except Exception:
        return state["balance"]


def _detect_broker_offset():
    """Broker sunucu saat offset'ini MT5 tick zamanından tespit et + logla.
    Session'ı broker saatine hizalar → backtest ile birebir aynı saatte işlem."""
    global _BROKER_OFFSET_H
    try:
        import MetaTrader5 as mt5
        from datetime import datetime as _dt, timezone as _tz

        for sym in TRADE_SYMBOLS:
            tick = mt5.symbol_info_tick(sym)
            if tick and tick.time:
                broker_wall = _dt.utcfromtimestamp(tick.time)
                real_utc = _dt.now(_tz.utc).replace(tzinfo=None)
                off = round((broker_wall - real_utc).total_seconds() / 3600)
                _BROKER_OFFSET_H = off
                fark = off - 3
                _log(
                    f"Broker saati: UTC{off:+d} | Türkiye (UTC+3) farkı: {fark:+d} saat | "
                    f"Session {SESSION_START:02d}:00–{SESSION_END:02d}:00 broker saatiyle "
                    f"(backtest ile birebir)"
                )
                if fark != 0:
                    _log(
                        f"NOT: Broker Türkiye'den {fark:+d} saat farklı → session Türkiye "
                        f"saatiyle {SESSION_START+fark:02d}:00–{SESSION_END+fark:02d}:00'a denk gelir."
                    )
                return
    except Exception as e:
        _log(f"WARN broker offset tespit: {e} — varsayılan UTC+3 kullanılıyor")


def _verify_account() -> bool:
    """
    Açılışta MT5 hesabının beklenen login/sunucu/para birimi olduğunu doğrula.
    (madde 6) — yanlış hesapta (gerçek/demo karışması) işlem açılmasını önler.
    Beklenen değerler .env'de tanımlı değilse o kontrol atlanır.
    """
    try:
        import MetaTrader5 as mt5

        info = mt5.account_info()
        if info is None:
            _log("HATA: Hesap doğrulama — account_info None.")
            return False
        if config.EXPECT_LOGIN and int(info.login) != config.EXPECT_LOGIN:
            _log(f"HATA: Login uyuşmuyor! Beklenen {config.EXPECT_LOGIN}, "
                 f"gerçek {info.login}. Bot başlatılmadı.")
            return False
        if config.EXPECT_SERVER and str(info.server) != config.EXPECT_SERVER:
            _log(f"HATA: Sunucu uyuşmuyor! Beklenen {config.EXPECT_SERVER}, "
                 f"gerçek {info.server}. Bot başlatılmadı.")
            return False
        if config.EXPECT_CURRENCY and str(info.currency) != config.EXPECT_CURRENCY:
            _log(f"HATA: Para birimi uyuşmuyor! Beklenen {config.EXPECT_CURRENCY}, "
                 f"gerçek {info.currency}. Bot başlatılmadı.")
            return False
        _log(f"Hesap doğrulandı: login={info.login} | {info.server} | {info.currency}")
        return True
    except Exception as e:
        _log(f"HATA hesap doğrulama: {e}")
        return False


# ══════════════════════════════════════════════
# VERİ ÇEKME
# ══════════════════════════════════════════════


def _fetch(symbol: str, tf: str, bars: int = 500) -> Optional[pd.DataFrame]:
    try:
        import MetaTrader5 as mt5

        tf_map = {
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "1h": mt5.TIMEFRAME_H1,
            "4h": mt5.TIMEFRAME_H4,
        }
        mt5_tf = tf_map.get(tf)
        if mt5_tf is None:
            return None
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, bars)
        if rates is None or len(rates) == 0:
            alt = symbol + "m" if not symbol.endswith("m") else symbol[:-1]
            rates = mt5.copy_rates_from_pos(alt, mt5_tf, 0, bars)
            if rates is None or len(rates) == 0:
                return None
        df = pd.DataFrame(rates)
        df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "volume"})
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df = df[df["timestamp"].dt.dayofweek < 5].reset_index(drop=True)
        return df[["timestamp", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        _log(f"WARN veri cekme {symbol} {tf}: {e}")
        return None


# ══════════════════════════════════════════════
# MT5 İŞLEM
# ══════════════════════════════════════════════


def _risk_tavan(symbol: str) -> float:
    """Bu sembol için tek işlemde izin verilen en büyük $ zarar (sert tavan)."""
    cap = config.MAX_LOSS_PER_TRADE_USD
    if symbol in config.INDEX_SYMBOLS:
        cap = min(cap, config.MAX_LOSS_PER_INDEX_TRADE_USD)
    return cap


def _risk_dolar(symbol: str, price: float, sl: float, lot: float) -> float:
    """Verilen lot + SL mesafesi ile gerçekleşecek $ zararı (hesap para birimi).
    Tavan kontrolünün tek doğruluk kaynağı — _lot_hesapla ile aynı formül."""
    try:
        import MetaTrader5 as mt5

        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.0
        tick_siz = info.trade_tick_size
        if not tick_siz:
            return 0.0
        return (info.trade_tick_value / tick_siz) * abs(price - sl) * lot
    except Exception:
        return 0.0


def _lot_hesapla(riske: float, current_price: float, sl: float, symbol: str) -> float:
    try:
        import MetaTrader5 as mt5

        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.01
        sl_dist = abs(current_price - sl)
        if sl_dist == 0:
            return 0.01
        tick_val = info.trade_tick_value
        tick_siz = info.trade_tick_size
        if tick_siz == 0:
            return 0.01
        pip_value_per_lot = (tick_val / tick_siz) * sl_dist
        if pip_value_per_lot == 0:
            return 0.01
        raw_lot = riske / pip_value_per_lot
        raw_lot = max(info.volume_min, min(info.volume_max, raw_lot))
        step = info.volume_step or 0.01
        # KORUMA #1: adımı YUKARI değil AŞAĞI yuvarla — yukarı yuvarlamak lotu
        # (dolayısıyla riski) tavanın üstüne taşıyabilirdi. Aşağı floor asla aşmaz.
        lot = round(math.floor(raw_lot / step) * step, 8)
        return max(info.volume_min, lot)
    except Exception as e:
        _log(f"WARN lot hesaplama {symbol}: {e}")
        return 0.01


def _broker_min_stop(symbol: str) -> float:
    """Broker'ın izin verdiği minimum stop mesafesi (fiyat cinsinden).
    trade_stops_level × point. Broker 0 dönerse güvenlik tamponu (10 point).
    Boyutlama ve gönderim AYNI kaynağı kullansın diye tek fonksiyonda."""
    try:
        import MetaTrader5 as mt5

        si = mt5.symbol_info(symbol)
        if si is None:
            return 0.0
        point = si.point if si.point else 0.00001
        min_dist = getattr(si, "trade_stops_level", 0) * point
        if min_dist <= 0:
            min_dist = 10 * point
        return min_dist
    except Exception:
        return 0.0


def _islem_ac(
    symbol: str, yon: str, lot: float, sl: float, tp: float, comment: str = "SMT",
    max_risk_usd: float = 0.0,
) -> Optional[int]:
    try:
        import MetaTrader5 as mt5

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None or not sym_info.visible:
            mt5.symbol_select(symbol, True)
            time.sleep(0.5)

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            _log(f"WARN tick alinamadi: {symbol}")
            return None

        price = tick.ask if yon == "LONG" else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if yon == "LONG" else mt5.ORDER_TYPE_SELL

        si = mt5.symbol_info(symbol)

        # --- 10016 fix: SL/TP normalizasyon + broker min stop mesafesi ---
        digits = si.digits if si else 5
        point = si.point if si and si.point else 0.00001
        min_dist = getattr(si, "trade_stops_level", 0) * point if si else 0
        if min_dist <= 0:
            min_dist = 10 * point  # broker 0 dönerse güvenlik tamponu
        if yon == "LONG":
            if price - sl < min_dist:
                sl = price - min_dist
            if tp - price < min_dist:
                tp = price + min_dist
        else:
            if sl - price < min_dist:
                sl = price + min_dist
            if price - tp < min_dist:
                tp = price - min_dist
        price = round(price, digits)
        sl = round(sl, digits)
        tp = round(tp, digits)

        # --- 10014 fix: lot min/max/step sinirla ---
        if si:
            v_min = si.volume_min or 0.01
            v_max = si.volume_max or 100.0
            v_step = si.volume_step or 0.01
            # KORUMA #2: adımı aşağı floor (yukarı yuvarlama tavanı aşabilir)
            lot = round(math.floor(lot / v_step) * v_step, 8)
            if lot < v_min:
                lot = v_min
            if lot > v_max:
                lot = v_max

        # ── KORUMA #2: SON TAVAN — LOTU BÜZ (iptal etme) ──
        # Gönderim anı fiyat + broker min-stop, SL'i sizing anındakinden biraz
        # genişletmiş olabilir. Emri GÖNDERMEDEN önce lotu, gerçek risk tavanı
        # ASLA geçmeyecek en büyük değere DÜŞÜR (aşağı yuvarla → risk ≤ tavan
        # garanti). Yalnızca broker minimum lotu bile tavanı aşıyorsa iptal et
        # (o sembolde tavana sığmak fiziksel olarak imkânsız — hata değil).
        if max_risk_usd and max_risk_usd > 0 and si:
            ts_ = si.trade_tick_size
            tv_ = si.trade_tick_value
            sl_dist = abs(price - sl)
            if ts_ and tv_ and sl_dist > 0:
                risk_per_lot = (tv_ / ts_) * sl_dist
                if risk_per_lot > 0:
                    izinli_max_lot = max_risk_usd / risk_per_lot
                    if lot > izinli_max_lot:
                        v_step2 = si.volume_step or 0.01
                        v_min2 = si.volume_min or 0.01
                        yeni_lot = round(math.floor(izinli_max_lot / v_step2) * v_step2, 8)
                        if yeni_lot < v_min2:
                            son_risk = risk_per_lot * v_min2
                            _log(
                                f"IPTAL {symbol} {yon} — min-lot riski ${son_risk:.0f} > "
                                f"tavan ${max_risk_usd:.0f} (broker minimum lotu küçültülemez). "
                                f"Bu sembolde tavana sığmıyor, işlem açılmadı."
                            )
                            return None
                        eski_lot = lot
                        lot = yeni_lot
                        _log(
                            f"LOT BÜZÜLDÜ {symbol} {yon} — stop broker min-mesafesiyle genişledi; "
                            f"lot {eski_lot} → {lot} (risk tavanı ${max_risk_usd:.0f} korunuyor)"
                        )

        # --- 10030 fix: broker'in destekledigi filling mode'u sec ---
        fill = mt5.ORDER_FILLING_IOC
        if si:
            fm = getattr(si, "filling_mode", 0)
            if fm & 1:  # SYMBOL_FILLING_FOK
                fill = mt5.ORDER_FILLING_FOK
            elif fm & 2:  # SYMBOL_FILLING_IOC
                fill = mt5.ORDER_FILLING_IOC
            else:
                fill = mt5.ORDER_FILLING_RETURN

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": 20250101,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": fill,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            rc = result.retcode if result else "None"
            _log(f"HATA islem acilamadi {symbol} {yon}: retcode={rc}")
            return None
        return result.order
    except Exception as e:
        _log(f"HATA islem ac {symbol}: {e}")
        return None


def _islem_kapat(ticket: int, symbol: str, yon: str, lot: float) -> bool:
    try:
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return False
        price = tick.bid if yon == "LONG" else tick.ask
        order_type = mt5.ORDER_TYPE_SELL if yon == "LONG" else mt5.ORDER_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": 20250101,
            "comment": "SMT_CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    except Exception as e:
        _log(f"HATA islem kapat {symbol}: {e}")
        return False


def _sl_guncelle(ticket: int, symbol: str, yeni_sl: float, yeni_tp: float = None) -> bool:
    """Açık pozisyonun SL (ve opsiyonel TP) seviyesini değiştir (breakeven/trailing).

    ÖNEMLİ (FTM/gerçek broker uyumu): Yeni SL, mevcut fiyata broker'ın izin verdiği
    minimum mesafeden (trade_stops_level) daha yakın olamaz — yoksa broker emri
    10016 (invalid stops) ile REDDEDER ve SL taşınmaz. MetaQuotes-Demo'da min-stop=0
    olduğu için bu görünmezdi; FTM'de XAUUSD=20 puan → 0.5R'de breakeven reddedilirdi.
    Bu yüzden yeni SL'i fiyattan en az min-stop uzağa KIRPARIZ (breakeven mümkün
    olduğunca korunur, emir de kabul edilir)."""
    try:
        import MetaTrader5 as mt5

        si = mt5.symbol_info(symbol)
        digits = si.digits if si else 5
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p = pos[0]
        is_long = (p.type == mt5.POSITION_TYPE_BUY)

        # ── Broker min-stop mesafesine göre kırp (10016 reddini önle) ──
        tick = mt5.symbol_info_tick(symbol)
        min_dist = _broker_min_stop(symbol)
        if tick is not None and min_dist > 0:
            if is_long:
                en_yakin = tick.bid - min_dist  # SL fiyata bundan yakın olamaz
                if yeni_sl > en_yakin:
                    yeni_sl = en_yakin
            else:
                en_yakin = tick.ask + min_dist
                if yeni_sl < en_yakin:
                    yeni_sl = en_yakin

        # ── GÜVENLİK: sadece DAHA SIKI yöne taşı — asla riski ARTIRMA ──
        # Kırpma sonrası yeni SL mevcut SL'den daha kötü (riski artıran) olursa
        # dokunma; mevcut SL zaten daha iyi. Böylece breakeven asla ters tepmez.
        cur_sl = float(p.sl) if p.sl else 0.0
        if cur_sl > 0:
            if is_long and yeni_sl <= cur_sl:
                return True   # mevcut SL zaten daha sıkı/eşit — başarı say, dokunma
            if (not is_long) and yeni_sl >= cur_sl:
                return True

        cur_tp = float(p.tp) if yeni_tp is None else yeni_tp
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": round(float(yeni_sl), digits),
            "tp": round(float(cur_tp), digits),
            "magic": 20250101,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    except Exception as e:
        _log(f"HATA SL guncelle {symbol}: {e}")
        return False


def _pozisyon_yonet():
    """
    Kâr yönetimi (Grup 2) — 1:1 RR KORUNUR.
    Açık her pozisyon için: fiyat +PARTIAL_TP_R'ye ulaştıysa pozisyonun
    PARTIAL_CLOSE_PCT kadarını kapat (kâr cebe) ve kalanın SL'ini breakeven'e çek.
    """
    if not config.partial_aktif():
        return
    for sym, ot in list(open_trades.items()):
        try:
            if ot.get("partial_done"):
                continue
            giris = ot["giris"]
            sl = ot["sl"]
            yon = ot["yon"]
            sl_dist = abs(giris - sl)
            if sl_dist <= 0:
                continue
            fiyat = _mt5_son_fiyat(sym)
            if fiyat is None:
                continue
            r_now = ((fiyat - giris) if yon == "LONG" else (giris - fiyat)) / sl_dist
            if r_now < config.PARTIAL_TP_R:
                continue
            # 1) Kısmi kapama
            kapat_lot = round(ot["lot"] * config.PARTIAL_CLOSE_PCT, 4)
            kalan_lot = round(ot["lot"] - kapat_lot, 4)
            if kapat_lot <= 0 or kalan_lot <= 0:
                continue
            if config.DRY_RUN or _islem_kapat(ot["ticket"], sym, yon, kapat_lot):
                ot["lot"] = kalan_lot
                ot["partial_done"] = True
                kismi_pnl = ot.get("riske", 0) * config.PARTIAL_CLOSE_PCT * config.PARTIAL_TP_R
                # 2) Breakeven — sonucu KONTROL et (FTM'de reddedilirse fark et),
                #    başarısızsa 1 kez daha dene, yine olmazsa alarm ver (sessiz kalma).
                be_ok = True
                be = None
                if config.BREAKEVEN_ENABLED:
                    be = (giris + config.BE_BUFFER_R * sl_dist) if yon == "LONG" \
                        else (giris - config.BE_BUFFER_R * sl_dist)
                    if config.DRY_RUN:
                        ot["sl"] = be
                    else:
                        be_ok = _sl_guncelle(ot["ticket"], sym, be)
                        if not be_ok:
                            be_ok = _sl_guncelle(ot["ticket"], sym, be)  # 1 kez daha dene
                        if be_ok:
                            ot["sl"] = be  # sadece gerçekten taşındıysa iç durumu güncelle
                        else:
                            _log(
                                f"UYARI {sym} {yon} — breakeven SL TAŞINAMADI (broker reddetti). "
                                f"ORİJİNAL stop hâlâ devrede (pozisyon korumasız değil)."
                            )
                            notifier.alarm(
                                f"⚠️ {sym} {yon} — breakeven SL taşınamadı! Orijinal stop "
                                f"devrede ama kâr kilidi kurulamadı. Manuel bakabilirsin."
                            )
                _save_state()
                db.log_partial(ot.get("ticket"))
                kalan_pct = 1 - config.PARTIAL_CLOSE_PCT
                _log(
                    f"KISMI KAR | {sym} {yon} | +{config.PARTIAL_TP_R}R'de "
                    f"%{int(config.PARTIAL_CLOSE_PCT*100)} kapandi (+${kismi_pnl:.2f}) | "
                    f"{'SL->breakeven OK' if be_ok else 'SL->breakeven BASARISIZ'} | "
                    f"kalan %{int(kalan_pct*100)}"
                )
                notifier.partial_be(sym, kismi_pnl, kalan_pct, be_ok=be_ok, be_price=be)
        except Exception as e:
            _log(f"WARN pozisyon yonet {sym}: {e}")


def _katastrofi_kontrol():
    """KATASTROFİ KORUMASI (Katman 4) — broker SL DELİNİRSE ikinci savunma hattı.

    Her açık pozisyonun YÜZEN zararı, planlanan riskin CATASTROPHE_R katını aşarsa
    (yani broker stop'u bir spike'ta delip-geçtiyse) pozisyonu ANINDA piyasa emriyle
    kapatır. 1436$ tipi (5.74R) olay bir daha yaşanmasın diye. Açık pozisyon varken
    her 10sn çağrılır. Alarm bir kez atılır, kapama başarısızsa her turda tekrar denenir.
    """
    if not config.CATASTROPHE_GUARD_ENABLED:
        return
    for sym, ot in list(open_trades.items()):
        try:
            riske = ot.get("riske", 0)
            giris = ot.get("giris", 0)
            sl = ot.get("sl", 0)
            yon = ot.get("yon", "LONG")
            sl_dist = abs(giris - sl)
            if riske <= 0 or sl_dist <= 0:
                continue
            fiyat = _mt5_son_fiyat(sym)
            if fiyat is None:
                continue
            # Yüzen R: negatifse zarardayız
            r_now = ((fiyat - giris) if yon == "LONG" else (giris - fiyat)) / sl_dist
            if r_now >= -config.CATASTROPHE_R:
                continue  # zarar henüz eşiğin altında — normal SL zaten 1R'de kapatır
            yuzen = riske * abs(r_now)
            if not ot.get("katastrofi_bildirildi"):
                ot["katastrofi_bildirildi"] = True
                _log(
                    f"KATASTROFI KAPAMA | {sym} {yon} | yüzen zarar {abs(r_now):.2f}R "
                    f"(~${yuzen:.0f}) > tavan {config.CATASTROPHE_R}R — broker stop delindi, "
                    f"ACİL piyasa kapaması"
                )
                notifier.alarm(
                    f"⛔ <b>{sym} {yon} KATASTROFİ KAPAMA</b> — yüzen zarar {abs(r_now):.2f}R "
                    f"(~${yuzen:.0f}), broker stop DELİNDİ. Pozisyon acil kapatılıyor. "
                    f"Telefonundan kontrol et!"
                )
            if not config.DRY_RUN:
                _islem_kapat(ot["ticket"], sym, yon, ot["lot"])
        except Exception as e:
            _log(f"WARN katastrofi kontrol {sym}: {e}")


def _mt5_pozisyon_var_mi(ticket: int) -> bool:
    try:
        import MetaTrader5 as mt5

        positions = mt5.positions_get(ticket=ticket)
        return positions is not None and len(positions) > 0
    except Exception:
        return False


def _mt5_pozisyon_lot(ticket: int) -> Optional[float]:
    """Pozisyon hâlâ açıksa mevcut lot miktarını döndür, yoksa None."""
    try:
        import MetaTrader5 as mt5

        positions = mt5.positions_get(ticket=ticket)
        if positions and len(positions) > 0:
            return float(positions[0].volume)
        return None
    except Exception:
        return None


def _mt5_sync_open_trades():
    """bot_state ile MT5 gerçek pozisyonları karşılaştır; hayalet kayıtları temizle."""
    for sym in list(open_trades.keys()):
        ot = open_trades[sym]
        ticket = ot.get("ticket")
        if not ticket:
            continue
        current_lot = _mt5_pozisyon_lot(ticket)
        if current_lot is None:
            # Pozisyon MT5'te yok ama bot_state'de var → hayalet kayıt
            _log(
                f"WARN hayalet pozisyon | {sym} ticket={ticket} | MT5'te yok, _acik_islemleri_kontrol kapatacak"
            )
        elif abs(current_lot - ot.get("lot", current_lot)) > 1e-6:
            # Lot azalmış ama pozisyon hâlâ açık → partial close
            old_lot = ot["lot"]
            open_trades[sym]["lot"] = current_lot
            _log(
                f"PARTIAL CLOSE algılandi | {sym} | Lot: {old_lot:.4f} → {current_lot:.4f} | "
                f"Pozisyon hâlâ açık, takip sürüyor"
            )
            _save_state()


def _mt5_son_fiyat(symbol: str) -> Optional[float]:
    try:
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        return (tick.bid + tick.ask) / 2 if tick else None
    except Exception:
        return None


# ══════════════════════════════════════════════
# PROP FIRM / GÜNLÜK KONTROL
# ══════════════════════════════════════════════


def _gun_guncelle():
    global _day_traded_date, day_traded_syms
    now = _now_tr()
    today = now.strftime("%Y-%m-%d")

    if state["day_date"] != today:
        state["day_date"] = today
        state["day_sl_count"] = 0
        state["day_sl_total"] = 0.0
        state["day_tp_count"] = 0
        # Yeni gün — SL engel listesini sıfırla
        if _day_traded_date != today:
            day_traded_syms.clear()
            _day_traded_date = today
        mt5_bal = _get_mt5_balance()
        if mt5_bal > 0:
            if abs(mt5_bal - state["balance"]) > 1:
                _log(
                    f"Gun basi bakiye sync: state=${state['balance']:.2f} → "
                    f"MT5=${mt5_bal:.2f}"
                )
            state["balance"] = mt5_bal
        # Equity-DD referansı: gün başı bakiye (madde 32)
        state["day_start_balance"] = state["balance"]
        state.pop("_sl_limit_logged", None)  # yeni gün, limit logunu sıfırla
        _log(f"Yeni gun: {today} | Bakiye: ${state['balance']:.2f}")
        _save_state()


def _gunluk_sl_doldu() -> bool:
    """Günlük %2 kayıp limitine veya günde 2 SL limitine ulaştık mı?
    (Haftalık 3 SL kuralı kaldırıldı — artık işlem engellemez.)"""
    gun_limit = BOT_PROP_FIRM["starting_balance"] * MAX_DAILY_LOSS_PCT
    return (
        state["day_sl_total"] >= gun_limit
        or state["day_sl_count"] >= 2
    )


def _pf_blown_mu() -> bool:
    return state["balance"] < state["pf_floor"]


def _flatten_all(reason: str):
    """Tüm açık pozisyonları anında kapat (equity-DD / haftasonu / acil)."""
    if not open_trades:
        return
    _log(f"FLATTEN — tüm pozisyonlar kapatılıyor: {reason}")
    notifier.alarm(f"Tüm pozisyonlar kapatılıyor: {reason}")
    for sym, ot in list(open_trades.items()):
        try:
            if not config.DRY_RUN:
                _islem_kapat(ot["ticket"], sym, ot["yon"], ot["lot"])
        except Exception as e:
            _log(f"WARN flatten {sym}: {e}")
    # Kapanışları normal akışta yakala
    _acik_islemleri_kontrol()


def _equity_dd_kontrol() -> bool:
    """
    Equity-bazlı günlük DD (madde 32) — prop firmalar yüzen zararı da sayar.
    Equity, günlük limite EQUITY_DD_BUFFER_USD kadar kala TÜM pozisyonları kapat
    ve günü blokla. True dönerse günün geri kalanında işlem yok.
    """
    if not config.EQUITY_DD_ENABLED:
        return False
    equity = _get_mt5_equity()
    pf_start = BOT_PROP_FIRM["starting_balance"]
    gun_limit = pf_start * MAX_DAILY_LOSS_PCT
    # Günlük başlangıç referansı: gün başı bakiye (kapalı) - equity farkı
    gun_kayip_equity = state.get("day_start_balance", state["balance"]) - equity
    # Max DD (floor) equity üzerinden
    if equity < state["pf_floor"] + config.EQUITY_DD_BUFFER_USD:
        if open_trades:
            _flatten_all(f"Equity floor'a yaklaştı (equity ${equity:.0f}, floor ${state['pf_floor']:.0f})")
        return True
    # Günlük limit equity üzerinden
    if gun_kayip_equity >= (gun_limit - config.EQUITY_DD_BUFFER_USD):
        if open_trades:
            _flatten_all(f"Equity günlük limite yaklaştı (kayıp ${gun_kayip_equity:.0f}/${gun_limit:.0f})")
        return True
    return False


def _payout_kontrol():
    pf = BOT_PROP_FIRM
    if state["payout_count"] == 0:
        target = pf["starting_balance"] * pf.get("profit_target_first", 0.10)
    else:
        target = pf["starting_balance"] * pf.get("profit_target", 0.02)
    kazanc = state["balance"] - pf["starting_balance"]
    if kazanc >= target:
        state["payout_count"] += 1
        state["total_payouts"] += kazanc
        trader_net = kazanc * pf["trader_share"]
        _log(
            f"PAYOUT #{state['payout_count']} | "
            f"Kar: ${kazanc:.2f} | Trader: ${trader_net:.2f} | "
            f"Payout kaydedildi — bakiye/floor GERÇEK MT5 bakiyesini takip ediyor."
        )
        # NOT: Gerçek MT5 hesabında bakiye, prop firma para çekene kadar değişmez ve
        # her işlem/gün başında MT5'ten senkronize edilir. Bu yüzden balance/peak/floor'u
        # burada sanal olarak sıfırlamak bir sonraki sync'te eziliyordu (tutarsız floor).
        # Çekim gerçekleştiğinde MT5 bakiyesi düşer ve sync otomatik yakalar.
        # pf_floor, TP'lerde pf_peak üzerinden trailing olarak güncellenmeye devam eder.
        state["dyn_risk"] = config.RISK_PCT
        state["consec_tp"] = 0
        _save_state()


# ══════════════════════════════════════════════
# KORELASYOn FİLTRESİ
# ══════════════════════════════════════════════


# ══════════════════════════════════════════════
# AÇIK İŞLEM TAKİP
# ══════════════════════════════════════════════


def _acik_islemleri_kontrol():
    """MT5'te SL/TP'ye çarpanları tespit et, dinamik riski güncelle."""
    global day_traded_syms
    # Önce partial close'ları yakala — lot değişmiş ama pozisyon hâlâ açık
    _mt5_sync_open_trades()

    kapananlar = []
    for sym, ot in list(open_trades.items()):
        ticket = ot.get("ticket")
        if ticket and not _mt5_pozisyon_var_mi(ticket):
            sonuc, pnl = _kapanis_bilgisi(ticket, ot)
            kapananlar.append((sym, ot, sonuc, pnl))

    for sym, ot, sonuc, pnl in kapananlar:
        riske = ot["riske"]
        if sonuc == "TP":
            # Bakiyeyi MT5'ten senkronize et — en doğru değer
            mt5_bal = _get_mt5_balance()
            if mt5_bal > 0:
                state["balance"] = mt5_bal
            else:
                # fallback: açılışta riske düşülmediği için sadece kârı ekle (1:1 RR ≈ riske)
                state["balance"] += pnl
            # Trailing peak/floor güncelle
            if state["balance"] > state["pf_peak"]:
                state["pf_peak"] = state["balance"]
                state["pf_floor"] = (
                    state["pf_peak"]
                    - BOT_PROP_FIRM["starting_balance"] * BOT_PROP_FIRM["max_drawdown"]
                )  # floor = peak - sabit $600 (%6 DD kuralı)
            # Dinamik risk: TP sonrası taban riske dön (config)
            state["consec_tp"] += 1
            state["day_tp_count"] += 1
            state["dyn_risk"] = config.RISK_PCT
            _log(
                f"TP | {sym} {ot['yon']} | PNL: +${pnl:.2f} | "
                f"Bakiye: ${state['balance']:.2f} | Floor: ${state['pf_floor']:.2f} | "
                f"Sonraki risk: %{state['dyn_risk']*100:.1f}"
            )
            _gun_limit = BOT_PROP_FIRM["starting_balance"] * MAX_DAILY_LOSS_PCT
            db.log_close(ot.get("ticket"), "TP", pnl, bakiye_kapanis=state["balance"])
            notifier.trade_closed(sym, ot["yon"], "TP", pnl, state["balance"],
                                  state["day_sl_total"], _gun_limit)
            _payout_kontrol()
        else:
            # Bakiyeyi MT5'ten senkronize et — manuel kapama/SL farkını yakala
            mt5_bal = _get_mt5_balance()
            if mt5_bal > 0:
                state["balance"] = mt5_bal
            else:
                state["balance"] -= pnl  # fallback
            state["day_sl_count"] += 1
            state["day_sl_total"] += pnl
            # Dinamik risk: SL sonrası taban riskin yarısına düş (config)
            state["consec_tp"] = 0
            state["dyn_risk"] = config.RISK_PCT * 0.5
            # SL vuruldu — o sembol ve korelasyon grubu bugün engellenir (backtest ile aynı)
            day_traded_syms.add(sym)
            for grp in CORR_GROUPS:
                if sym in grp:
                    day_traded_syms.update(grp)
            # Kayma tespiti: gerçek kayıp / planlanan risk (1R = riske)
            riske_plan = ot.get("riske", pnl) or pnl
            slippage_R = (pnl / riske_plan) if riske_plan > 0 else 1.0
            _gun_limit = BOT_PROP_FIRM["starting_balance"] * MAX_DAILY_LOSS_PCT
            _log(
                f"SL | {sym} {ot['yon']} | PNL: -${pnl:.2f} | Kayma: {slippage_R:.2f}R | "
                f"Gun kayip: ${state['day_sl_total']:.0f}/${_gun_limit:.0f} | "
                f"Bakiye: ${state['balance']:.2f} | "
                f"Sonraki risk: %{state['dyn_risk']*100:.1f} | "
                f"Bugun engelli: {day_traded_syms}"
            )
            db.log_close(ot.get("ticket"), "SL", -pnl, slippage_R=round(slippage_R, 2),
                         bakiye_kapanis=state["balance"])
            notifier.trade_closed(sym, ot["yon"], "SL", -pnl, state["balance"],
                                  state["day_sl_total"], _gun_limit, slippage_R=slippage_R)
            # Anormal kayma alarmı (madde 12)
            if slippage_R > 1.5:
                notifier.alarm(
                    f"{sym} SL {slippage_R:.2f}R kaydı! Planlanan ${riske_plan:.0f}, "
                    f"gerçek ${pnl:.0f}. Slippage koruması gözden geçirilmeli."
                )
            # madde 44 — sert $ zarar tavanı aşımı (canlıda gap yazılımla geri
            # alınamaz; en azından tespit + alarm). Endeks boyutlaması ($75) bunu
            # nadir kılar; aştıysa boyutlama/stop mesafesi ciddi gözden geçirilmeli.
            if config.HARD_LOSS_CAP_ENABLED and pnl > config.MAX_LOSS_PER_TRADE_USD:
                notifier.alarm(
                    f"{sym} SL zararı ${pnl:.0f} > sert tavan "
                    f"${config.MAX_LOSS_PER_TRADE_USD:.0f}! Endeks kayması gerçekleşti — "
                    f"boyutlama/stop mesafesini gözden geçir."
                )
            if _pf_blown_mu():
                state["blown"] = True
                _log("HESAP PATLAMASI! Max drawdown asıldı. Bot durdu.")
                notifier.alarm("🔴 HESAP PATLAMASI! Max drawdown aşıldı. Bot durdu.")

        open_trades.pop(sym, None)
        active_setups.pop(sym, None)
        _save_state()


def _kapanis_bilgisi(ticket: int, ot: Dict):
    """
    TP/SL siniflandirmasi CIKIS FIYATI ile yapilir (SL'e mi TP'ye mi yakin).
    Bu brokerin deal-history kar/zarar toplami GUVENILMEZ oldugu icin ona bakilmaz.
    Buyukluk (pnl): tek islem acikken bakiye farki, es zamanli ise riske.
    """
    yon = ot.get("yon", "LONG")
    tp = ot.get("tp", 0)
    sl = ot.get("sl", 0)
    riske = ot.get("riske", 100.0)

    mt5_bal_now = _get_mt5_balance()
    bal_open = ot.get("balance_at_open", state["balance"])

    # 1) EN KESIN: tek islem acik + bakiye anlamli degismis
    #    Bakiye DUSTUYSE zarar=SL, ARTTIYSA kar=TP. Hicbir seye bagli degil, %100 kesin.
    if mt5_bal_now > 0 and len(open_trades) <= 1 and abs(mt5_bal_now - bal_open) >= 0.5:
        sonuc = "TP" if mt5_bal_now > bal_open else "SL"
        return sonuc, abs(mt5_bal_now - bal_open)

    # 2) Es zamanli islem VEYA bakiye okunamadi → cikis fiyatini SL/TP ile karsilastir
    exit_price = None
    try:
        import MetaTrader5 as mt5

        deals = mt5.history_deals_get(position=ticket)
        if deals:
            outs = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
            if outs:
                exit_price = float(outs[-1].price)
    except Exception:
        pass
    if not exit_price or exit_price <= 0:
        exit_price = _mt5_son_fiyat(ot["symbol"]) or ot.get("giris", 0)

    if tp and sl:
        sonuc = "TP" if abs(exit_price - tp) <= abs(exit_price - sl) else "SL"
    else:
        giris = ot.get("giris", exit_price)
        if yon == "LONG":
            sonuc = "TP" if exit_price >= giris else "SL"
        else:
            sonuc = "TP" if exit_price <= giris else "SL"

    return sonuc, riske


# ══════════════════════════════════════════════
# FİLTRELER & HEDEF-KİLİT (Grup 4 / madde 42)
# ══════════════════════════════════════════════

def _haber_penceresi_mi(symbol: str, now) -> bool:
    """Endeksler için: ABD açılışı ±dk penceresinde miyiz? (Haber filtresi kaldırıldı.)"""
    if symbol not in config.INDEX_SYMBOLS:
        return False
    if config.US_OPEN_BLOCK:
        open_dt = now.replace(hour=config.US_OPEN_HOUR_TR, minute=config.US_OPEN_MIN_TR,
                              second=0, microsecond=0)
        if abs((now - open_dt).total_seconds()) <= config.US_OPEN_BLOCK_MIN * 60:
            return True
    return False


def _correlation_engelli(symbol: str) -> bool:
    """Aynı korelasyon grubunda zaten açık işlem varsa yeni açma (madde 16)."""
    if not config.CORRELATION_ONE_PER_GROUP:
        return False
    for grp in CORR_GROUPS:
        if symbol in grp and any(a in grp for a in open_trades):
            return True
    return False


def _spread_genis_mi(symbol: str) -> bool:
    """Anlık spread, tablo değerinin SPREAD_CAP_MULT katından genişse açma (madde 18)."""
    if not config.SPREAD_CAP_ENABLED:
        return False
    try:
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return False
        spread_now = abs(tick.ask - tick.bid)
        cap = SPREAD_TABLE.get(symbol, 0.0) * config.SPREAD_CAP_MULT
        return cap > 0 and spread_now > cap
    except Exception:
        return False


def _hedef_kilit_aktif() -> bool:
    """Kâr hedefine ulaşıldı → yeni işlem açma (madde 42)."""
    if not (config.TARGET_LOCK_ENABLED and config.TARGET_LOCK_STOP_AT_TARGET):
        return False
    hedef = BOT_PROP_FIRM["starting_balance"] * config.PROFIT_TARGET_PCT
    return (state["balance"] - BOT_PROP_FIRM["starting_balance"]) >= hedef


def _hedefe_yakin_mi() -> bool:
    """Hedefin TARGET_LOCK_NEAR_PCT'ine gelindi → riski minimuma indir (madde 42)."""
    if not config.TARGET_LOCK_ENABLED:
        return False
    hedef = BOT_PROP_FIRM["starting_balance"] * config.PROFIT_TARGET_PCT
    kazanc = state["balance"] - BOT_PROP_FIRM["starting_balance"]
    return kazanc >= hedef * config.TARGET_LOCK_NEAR_PCT


def _fill_dogrula(ticket: int, symbol: str, yon: str) -> bool:
    """
    Fill sonrası SL yapıştı mı? (madde 15) Korumasız pozisyon = prop felaketi.
    SL yoksa pozisyonu güvenlik için kapat + alarm.
    """
    try:
        import MetaTrader5 as mt5

        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return True  # kontrol edilemez (zaten kapanmış olabilir)
        p = pos[0]
        if not p.sl or float(p.sl) == 0.0:
            _log(f"HATA {symbol} — SL yapışmadı! Pozisyon güvenlik için kapatılıyor.")
            _islem_kapat(ticket, symbol, yon, float(p.volume))
            notifier.alarm(f"{symbol} SL yapışmadı → pozisyon kapatıldı (korumasız pozisyon önlendi).")
            return False
        return True
    except Exception as e:
        _log(f"WARN fill dogrula {symbol}: {e}")
        return True


# ══════════════════════════════════════════════
# SİNYAL TARAMA
# ══════════════════════════════════════════════


def _sembol_tara(symbol: str):
    """
    Tek sembol için:
    1. Aktif setup varsa → giriş sinyali ara
    2. Setup yoksa     → sweep+SMT tara, setup kaydet
    """
    if symbol in open_trades:
        active_setups.pop(symbol, None)
        return
    if symbol in day_traded_syms:
        return
    if symbol in config.DISABLED_SYMBOLS:  # madde 19 — forward-teste kadar kapalı
        return
    if _correlation_engelli(symbol):  # madde 16
        return
    if _hedef_kilit_aktif():  # madde 42 — hedefe ulaşıldı, koru
        return
    if len(open_trades) >= MAX_OPEN:
        return

    # Veri çek
    df5 = _fetch(symbol, "5m", 200)
    df15 = _fetch(symbol, "15m", 100)
    df4h = _fetch(symbol, "4h", 150)
    df1h = _fetch(symbol, "1h", 150)

    if df5 is None or len(df5) < 50:
        return

    # Zaman: session BROKER saatiyle (backtest mum saatiyle birebir aynı),
    # haber/ABD açılışı filtresi ise Türkiye saatiyle (o sabitler TR bazlı).
    now_tr = _now_tr()
    now_broker = _broker_now()

    # Session filtresi — broker saati 09:00–20:00 = backtest penceresiyle BİREBİR
    if not _in_session(now_broker):
        return

    # HTF trend
    df4h_s = (
        df4h.tail(100).reset_index(drop=True)
        if df4h is not None and len(df4h) >= 30
        else None
    )
    df1h_s = (
        df1h.tail(100).reset_index(drop=True)
        if df1h is not None and len(df1h) >= 30
        else None
    )
    trend = _htf_trend(df4h_s, df1h_s)
    if trend == "YATAY":
        active_setups.pop(symbol, None)
        return

    # SMT çift verisi — EURUSD sadece referans, işlem açılmaz
    pair_sym = SMT_PAIRS.get(symbol)
    df_pair = None
    if pair_sym:
        dp = _fetch(pair_sym, "5m", 150)
        if dp is not None and len(dp) >= 10:
            df_pair = dp.tail(100).reset_index(drop=True)

    df5_s = df5.tail(101).iloc[:-1].reset_index(drop=True)
    df15_s = (
        df15.tail(40).reset_index(drop=True)
        if df15 is not None and len(df15) >= 5
        else None
    )

    # ── Aktif setup varsa giriş ara ──
    setup = active_setups.get(symbol)

    if setup is not None:
        setup["bars_waited"] += 1
        # Trend değiştiyse veya süre dolduysa setup iptal
        if setup["bars_waited"] > SETUP_MAX_WAIT or setup["trend"] != trend:
            active_setups.pop(symbol, None)
            setup = None

    if setup is None:
        # Yeni sweep+SMT tara
        sweep_idx = _find_sweep(df5_s, trend)
        if sweep_idx >= 0 and _smt_divergence(df5_s, df_pair, trend, sweep_idx, symbol):
            if symbol not in active_setups:
                active_setups[symbol] = {
                    "trend": trend,
                    "sweep_idx": sweep_idx,
                    "bars_waited": 0,
                }
                _log(
                    f"SETUP | {symbol} {trend} | sweep@{sweep_idx} SMT onaylı — giriş bekleniyor"
                )
                notifier.setup(symbol, trend, f"sweep@{sweep_idx} SMT✓")
        return  # Bu taramada giriş yok; setup yeni kaydedildi ya da yok

    # ── Setup aktif — MSS + OB/IFVG giriş sinyali ──
    last_row = df5_s.iloc[-1]
    cp = float(last_row["close"])

    res = _entry_signal(
        df5_s,
        last_row,
        cp,
        setup["sweep_idx"],
        df15_s,
        df4h_s,
        df1h_s,
        trend,
        symbol,
    )
    if res is None:
        return

    # Sinyal geldi — setup temizle
    active_setups.pop(symbol, None)

    # ── Filtreler (Grup 4) — sinyal geldi ama koşul uygun mu? ──
    if _haber_penceresi_mi(symbol, now_tr):  # madde 17 — ABD açılışı TR saatiyle
        _log(f"SKIP {symbol} {trend} — ABD açılışı penceresi")
        return
    if _spread_genis_mi(symbol):  # madde 18
        _log(f"SKIP {symbol} {trend} — spread çok geniş")
        return

    # Spread ekle
    spread = SPREAD_TABLE.get(symbol, 0.0)
    cp_entry = cp + spread if trend == "LONG" else cp - spread

    # ATR
    atr_val = _atr(df15_s if df15_s is not None else df5_s)
    if atr_val <= 0:
        atr_val = cp * 0.001

    # SL / TP (1:1.5 RR korunur)
    sl, _, sl_ok = _calc_sl(cp_entry, trend, symbol, res.get("ob"), atr_val, df15_s)
    if not sl_ok:
        _log(f"SKIP {symbol} {trend} — SL geçersiz (çok geniş)")
        return

    # ── Broker minimum stop mesafesini BOYUTLAMADAN ÖNCE uygula ──
    # Lot, gönderilecek NİHAİ stop'a göre hesaplanır; böylece gönderim anında
    # stop'un genişleyip riski tavanın üstüne taşıması imkânsız hale gelir
    # ($875 sorununun kökü buydu). TP de nihai stop'tan hesaplanır → RR korunur.
    min_stop = _broker_min_stop(symbol)
    if min_stop > 0:
        if trend == "LONG":
            if cp_entry - sl < min_stop:
                sl = cp_entry - min_stop
        else:
            if sl - cp_entry < min_stop:
                sl = cp_entry + min_stop

    tp = _calc_tp(cp_entry, sl, trend, config.TP_R)

    # Dinamik risk
    pf = BOT_PROP_FIRM
    dyn_risk = state["dyn_risk"]
    risk_ratio = min(dyn_risk, pf.get("max_risk_per_trade", 0.025))

    # Floor protection: floor'a yaklaştıkça riski kıs
    floor_buffer = state["balance"] - state["pf_floor"]
    floor_pct = floor_buffer / pf["starting_balance"]
    if floor_pct < 0.03:
        risk_ratio = min(risk_ratio, 0.005)
    elif floor_pct < 0.04:
        risk_ratio = min(risk_ratio, 0.010)
    elif floor_pct < 0.05:
        risk_ratio = min(risk_ratio, 0.015)

    # Hedefe yakınsa riski minimuma indir (hedef-kilit, madde 42)
    if _hedefe_yakin_mi():
        risk_ratio = min(risk_ratio, 0.005)

    # Günlük kayıp limiti
    day_limit = pf["starting_balance"] * MAX_DAILY_LOSS_PCT
    remaining = day_limit - state["day_sl_total"]
    if remaining <= 0:
        return

    riske = min(pf["starting_balance"] * risk_ratio, remaining * 0.90)

    # Evrensel per-trade $ tavan (tüm sembollere aynı)
    riske = min(riske, config.MAX_LOSS_PER_TRADE_USD)
    # madde 43 — endeks per-trade risk tavanı (backtest ile parite)
    if symbol in config.INDEX_SYMBOLS:
        riske = min(riske, config.MAX_LOSS_PER_INDEX_TRADE_USD)

    if riske < pf["starting_balance"] * 0.001:  # $10 taban
        return

    # Worst-case kontrolü (Katman 3) — tek işlem limiti/DD'yi delemesin
    worst_case = riske * config.SLIP_FACTOR
    if config.WORST_CASE_CHECK:
        if worst_case > remaining:
            _log(f"SKIP {symbol} {trend} — worst-case ${worst_case:.0f} > günlük kalan ${remaining:.0f}")
            return
        if worst_case > floor_buffer:
            _log(f"SKIP {symbol} {trend} — worst-case ${worst_case:.0f} > floor tamponu ${floor_buffer:.0f}")
            return

    # Lot hesapla
    lot = _lot_hesapla(riske, cp_entry, sl, symbol)
    if lot <= 0:
        return

    # ── KORUMA #1 & #3: SERT $ TAVAN GUARD (tek işlemde tavan ASLA aşılmaz) ──
    # _lot_hesapla lotu min lota yükseltmiş olabilir; o durumda gerçek risk
    # tavanı geçebilir. Lot broker minimumunun altına inemeyeceği için bu
    # sembol/kurulumda tavan garanti edilemez → işlemi hiç açma, atla + alarm.
    cap = _risk_tavan(symbol)
    gercek_risk = _risk_dolar(symbol, cp_entry, sl, lot)
    RISK_TOL = 1.02  # %2 tolerans (tick/kayma yuvarlaması)
    if gercek_risk > cap * RISK_TOL:
        _log(
            f"SKIP {symbol} {trend} — min-lot riski ${gercek_risk:.0f} > tavan "
            f"${cap:.0f} (lot {lot} küçültülemez, işlem AÇILMADI)"
        )
        notifier.alarm(
            f"{symbol} {trend} ATLANDI — min-lot riski ${gercek_risk:.0f}, "
            f"tavan ${cap:.0f}. Tek işlemde tavan aşımı önlendi."
        )
        return

    ot_yeni = {
        "ticket": None,
        "symbol": symbol,
        "yon": trend,
        "giris": cp_entry,
        "sl": sl,
        "tp": tp,
        "lot": lot,
        "riske": riske,
        "risk_pct": round(risk_ratio * 100, 2),
        "worst_case": round(worst_case, 2),
        "entry_type": res["entry_type"],
        "in_zone": res["in_zone"],
        "mss": res["mss"],
        "partial_done": False,
        "acilis_ts": str(_now_tr()),
        "balance_at_open": state["balance"],
    }

    # CONFIRM modu (madde 14): telegram'dan onay bekle (timeout=açma)
    if config.TELEGRAM_MODE == "CONFIRM":
        if not notifier.ask_confirmation(ot_yeni):
            _log(f"SKIP {symbol} {trend} — CONFIRM onayı gelmedi")
            return

    # DRY_RUN: gerçek emir gönderme (madde 39)
    if config.DRY_RUN:
        _log(f"[DRY_RUN] ISLEM (sanal) | {symbol} {trend} {res['entry_type']} | "
             f"Giris:{cp_entry:.5f} SL:{sl:.5f} TP:{tp:.5f} | Lot:{lot:.4f} Risk:${riske:.2f}")
        notifier.trade_opened(ot_yeni)
        return

    # MT5'te işlem aç (KORUMA #2: cap gönderilir → SL genişlerse emir iptal)
    comment = f"SMT {res['entry_type']}"
    ticket = _islem_ac(symbol, trend, lot, sl, tp, comment=comment, max_risk_usd=cap)
    if ticket is None:
        _log(f"HATA islem acilamadi: {symbol}")
        notifier.alarm(f"{symbol} {trend} işlem açılamadı (retcode). Kontrol et.")
        return

    # Fill sonrası SL doğrulaması (madde 15) — SL yoksa pozisyon kapatılır
    if not _fill_dogrula(ticket, symbol, trend):
        return

    # Bakiyeyi MT5'ten senkronize et
    mt5_bal = _get_mt5_balance()
    if mt5_bal > 0:
        state["balance"] = mt5_bal

    ot_yeni["ticket"] = ticket
    ot_yeni["balance_at_open"] = state["balance"]
    open_trades[symbol] = ot_yeni
    _save_state()
    db.log_open(ot_yeni)

    _log(
        f"ISLEM ACILDI | {symbol} {trend} {res['entry_type']} | "
        f"Giris:{cp_entry:.5f} SL:{sl:.5f} TP:{tp:.5f} | "
        f"Lot:{lot:.4f} Risk:${riske:.2f}(%{risk_ratio*100:.1f}) | Worst:${worst_case:.0f}"
    )
    notifier.trade_opened(ot_yeni)


# ══════════════════════════════════════════════
# DURUM RAPORU
# ══════════════════════════════════════════════


def _durum_satiri(scan_count: int, now_utc, now_local, tarama_sym: str = ""):
    """Her 10sn CMD'ye basılan tek satır özet."""
    session = _in_session(now_utc)
    ses_str = "AKTIF " if session else "KAPALI"
    kazanc = state["balance"] - BOT_PROP_FIRM["starting_balance"]
    k_str = f"+${kazanc:,.0f}" if kazanc >= 0 else f"-${abs(kazanc):,.0f}"
    setups = ",".join(active_setups.keys()) if active_setups else "—"
    pos = f"{len(open_trades)}/{MAX_OPEN}"
    gun_limit = BOT_PROP_FIRM["starting_balance"] * MAX_DAILY_LOSS_PCT
    sl = f"${state['day_sl_total']:.0f}/${gun_limit:.0f}"
    toplam_riske = sum(t.get("riske", 0) for t in open_trades.values())
    risk_str = (
        f"Risk:${toplam_riske:.0f}(%{toplam_riske/state['balance']*100:.1f})"
        if toplam_riske > 0
        else "Risk:—"
    )
    tara = f" Tara:{tarama_sym}" if tarama_sym else f" #{scan_count}"

    line = (
        f"  {now_local.strftime('%H:%M:%S')} | {ses_str} | "
        f"Bakiye:${state['balance']:,.0f}({k_str}) | "
        f"Pos:{pos} {risk_str} SL:{sl} | Setup:{setups} |{tara}"
    )
    # Satırı sabit uzunlukta tut (eski yazı kalmasın)
    print(line.ljust(100), end="\r", flush=True)


def _rapor_yazdir(baslik: str = "DURUM RAPORU"):
    pf = BOT_PROP_FIRM
    kazanc = state["balance"] - pf["starting_balance"]
    now_str = _now_tr().strftime("%Y-%m-%d %H:%M:%S")
    durum = "SAGLIKLI" if not state["blown"] else "PATLAMIS"
    day_lim = pf["starting_balance"] * MAX_DAILY_LOSS_PCT
    kazanc_str = f"+${kazanc:,.2f}" if kazanc >= 0 else f"-${abs(kazanc):,.2f}"

    satirlar = [
        "",
        "=" * 65,
        f"  SOFiNARD SMT DiVERGENCE BOT — {baslik}",
        f"  {now_str}",
        "=" * 65,
        f"  Bakiye        : ${state['balance']:>12,.2f}  ({kazanc_str})",
        f"  Dinamik Risk  : %{state['dyn_risk']*100:.1f} | Ust uste TP: {state['consec_tp']}",
        f"  Gun kayip     : ${state['day_sl_total']:.2f} / ${day_lim:.2f} | Gun SL: {state['day_sl_count']}/2",
        f"  Payout        : {state['payout_count']} kez | Toplam: ${state['total_payouts']:,.2f}",
        f"  Hesap durumu  : {durum}",
        f"  Acik islemler : {len(open_trades)}/{MAX_OPEN}",
        f"  Aktif setup   : {list(active_setups.keys())}",
    ]

    if open_trades:
        satirlar.append("  " + "─" * 61)
        for sym, ot in open_trades.items():
            cp = _mt5_son_fiyat(sym) or ot["giris"]
            sl_dist = abs(ot["giris"] - ot["sl"])
            raw = (cp - ot["giris"]) if ot["yon"] == "LONG" else (ot["giris"] - cp)
            unr = (raw / sl_dist * ot["riske"]) if sl_dist > 0 else 0
            unr_str = f"+${unr:.2f}" if unr >= 0 else f"-${abs(unr):.2f}"
            satirlar.append(
                f"  {sym:<10} {ot['yon']:<5} {ot.get('entry_type','?'):<12} | "
                f"Giris:{ot['giris']:.5f} | PNL:{unr_str:>10} | Lot:{ot.get('lot',0):.3f}"
            )

    satirlar += ["=" * 65, ""]
    rapor = "\n".join(satirlar)
    print(rapor, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(rapor + "\n")
    except Exception:
        pass


# ══════════════════════════════════════════════
# ANA DÖNGÜ
# ══════════════════════════════════════════════


_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.lock")
_lock_handle = None


def _acquire_single_instance_lock() -> bool:
    """Tek bir bot ornegi calismasini garanti eder. Ikinci ornek False alir.
    OS seviyesinde kilit — surec cokse bile otomatik birakilir (stale lock olmaz)."""
    global _lock_handle
    try:
        _lock_handle = open(_LOCK_FILE, "a+")
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_handle.seek(0)
        _lock_handle.truncate()
        _lock_handle.write(str(os.getpid()))
        _lock_handle.flush()
        return True
    except (OSError, IOError):
        return False


def main():
    if not _acquire_single_instance_lock():
        _log(
            "UYARI: Bot zaten calisiyor (kilit alinamadi). Ikinci ornek BASLATILMADI."
        )
        return
    _log("SOFiNARD SMT DiVERGENCE BOT baslatilıyor...")
    _rotate_log()

    # Config doğrulama (madde 39) — saçma parametre varsa başlama
    cfg_err = config.validate()
    if cfg_err:
        for e in cfg_err:
            _log(f"CONFIG HATASI: {e}")
        _log("Config geçersiz. Bot başlatılmadı.")
        return
    db.init()  # trade DB tablolarını hazırla (madde 5)
    if config.DRY_RUN:
        _log("DRY_RUN aktif — gerçek emir GÖNDERİLMEZ (sanal test modu).")
    _load_state()

    if not _init_mt5():
        _log("MT5 baglantısı kurulamadı. Cıkılıyor.")
        notifier.alarm("MT5 bağlantısı kurulamadı — bot başlayamadı.")
        return

    # Hesap doğrulama (madde 6) — yanlış hesapta işlem açmayı önle
    if not _verify_account():
        notifier.alarm("Hesap doğrulama başarısız — bot başlatılmadı.")
        return

    # Broker saat offset'ini tespit et → session backtest ile birebir hizalanır
    _detect_broker_offset()

    mt5_bal = _get_mt5_balance()
    if mt5_bal <= 0:
        _log(
            "HATA: MT5'ten bakiye alinamadi. Bot durduruluyor — lot hesabı yanlış olur."
        )
        return
    if abs(mt5_bal - state["balance"]) > 1:
        _log(f"Bakiye MT5'ten senkronize edildi: ${mt5_bal:.2f}")
    state["balance"] = mt5_bal

    # ── HESAP BOYUTU ANCHOR (dinamik) ──
    # İlk çalıştırmada (veya eski $10k state'inden geçişte) hesap boyutunu
    # .env ACCOUNT_SIZE veya gerçek MT5 bakiyesinden sabitle; floor/peak/tavanları
    # buna göre kur. Sonraki çalıştırmalarda persist edilen değer korunur (challenge
    # ortasında hedef/floor kaymasın).
    if not state.get("starting_balance"):
        base = config.ACCOUNT_SIZE or mt5_bal
        state["starting_balance"] = base
        state["pf_peak"] = max(base, mt5_bal)
        state["pf_floor"] = state["pf_peak"] - base * BOT_PROP_FIRM["max_drawdown"]
        _log(f"Hesap boyutu anchor edildi: ${base:,.2f} "
             f"(floor ${state['pf_floor']:,.2f}, DD %{BOT_PROP_FIRM['max_drawdown']*100:.0f})")
    # BOT_PROP_FIRM'i persist edilen boyuta hizala (tüm sizing/limit buradan okur)
    BOT_PROP_FIRM["starting_balance"] = state["starting_balance"]
    # Risk tavanlarını hesap boyutuna göre $'a çevir (yüzde-bazlı → oran sabit kalır)
    config.MAX_LOSS_PER_TRADE_USD = round(state["starting_balance"] * config.MAX_LOSS_PCT, 2)
    config.MAX_LOSS_PER_INDEX_TRADE_USD = round(state["starting_balance"] * config.MAX_LOSS_INDEX_PCT, 2)
    _log(f"Risk tavanlari: genel ${config.MAX_LOSS_PER_TRADE_USD:,.0f} | "
         f"endeks ${config.MAX_LOSS_PER_INDEX_TRADE_USD:,.0f} | "
         f"gunluk ${state['starting_balance']*MAX_DAILY_LOSS_PCT:,.0f} | "
         f"max DD ${state['starting_balance']*BOT_PROP_FIRM['max_drawdown']:,.0f}")

    # Equity-DD referansı: yeni gün veya eksikse mevcut bakiyeye ayarla (madde 32)
    _today = _now_tr().strftime("%Y-%m-%d")
    if state.get("day_date") != _today or not state.get("day_start_balance"):
        state["day_start_balance"] = state["balance"]
    _save_state()

    # Başlangıçta açık pozisyonları MT5 ile karşılaştır
    if open_trades:
        _log(f"Başlangıç sync: {len(open_trades)} kayıtlı pozisyon kontrol ediliyor...")
        _mt5_sync_open_trades()
        # bot_state'de var ama MT5'te kapanmış olanları işle
        _acik_islemleri_kontrol()

    scan_count = 0
    last_report = time.time()
    last_heartbeat = time.time()
    gun_rapor_tarihi = ""
    scan_count_gun = _now_tr().strftime("%Y-%m-%d")
    # ── Telegram self-test — 'bildirim gitmiyor' sorununu GÖRÜNÜR kıl ──
    # Sessizce atlamak yerine, çalışıyor mu / neden çalışmıyor mu NET logla.
    tg_ok, tg_sebep = notifier.self_test()
    if tg_ok:
        _log("Telegram bildirimleri AKTİF ✓ (test mesajı gönderildi — telefonunu kontrol et).")
        notifier.send(
            f"🤖 SOFiNARD Bot başladı | Bakiye ${state['balance']:,.0f} | "
            f"Mod: {config.TELEGRAM_MODE}{' | DRY_RUN' if config.DRY_RUN else ''}"
        )
    else:
        _log(
            f"UYARI: Telegram bildirimleri KAPALI — sebep: {tg_sebep}. "
            f"Telefonda bildirim/alarm istiyorsan .env'e TELEGRAM_BOT_TOKEN ve "
            f"TELEGRAM_CHAT_ID ekle (chat id için: python chatid_bul.py)."
        )

    pf = BOT_PROP_FIRM
    print("=" * 65, flush=True)
    print("  SOFiNARD SMT DiVERGENCE BOT  —  CANLI", flush=True)
    print("=" * 65, flush=True)
    print(f"  Bakiye         : ${state['balance']:>12,.2f}", flush=True)
    print(f"  Baslangic      : ${pf['starting_balance']:>12,.2f}", flush=True)
    print(
        f"  Gunluk Kayip   : %{MAX_DAILY_LOSS_PCT*100:.0f}  = ${pf['starting_balance']*MAX_DAILY_LOSS_PCT:,.2f}"
        f"  (gercekte uygulanan)",
        flush=True,
    )
    print(
        f"  Islem Riski    : %{config.RISK_PCT*100:.1f} = ${config.MAX_LOSS_PER_TRADE_USD:,.0f}/islem"
        f"  |  endeks ${config.MAX_LOSS_PER_INDEX_TRADE_USD:,.0f}",
        flush=True,
    )
    print(
        f"  Max Drawdown   : %{pf['max_drawdown']*100:.0f}  = ${pf['starting_balance']*pf['max_drawdown']:,.2f}",
        flush=True,
    )
    print(
        f"  Kar Hedefi     : %{pf['profit_target']*100:.0f}  = ${pf['starting_balance']*pf['profit_target']:,.2f}",
        flush=True,
    )
    print(
        f"  Session (TR)   : {SESSION_START:02d}:00 – {SESSION_END:02d}:00  |  Gunluk kayip limit: %{MAX_DAILY_LOSS_PCT*100:.0f}",
        flush=True,
    )
    print(f"  Semboller      : {', '.join(TRADE_SYMBOLS)}", flush=True)
    print("=" * 65, flush=True)
    print(f"  AKTIF AYAR: {config.mode_summary()}", flush=True)
    print("=" * 65, flush=True)
    print("  Tarama basliyor... (her 60sn guncellenir)", flush=True)
    print("=" * 65, flush=True)

    consecutive_mt5_errors = 0

    while True:
        try:
            if state["blown"]:
                _log("Hesap patlamis. Bot durdu. Manuel mudahale gerekli.")
                time.sleep(300)
                continue

            # MT5 bağlantı sağlığı kontrol — her döngüde
            if not _init_mt5():
                consecutive_mt5_errors += 1
                _log(
                    f"MT5 baglantisi yok ({consecutive_mt5_errors}. deneme). 30sn bekleniyor..."
                )
                # 3+ ard arda kopma → telefona haber ver (spam engelli)
                if consecutive_mt5_errors >= 3:
                    _alarm_kisitli(
                        "mt5_kopma",
                        f"🔌 MT5 bağlantısı koptu ({consecutive_mt5_errors} deneme). "
                        f"Bot işlem yapamıyor/açık pozisyonları izleyemiyor — kontrol et!",
                        saniye=900,
                    )
                time.sleep(30)
                continue
            consecutive_mt5_errors = 0

            _touch_heartbeat()  # watchdog canlılık damgası (madde 37)
            _gun_guncelle()

            # Haftasonu kontrolü — broker saatiyle (backtest ile birebir)
            now_broker = _broker_now()
            wd = now_broker.weekday()
            hu = now_broker.hour
            mn = now_broker.minute

            # Haftasonu flatten (madde 34): Cuma kapanıştan önce açıkları kapat
            if config.WEEKEND_FLATTEN and wd == 4 and open_trades and (
                hu > config.WEEKEND_FLATTEN_HOUR_TR
                or (hu == config.WEEKEND_FLATTEN_HOUR_TR
                    and mn >= config.WEEKEND_FLATTEN_MIN_TR)
            ):
                _flatten_all("Haftasonu yaklaşıyor — gap riski")

            is_weekend = wd == 5 or wd == 6 or (wd == 4 and hu >= 20)
            if is_weekend:
                print(
                    "  Haftasonu — piyasa kapali. Bekleniyor...", end="\r", flush=True
                )
                time.sleep(300)
                continue

            # Açık işlemleri kontrol + kâr yönetimi (Grup 2)
            _katastrofi_kontrol()  # broker stop delindiyse ACİL kapat (1436$ koruması)
            _acik_islemleri_kontrol()
            _pozisyon_yonet()

            # Equity-bazlı günlük DD (madde 32) — yüzen zarar dahil
            if _equity_dd_kontrol():
                if state.get("_equity_block") != state["day_date"]:
                    state["_equity_block"] = state["day_date"]
                    _log("Equity günlük DD limitine yaklaşıldı — bugün işlem yok.")
                    notifier.alarm("Equity günlük DD limiti — bugün işlem durdu.")
                time.sleep(120)
                continue

            # Günlük limit — sadece bir kere logla, sessizce bekle
            if _gunluk_sl_doldu():
                log_key = f"{state['day_date']}"
                if state.get("_sl_limit_logged") != log_key:
                    state["_sl_limit_logged"] = log_key
                    gun_limit = BOT_PROP_FIRM["starting_balance"] * MAX_DAILY_LOSS_PCT
                    if state["day_sl_count"] >= 2:
                        _log(f"Gunluk SL limitine ulasildi (2/2). Bugun islem yok.")
                    else:
                        _log(
                            f"Gunluk kayip limitine ulasildi (${state['day_sl_total']:.0f}/${gun_limit:.0f}). Bu gun islem yok."
                        )
                time.sleep(300)
                continue

            # Günlük TP limiti kaldırıldı — karlı günlerde serbest

            # Sinyal tara
            if len(open_trades) < MAX_OPEN:
                print(
                    f"\n  [{_now_tr().strftime('%H:%M:%S')}] Tarama #{scan_count} — "
                    f"{len(TRADE_SYMBOLS)} sembol: {', '.join(TRADE_SYMBOLS)}",
                    flush=True,
                )
                for symbol in TRADE_SYMBOLS:
                    if state["blown"] or _gunluk_sl_doldu():
                        break
                    if len(open_trades) >= MAX_OPEN:
                        break
                    now_utc = _now_tr()
                    now_local = _now_tr()
                    _durum_satiri(scan_count, now_utc, now_local, tarama_sym=symbol)
                    _sembol_tara(symbol)
                    now_utc = _now_tr()
                    now_local = _now_tr()
                    _durum_satiri(
                        scan_count, now_utc, now_local, tarama_sym=f"{symbol}✓"
                    )

            scan_count += 1

            # Yeni günde scan_count sıfırla (TR saatine göre)
            now_local = _now_tr()
            bugun = now_local.strftime("%Y-%m-%d")
            if bugun != scan_count_gun:
                scan_count = 0
                scan_count_gun = bugun

            # 30 dakikada bir durum raporu
            if time.time() - last_report > 1800:
                _rapor_yazdir()
                last_report = time.time()

            # Heartbeat (madde 13) — bot ayakta bildirimi
            if time.time() - last_heartbeat > config.HEARTBEAT_HOURS * 3600:
                notifier.heartbeat(state["balance"], len(open_trades))
                last_heartbeat = time.time()

            # Gece 23:59 günlük rapor + Telegram özet
            if (
                now_local.hour == 23
                and now_local.minute == 59
                and gun_rapor_tarihi != bugun
            ):
                gun_rapor_tarihi = bugun
                _rapor_yazdir(f"GUNLUK KAPANIS — {bugun}")
                kazanc = state["balance"] - BOT_PROP_FIRM["starting_balance"]
                notifier.daily_summary(
                    f"{bugun}\nBakiye: ${state['balance']:,.2f} "
                    f"({'+' if kazanc>=0 else '-'}${abs(kazanc):,.0f})\n"
                    f"Gün SL: {state['day_sl_count']} | TP: {state['day_tp_count']} | "
                    f"Gün kayıp: ${state['day_sl_total']:.0f}"
                )

            # Tarama özeti — her 10sn güncelle; açık pozisyon varsa hızlı kontrol
            elapsed = 0
            while elapsed < SCAN_INTERVAL:
                now_utc = _now_tr()
                now_local = _now_tr()
                _durum_satiri(scan_count, now_utc, now_local)
                # Hızlı kapanış + kâr yönetimi (madde 20): 14 dk gecikmeyi ~10sn'ye indir
                if open_trades and config.CLOSE_CHECK_FAST:
                    _katastrofi_kontrol()  # her 10sn: broker stop delindiyse acil kapat
                    _acik_islemleri_kontrol()
                    _pozisyon_yonet()
                time.sleep(10)
                elapsed += 10

        except KeyboardInterrupt:
            print("\nManuel kapatıldı.")
            _rapor_yazdir()
            _save_state()
            break
        except Exception as e:
            _log(f"HATA ana dongu: {e}")
            # Beklenmedik döngü hatası → telefona haber ver (spam engelli)
            _alarm_kisitli(
                "ana_dongu_hata",
                f"🐛 Bot ana döngü hatası: {e}. Bot ayakta ama bu hatayı kontrol et.",
                saniye=1800,
            )
            time.sleep(10)


if __name__ == "__main__":
    main()
