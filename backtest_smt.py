#!/usr/bin/env python3
"""
backtest_smt.py — SOFiNARD SMT Divergence v1 — LOOKAHEAD-FREE

Kullanım:
  python backtest_smt.py --months 6
  python backtest_smt.py --months 3 --show-trades
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone

# Encoding güvenliği: Türkçe/özel karakterler cp1252 konsolda çökertmesin
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd

import config
from strategy import (
    SYMBOLS,
    SMT_PAIRS,
    CORR_GROUPS,
    PROP_FIRM,
    SPREAD_TABLE,
    SLIPPAGE_TABLE,
    FIXED_RISK,
    SETUP_MAX_WAIT,
    SESSION_START,
    SESSION_END,
    BLOCKED_HOURS,
    _atr,
    _htf_trend,
    _find_sweep,
    _smt_divergence,
    _entry_signal,
    _calc_sl,
    _calc_tp,
)

INITIAL_BALANCE = 10_000.0

# Canlı botta SYMBOLS kullanılır; backtest için kripto semboller ek olarak test edilebilir
BACKTEST_SYMBOLS = SYMBOLS

random.seed(42)


def _in_session(ts):
    h = ts.hour
    return SESSION_START <= h < SESSION_END and h not in BLOCKED_HOURS


# ══════════════════════════════════════════════
# MT5 VERİ
# ══════════════════════════════════════════════

_mt5_init = False


def _init_mt5():
    global _mt5_init
    if _mt5_init:
        return True
    try:
        import MetaTrader5 as mt5

        if not mt5.initialize():
            print(f"MT5 hatasi: {mt5.last_error()}")
            return False
        print(f"MT5 baglandi: {mt5.terminal_info().name}")
        _mt5_init = True
        return True
    except ImportError:
        print("MetaTrader5 paketi yuklu degil")
        return False


def fetch_mt5(symbol, tf_str, start_ms, end_ms):
    if not _init_mt5():
        return None
    try:
        import MetaTrader5 as mt5

        tf_map = {
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "1h": mt5.TIMEFRAME_H1,
            "4h": mt5.TIMEFRAME_H4,
        }
        tf = tf_map.get(tf_str)
        if tf is None:
            return None
        dt_from = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        dt_to = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
        rates = mt5.copy_rates_range(symbol, tf, dt_from, dt_to)
        if rates is None or len(rates) == 0:
            alt = symbol + "m" if not symbol.endswith("m") else symbol[:-1]
            rates = mt5.copy_rates_range(alt, tf, dt_from, dt_to)
            if rates is None or len(rates) == 0:
                return None
        df = pd.DataFrame(rates)
        df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "volume"})
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df = df[df["timestamp"].dt.dayofweek < 5].reset_index(drop=True)
        keep = ["timestamp", "open", "high", "low", "close", "volume"]
        # GERÇEK geçmiş spread (puan cinsinden) — spread filtresi için sakla.
        if "spread" in df.columns:
            df["spread"] = df["spread"].astype(float)
            keep.append("spread")
        return df[keep]
    except Exception as e:
        print(f"  MT5 {symbol} {tf_str}: {e}")
        return None


# ══════════════════════════════════════════════
# BACKTEST
# ══════════════════════════════════════════════


def run_backtest(symbols, months, prop_firm=None, start_dt=None, end_dt=None):
    pf = prop_firm or {}
    pf_enabled = pf.get("enabled", False)
    pf_start = pf.get("starting_balance", INITIAL_BALANCE)
    pf_max_dd = pf_start * pf.get("max_drawdown", 0.06)
    pf_daily_lim = pf_start * pf.get("daily_loss_limit", 0.02)
    pf_day_stop = (
        pf_start * config.DAILY_LOSS_PCT
    )  # günlük limit (config — bot_worker ile aynı)
    pf_trailing = pf.get("trailing_drawdown", False)
    pf_max_per = pf.get("max_risk_per_trade", 0.025)

    if end_dt is None:
        end_dt = datetime.now(tz=timezone.utc)
    if start_dt is None:
        start_dt = end_dt - timedelta(days=30 * months)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    W = 72
    print(f"\n{'='*W}")
    print(f"  {'SOFiNARD SMT DiVERGENCE v1 — LOOKAHEAD-FREE':^{W}}")
    print(f"{'='*W}")
    print(
        f"  {start_dt.strftime('%Y-%m-%d')} -> {end_dt.strftime('%Y-%m-%d')} ({months} ay)"
    )
    print(f"  AKTIF AYAR: {config.mode_summary()}")
    print(f"  Semboller: {', '.join(symbols)}\n")

    data = {}
    pair_data = {}
    ref_syms = {SMT_PAIRS[s] for s in symbols if s in SMT_PAIRS}

    for sym in symbols:
        print(f"  Veri: {sym}", end=" ")
        d5 = fetch_mt5(sym, "5m", start_ms, end_ms)
        d15 = fetch_mt5(sym, "15m", start_ms, end_ms)
        d4h = fetch_mt5(sym, "4h", start_ms, end_ms)
        d1h = fetch_mt5(sym, "1h", start_ms, end_ms)
        if d5 is None or len(d5) < 100:
            print("yetersiz, atlanıyor")
            continue
        print(f"OK {len(d5)}x5m")
        data[sym] = {"5m": d5, "15m": d15, "4h": d4h, "1h": d1h}

    for rsym in ref_syms:
        print(f"  Ref: {rsym}", end=" ")
        d5r = fetch_mt5(rsym, "5m", start_ms, end_ms)
        if d5r is not None:
            print(f"OK {len(d5r)}x5m")
            pair_data[rsym] = d5r
        else:
            print("bulunamadi — bu sembol icin SMT atlanir")

    if not data:
        print("Veri yok!")
        return {}

    # ── SPREAD TABANI (medyan) — spread-çok-geniş filtresi için (madde 18) ──
    # Her sembolün GERÇEK geçmiş spread'inin medyanı = "normal" spread. O anki bar
    # spread'i medyanın SPREAD_CAP_MULT katını aşarsa canlıdaki gibi işlem atlanır.
    spread_baseline = {}
    for _s in data:
        _d5 = data[_s]["5m"]
        if "spread" in _d5.columns and len(_d5) > 0:
            _med = float(_d5["spread"].median())
            spread_baseline[_s] = _med if _med > 0 else 0.0
        else:
            spread_baseline[_s] = 0.0
    _spread_veri_var = any(v > 0 for v in spread_baseline.values())
    print(
        f"  Spread filtresi: {'GERCEK gecmis spread ile AKTIF' if _spread_veri_var else 'veri yok — pasif'}"
    )

    all_ts = set()
    for d in data.values():
        all_ts.update(d["5m"]["timestamp"].tolist())
    sorted_ts = sorted(all_ts)

    balance = pf_start if pf_enabled else INITIAL_BALANCE
    open_trades = {}
    closed = []
    sym_stats = {s: {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0} for s in data}
    monthly = {}
    monthly_trades = {}
    hour_stats = {}

    dyn_risk = config.RISK_PCT
    consec_tp = 0

    pf_peak = pf_start
    pf_floor = pf_start - pf_max_dd
    pf_min_bal = pf_start
    pf_max_dd_seen = 0.0  # peak'ten en büyük düşüş (trailing DD)
    pf_max_dd_seen_pct = 0.0
    pf_blown = False
    pf_day = None
    day_traded_syms: set = set()
    pf_day_sl = 0.0
    pf_day_sl_count = 0
    pf_day_tp_count = 0
    pf_blocked = False
    MAX_DAILY_SL_COUNT = 2  # günde max 2 SL → dur
    MAX_OPEN = (
        config.MAX_OPEN
    )  # aynı anda max pozisyon (config — bot_worker ile tutarlı)
    pf_payouts = []
    pf_total_p = 0.0
    pf_payout_count = 0
    MAX_DAILY_LOSS_PCT = config.DAILY_LOSS_PCT  # günlük kayıp limiti (config)

    _cache = {s: {} for s in data}
    active_setups = {}

    for ts in sorted_ts:
        if pf_enabled and pf_blown:
            break

        candle_day = ts.date() if hasattr(ts, "date") else ts.to_pydatetime().date()
        if candle_day != pf_day:
            day_traded_syms = set()
        if pf_enabled and candle_day != pf_day:
            pf_day, pf_day_sl, pf_day_sl_count, pf_blocked = (
                candle_day,
                0.0,
                0,
                False,
            )
        if pf_enabled and pf_trailing and balance > pf_peak:
            pf_peak = balance
            pf_floor = pf_peak - pf_max_dd
        if pf_enabled:
            dd_now = pf_peak - balance
            dd_now_pct = dd_now / pf_start * 100
            if dd_now > pf_max_dd_seen:
                pf_max_dd_seen = dd_now
                pf_max_dd_seen_pct = dd_now_pct

        kapanan = []
        for sym, ot in list(open_trades.items()):
            row = data[sym]["5m"]
            r = row[row["timestamp"] == ts]
            if r.empty:
                continue
            h_, lo_ = float(r.iloc[0]["high"]), float(r.iloc[0]["low"])
            yon, tp, riske = ot["yon"], ot["tp"], ot["riske"]
            giris = ot["giris"]
            cost_R = ot.get("cost_R", 0.0)
            r_dist = ot.get("r_dist", abs(giris - ot["sl"])) or abs(giris - ot["sl"])

            # Önce mevcut SL/TP durumu (partial öncesi = orijinal SL)
            sl = ot["sl"]
            sl_hit = (yon == "LONG" and lo_ <= sl) or (yon == "SHORT" and h_ >= sl)
            tp_hit = (yon == "LONG" and h_ >= tp) or (yon == "SHORT" and lo_ <= tp)
            if sl_hit and tp_hit:
                tp_hit = False

            # ── Kâr yönetimi (E4): +PARTIAL_TP_R'de kısmi kapama + breakeven ──
            # 1:1 RR KORUNUR (TP hâlâ 1R). Canlı bot ile birebir aynı mantık.
            # Bu bar SL'i vurmadıysa ve henüz partial değilse kısmi tetiklenir.
            partial_just_now = False
            if config.partial_aktif() and not ot.get("partial_done") and not sl_hit:
                partial_px = (
                    giris + config.PARTIAL_TP_R * r_dist
                    if yon == "LONG"
                    else giris - config.PARTIAL_TP_R * r_dist
                )
                reached = (yon == "LONG" and h_ >= partial_px) or (
                    yon == "SHORT" and lo_ <= partial_px
                )
                if reached:
                    ot["partial_done"] = True
                    ot["realized_R"] = config.PARTIAL_CLOSE_PCT * config.PARTIAL_TP_R
                    partial_just_now = True
                    if config.BREAKEVEN_ENABLED:
                        # Breakeven bir SONRAKİ bardan aktif (aynı barda tekrar vurmasın)
                        ot["sl"] = (
                            giris + config.BE_BUFFER_R * r_dist
                            if yon == "LONG"
                            else giris - config.BE_BUFFER_R * r_dist
                        )

            partial_done = ot.get("partial_done", False)
            realized_R = ot.get("realized_R", 0.0)
            rem_frac = (1.0 - config.PARTIAL_CLOSE_PCT) if partial_done else 1.0

            # Breakeven SL'e çekildiyse (partial'ın triggerlandığı bar HARİÇ),
            # "SL" aslında kâr/başabaş → kazanç say
            be_win = partial_done and sl_hit and not tp_hit and not partial_just_now

            if tp_hit or be_win:
                if tp_hit:
                    total_R = (
                        realized_R + rem_frac * config.TP_R
                    )  # kalan TP'ye (TP_R kadar)
                else:  # be_win: kalan breakeven'de kapandı
                    be_R = (abs(sl - giris) / r_dist) if r_dist > 0 else 0.0
                    total_R = realized_R + rem_frac * be_R
                pnl = riske * total_R * (1.0 - cost_R)
                balance += riske + pnl
                if pf_enabled:
                    pf_day_tp_count += 1
                if pf_enabled and pf_trailing and balance > pf_peak:
                    pf_peak = balance
                    pf_floor = pf_peak - pf_max_dd
                if pf_enabled:
                    pf_min_bal = min(pf_min_bal, balance)
                m = str(ts)[:7]
                monthly[m] = monthly.get(m, 0) + pnl
                if m not in monthly_trades:
                    monthly_trades[m] = {"tp": 0, "sl": 0}
                monthly_trades[m]["tp"] += 1
                h = pd.Timestamp(ot["giris_ts"]).hour
                if h not in hour_stats:
                    hour_stats[h] = {"count": 0, "pnl": 0.0}
                hour_stats[h]["count"] += 1
                hour_stats[h]["pnl"] += pnl
                closed.append(
                    {**ot, "sonuc": "TP", "pnl": round(pnl, 2), "cikis_ts": str(ts)}
                )
                sym_stats[sym]["wins"] += 1
                sym_stats[sym]["total"] += 1
                sym_stats[sym]["pnl"] += pnl
                kapanan.append(sym)

                consec_tp += 1
                dyn_risk = config.RISK_PCT

                if pf_payout_count == 0:
                    next_target = pf_start * pf.get("profit_target_first", 0.10)
                else:
                    next_target = pf_start * pf.get("profit_target", 0.02)
                if pf_enabled and (balance - pf_start) >= next_target:
                    profit = balance - pf_start
                    pf_payout_count += 1
                    pf_total_p += profit
                    pf_payouts.append(
                        {
                            "no": pf_payout_count,
                            "symbol": sym,
                            "date": str(candle_day),
                            "profit": round(profit, 2),
                        }
                    )
                    if pf.get("reset_on_payout"):
                        balance = pf_start
                        pf_peak = pf_start
                        pf_floor = pf_start - pf_max_dd
                        dyn_risk = config.RISK_PCT
                        consec_tp = 0
                    print(
                        f"  PAYOUT #{pf_payout_count} | {sym} | ${profit:+,.2f} | {candle_day}"
                    )

            elif sl_hit:
                # Gerçek zarar = 1R + round-trip maliyet + (endekste) delip-geçme kuyruğu
                # Bu kuyruk, US100 $305 (3R) olayını modelleyen realizmdir (madde 21).
                tail_R = 0.0
                if (
                    sym in config.INDEX_SYMBOLS
                    and random.random() < config.SLIP_TAIL_PROB
                ):
                    tail_R = random.uniform(
                        config.SLIP_TAIL_MIN_R, config.SLIP_TAIL_MAX_R
                    )
                riske_sl = riske * (1.0 + cost_R + tail_R)
                # madde 44 — sert $ zarar tavanı: gerçekleşen zarar bu değeri aşmaz
                if config.HARD_LOSS_CAP_ENABLED:
                    riske_sl = min(riske_sl, config.MAX_LOSS_PER_TRADE_USD)
                # riske açılışta zaten düşüldü; tavan sonrası kalan kısmı şimdi düş
                balance -= riske_sl - riske
                if pf_enabled:
                    pf_day_sl += riske_sl
                    pf_day_sl_count += 1
                    if pf_day_sl >= pf_start * MAX_DAILY_LOSS_PCT:
                        pf_blocked = True
                    if pf_day_sl_count >= MAX_DAILY_SL_COUNT:
                        pf_blocked = True
                    if pf_trailing and balance < pf_floor:
                        pf_blown = True
                    elif not pf_trailing and (pf_start - balance) >= pf_max_dd:
                        pf_blown = True
                    pf_min_bal = min(pf_min_bal, balance)
                m = str(ts)[:7]
                monthly[m] = monthly.get(m, 0) - riske_sl
                if m not in monthly_trades:
                    monthly_trades[m] = {"tp": 0, "sl": 0}
                monthly_trades[m]["sl"] += 1
                h = pd.Timestamp(ot["giris_ts"]).hour
                if h not in hour_stats:
                    hour_stats[h] = {"count": 0, "pnl": 0.0}
                hour_stats[h]["count"] += 1
                hour_stats[h]["pnl"] -= riske_sl
                closed.append(
                    {
                        **ot,
                        "sonuc": "SL",
                        "pnl": round(-riske_sl, 2),
                        "cikis_ts": str(ts),
                        "cost": round(riske * cost_R, 2),
                    }
                )
                sym_stats[sym]["losses"] += 1
                sym_stats[sym]["total"] += 1
                sym_stats[sym]["pnl"] -= riske_sl
                kapanan.append(sym)
                day_traded_syms.add(sym)
                for grp in CORR_GROUPS:
                    if sym in grp:
                        day_traded_syms.update(grp)

                consec_tp = 0
                dyn_risk = config.RISK_PCT * 0.5
                if pf_enabled and pf_blown:
                    print(
                        f"\n  HESAP PATLADI! {candle_day} | "
                        f"Bakiye:${balance:,.2f} | Floor:${pf_floor:,.2f} | Peak:${pf_peak:,.2f}"
                    )
                    break

        for sym in kapanan:
            open_trades.pop(sym, None)
        if pf_enabled and pf_blown:
            break

        if ts.weekday() == 4 and ts.hour >= 20:
            continue
        if not _in_session(ts):
            continue
        if (
            pf_enabled and pf_blocked
        ):  # haftalik 3 SL durdurmasi backtest icin kapatildi
            continue

        # ── HEDEF-KİLİT (madde 42) — canlı bot ile parite ──
        # Kâr hedefine (PROFIT_TARGET_PCT) ulaşıldıysa yeni işlem AÇMA (kârı koru).
        hedef_kilit = False
        if config.TARGET_LOCK_ENABLED and config.TARGET_LOCK_STOP_AT_TARGET:
            hedef = pf_start * config.PROFIT_TARGET_PCT
            if (balance - pf_start) >= hedef:
                hedef_kilit = True

        for sym in data:
            # Ayni anda max MAX_OPEN pozisyon (bot_worker ile tutarli)
            if len(open_trades) >= MAX_OPEN:
                break
            if hedef_kilit:  # hedefe ulaşıldı → yeni işlem yok (canlı parite)
                break
            if sym in open_trades:
                active_setups.pop(sym, None)
                continue
            if sym in day_traded_syms:
                continue
            # ── KORELASYON GRUBU (madde 16) — canlı bot ile parite ──
            # Aynı korelasyon grubunda zaten AÇIK işlem varsa yeni açma.
            if config.CORRELATION_ONE_PER_GROUP and any(
                sym in grp and any(a in grp for a in open_trades)
                for grp in CORR_GROUPS
            ):
                active_setups.pop(sym, None)
                continue

            df5 = data[sym]["5m"]
            idx = df5[df5["timestamp"] == ts].index
            if len(idx) == 0:
                continue
            idx = idx[0]
            if idx < 30:
                continue

            cp = float(df5.iloc[idx]["close"])

            df4h = data[sym]["4h"]
            df1h = data[sym]["1h"]
            l4 = df4h[df4h["timestamp"] <= ts] if df4h is not None else None
            l1 = df1h[df1h["timestamp"] <= ts] if df1h is not None else None
            lts4 = l4["timestamp"].iloc[-1] if l4 is not None and len(l4) > 0 else None
            lts1 = l1["timestamp"].iloc[-1] if l1 is not None and len(l1) > 0 else None
            ckey = (lts4, lts1)
            if _cache[sym].get("ckey") != ckey:
                df4h_s = (
                    l4.tail(100).reset_index(drop=True)
                    if l4 is not None and len(l4) >= 30
                    else None
                )
                df1h_s = (
                    l1.tail(100).reset_index(drop=True)
                    if l1 is not None and len(l1) >= 30
                    else None
                )
                trend = _htf_trend(df4h_s, df1h_s)
                _cache[sym].update(
                    {"ckey": ckey, "trend": trend, "df4h_s": df4h_s, "df1h_s": df1h_s}
                )
            else:
                trend = _cache[sym]["trend"]
                df4h_s = _cache[sym]["df4h_s"]
                df1h_s = _cache[sym]["df1h_s"]

            if trend == "YATAY":
                active_setups.pop(sym, None)
                continue

            pair_sym = SMT_PAIRS.get(sym)
            df_pair = None
            if pair_sym:
                if pair_sym in pair_data:
                    pp = pair_data[pair_sym]
                    df_pair = pp[pp["timestamp"] <= ts].tail(100).reset_index(drop=True)
                elif pair_sym in data:
                    pp = data[pair_sym]["5m"]
                    df_pair = pp[pp["timestamp"] <= ts].tail(100).reset_index(drop=True)

            df5_s = df5.iloc[max(0, idx - 100) : idx].reset_index(drop=True)
            df15 = data[sym]["15m"]
            df15_s = (
                df15[df15["timestamp"] <= ts].tail(40).reset_index(drop=True)
                if df15 is not None and len(df15[df15["timestamp"] <= ts]) >= 5
                else None
            )

            setup = active_setups.get(sym)

            if setup is not None:
                setup["bars_waited"] += 1
                if setup["bars_waited"] > SETUP_MAX_WAIT or setup["trend"] != trend:
                    active_setups.pop(sym, None)
                    setup = None
                elif not _in_session(ts):
                    continue

            if setup is None:
                sweep_idx = _find_sweep(df5_s, trend)
                if sweep_idx >= 0 and _smt_divergence(
                    df5_s, df_pair, trend, sweep_idx, sym
                ):
                    active_setups[sym] = {
                        "trend": trend,
                        "bars_waited": 0,
                        "df_pair": df_pair,
                        "sweep_idx": sweep_idx,
                    }
                continue

            last_row = df5_s.iloc[-1]
            res = _entry_signal(
                df5_s,
                last_row,
                float(last_row["close"]),
                setup.get("sweep_idx", -1),
                df15_s,
                df4h_s,
                df1h_s,
                trend,
                sym,
            )
            if res is None:
                continue
            active_setups.pop(sym, None)

            # ── SPREAD-ÇOK-GENİŞ (madde 18) — GERÇEK geçmiş spread ile (canlı parite) ──
            # O anki barın gerçek spread'i (MT5 geçmişi, puan), sembolün normal
            # (medyan) spread'inin SPREAD_CAP_MULT katını aşarsa → canlıdaki gibi ATLA.
            # Böylece backtest de haber/rollover gibi anlarda bazı işlemleri atlar.
            if config.SPREAD_CAP_ENABLED:
                _base = spread_baseline.get(sym, 0.0)
                if _base > 0:
                    try:
                        _cur_sp = float(df5.iloc[idx].get("spread", 0.0))
                    except Exception:
                        _cur_sp = 0.0
                    if _cur_sp > _base * config.SPREAD_CAP_MULT:
                        continue  # spread anormal genişti → işlem yok

            spread = SPREAD_TABLE.get(sym, 0.0)
            cp_entry = cp + spread if trend == "LONG" else cp - spread

            atr_val = _atr(df15_s if df15_s is not None else df5_s)
            if atr_val <= 0:
                atr_val = cp * 0.001

            sl, sl_pct, sl_ok = _calc_sl(
                cp_entry, trend, sym, res.get("ob"), atr_val, df15_s
            )
            if not sl_ok:
                continue
            tp = _calc_tp(cp_entry, sl, trend, config.TP_R)

            risk_ratio = min(dyn_risk, pf_max_per) if pf_enabled else dyn_risk
            if pf_enabled:
                floor_buffer = balance - pf_floor
                floor_pct = floor_buffer / pf_start if pf_start > 0 else 1.0
                if floor_pct < 0.03:  # %3 kala → %0.5 risk
                    risk_ratio = min(risk_ratio, 0.005)
                elif floor_pct < 0.04:  # %4 kala → %1 risk
                    risk_ratio = min(risk_ratio, 0.010)
                elif floor_pct < 0.05:  # %5 kala → %1.5 risk
                    risk_ratio = min(risk_ratio, 0.015)
                remaining = pf_day_stop - pf_day_sl
                if remaining <= 0:
                    continue
                riske = min(pf_start * risk_ratio, remaining * 0.90)
                # Evrensel per-trade $ tavan (endeks/forex EŞİT — canlı ile PARİTE)
                riske = min(riske, config.MAX_LOSS_PER_TRADE_USD)
                # madde 43 — endeks per-trade risk tavanı (canlı ile parite)
                if sym in config.INDEX_SYMBOLS:
                    riske = min(riske, config.MAX_LOSS_PER_INDEX_TRADE_USD)
                if riske < pf_start * 0.001:  # $10 taban (canlı ile aynı)
                    continue
                # Worst-case kontrolü (Katman 3) — canlı ile parite
                if config.WORST_CASE_CHECK:
                    worst = riske * config.SLIP_FACTOR
                    if worst > remaining or worst > floor_buffer:
                        continue
            else:
                riske = pf_start * risk_ratio

            # ── GERÇEKÇİ MALİYET: round-trip spread + slippage (R cinsinden) ──
            # Giriş ask / çıkış bid → 1x spread; giriş + çıkış slippage → 2x slip.
            # Dar stop'larda (küçük sl_dist) maliyet R'nin büyük kısmını yer.
            sl_dist_price = abs(cp_entry - sl)
            cost_price = SPREAD_TABLE.get(sym, 0.0) + 2 * SLIPPAGE_TABLE.get(sym, 0.0)
            cost_R = cost_price / sl_dist_price if sl_dist_price > 0 else 0.0

            balance -= riske
            open_trades[sym] = {
                "symbol": sym,
                "yon": trend,
                "giris": cp_entry,
                "sl": sl,
                "tp": tp,
                "riske": riske,
                "cost_R": cost_R,
                "r_dist": sl_dist_price,  # orijinal 1R mesafesi (kâr yönetimi için)
                "partial_done": False,  # kâr yönetimi durumu
                "realized_R": 0.0,
                "sl_pct": round(sl_pct * 100, 3),
                "atr": round(atr_val, 5),
                "mss": res["mss"],
                "entry_type": res["entry_type"],
                "in_zone": res["in_zone"],
                "giris_ts": str(ts),
            }

    wins = [t for t in closed if t["sonuc"] == "TP"]
    losses = [t for t in closed if t["sonuc"] == "SL"]
    total = len(closed)
    wr = round(len(wins) / total * 100, 1) if total else 0.0
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf_val = round(gp / gl, 2) if gl > 0 else 0.0
    tot_pnl = sum(t["pnl"] for t in closed)

    for d in sym_stats.values():
        if d["total"] > 0:
            d["win_rate"] = round(d["wins"] / d["total"] * 100, 1)

    ob_t = [t for t in closed if t.get("entry_type") == "OB_RETEST"]
    ifvg_t = [t for t in closed if t.get("entry_type") == "IFVG"]
    mom_t = [t for t in closed if t.get("entry_type") == "MOMENTUM"]

    prop_result = None
    if pf_enabled:
        net = pf_total_p * pf.get("trader_share", 0.80) + max(
            balance - pf_start, 0
        ) * pf.get("trader_share", 0.80)
        prop_result = {
            "enabled": True,
            "final_balance": round(balance, 2),
            "peak": round(pf_peak, 2),
            "floor": round(pf_floor, 2),
            "min_balance": round(pf_min_bal, 2),
            "max_dd_abs": round(pf_max_dd_seen, 2),
            "max_dd_pct": round(pf_max_dd_seen_pct, 2),
            "total_payouts": round(pf_total_p, 2),
            "payout_count": len(pf_payouts),
            "trader_net": round(net, 2),
            "blown": pf_blown,
            "payout_events": pf_payouts,
        }

    return {
        "months": months,
        "start": str(start_dt.date()),
        "end": str(end_dt.date()),
        "session": f"{SESSION_START:02d}:00-{SESSION_END:02d}:00",
        "session_start": SESSION_START,
        "session_end": SESSION_END,
        "pf_start": pf_start,
        "symbols": list(data.keys()),
        "stats": {
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": wr,
            "profit_factor": pf_val,
            "total_pnl": round(tot_pnl, 2),
            "pnl_pct": round(tot_pnl / pf_start * 100, 1) if pf_enabled else 0.0,
        },
        "symbol_stats": sym_stats,
        "monthly_pnl": {k: round(v, 2) for k, v in sorted(monthly.items())},
        "monthly_trades": {k: v for k, v in sorted(monthly_trades.items())},
        "hour_stats": {
            k: {"count": v["count"], "pnl": round(v["pnl"], 2)}
            for k, v in sorted(hour_stats.items())
        },
        "entry_analysis": {
            "OB_RETEST": {
                "count": len(ob_t),
                "win_rate": (
                    round(
                        sum(1 for t in ob_t if t["sonuc"] == "TP") / len(ob_t) * 100, 1
                    )
                    if ob_t
                    else 0
                ),
                "pnl": round(sum(t["pnl"] for t in ob_t), 2),
            },
            "IFVG": {
                "count": len(ifvg_t),
                "win_rate": (
                    round(
                        sum(1 for t in ifvg_t if t["sonuc"] == "TP")
                        / len(ifvg_t)
                        * 100,
                        1,
                    )
                    if ifvg_t
                    else 0
                ),
                "pnl": round(sum(t["pnl"] for t in ifvg_t), 2),
            },
            "MOMENTUM": {
                "count": len(mom_t),
                "win_rate": (
                    round(
                        sum(1 for t in mom_t if t["sonuc"] == "TP") / len(mom_t) * 100,
                        1,
                    )
                    if mom_t
                    else 0
                ),
                "pnl": round(sum(t["pnl"] for t in mom_t), 2),
            },
        },
        "trades": closed,
        "prop_firm": prop_result,
    }


# ══════════════════════════════════════════════
# RAPOR
# ══════════════════════════════════════════════


def print_report(result, show_trades=False):
    if not result:
        print("Sonuc yok.")
        return

    W = 72
    s = result["stats"]
    pf = result.get("prop_firm")

    def hdr(t):
        print(f"\n  {'─'*W}\n  {t}\n  {'─'*W}")

    def check(label, passed, detay=""):
        icon = "✓ GECTI" if passed else "✗ KALDI"
        print(f"  {icon}  {label:<40} {detay}")

    print(f"\n  {'='*W}")
    print(f"  {'SOFiNARD — FON HESABI BACKTEST RAPORU':^{W}}")
    print(f"  {'='*W}")
    print(f"  Donem : {result['start']} → {result['end']} ({result['months']} ay)")
    print(f"  Sembol: {', '.join(result['symbols'])}")
    print(
        f"  Seans : {SESSION_START:02d}:00 – {SESSION_END:02d}:00 (broker saati)"
        + (f" | Blok saat: {sorted(BLOCKED_HOURS)}" if BLOCKED_HOURS else "")
    )
    pf_baslangic_rapor = result.get("pf_start", 10_000)
    print(f"  Fon   : FundedTraderMarkets | ${pf_baslangic_rapor:,.0f}")
    print(f"  Kurallar: Gunluk DD %{PROP_FIRM['daily_loss_limit']*100:.0f} | "
          f"Max DD %{PROP_FIRM['max_drawdown']*100:.0f} trailing | "
          f"Hedef %{PROP_FIRM['profit_target_first']*100:.0f}")

    hdr("FON KURALLARI — GECTI MI?")

    if pf:
        check(
            f"Hesap patlamadı (Max DD %{PROP_FIRM['max_drawdown']*100:.0f} trailing)",
            not pf["blown"],
            f"Min bakiye: ${pf['min_balance']:,.0f}",
        )
        kar_hedefi_ulasildi = pf["payout_count"] > 0
        pf_baslangic = result.get("pf_start", 10_000)
        ilk_hedef = pf_baslangic * PROP_FIRM['profit_target_first']
        check(
            f"Kar hedefine ulasildi (%{PROP_FIRM['profit_target_first']*100:.0f} = ${ilk_hedef:,.0f})",
            kar_hedefi_ulasildi,
            f"{pf['payout_count']} kez payout",
        )
        toplam_kazanc = pf["total_payouts"] + max(pf["final_balance"] - pf_baslangic, 0)
        genel_karli = toplam_kazanc > 0
        check(
            f"Genel karli (bitis: ${pf['final_balance']:,.0f})",
            genel_karli,
            f"Toplam kazanc: ${toplam_kazanc:+,.0f} (payout+bakiye)",
        )
        check(
            "Profit Factor > 1.5 (saglikli)",
            s["profit_factor"] >= 1.5,
            f"PF: {s['profit_factor']:.2f}",
        )
        check("Kazanma orani > %50", s["win_rate"] >= 50, f"WR: %{s['win_rate']}")
        neg_aylar = [m for m, v in result["monthly_pnl"].items() if v < 0]
        check(
            "Negatif ay sayisi az (max 2)",
            len(neg_aylar) <= 2,
            f"{len(neg_aylar)} negatif ay: {', '.join(neg_aylar) if neg_aylar else 'yok'}",
        )

        tum_gecti = (
            not pf["blown"]
            and kar_hedefi_ulasildi
            and genel_karli
            and s["profit_factor"] >= 1.5
            and s["win_rate"] >= 50
        )
        print(f"\n  {'='*W}")
        if tum_gecti:
            print(f"  >>> SONUC: BU STRATEJI FON HESABINI GECEBİLİR <<<")
        else:
            print(f"  >>> SONUC: DİKKAT — BAZI KURALLAR SAGLANAMADI <<<")
        print(f"  {'='*W}")

    hdr("PERFORMANS ÖZETİ")
    print(
        f"  Toplam islem : {s['total_trades']} (~{s['total_trades']//max(result['months'],1)}/ay)"
    )
    print(f"  Kazanma orani: %{s['win_rate']}  (TP:{s['wins']} | SL:{s['losses']})")
    print(f"  Profit Factor: {s['profit_factor']:.2f}  (1.5+ saglikli, 2.0+ mukemmel)")
    print(f"  Toplam PNL   : ${s['total_pnl']:+,.0f}  (%{s['pnl_pct']:+.1f})")
    if pf:
        print(
            f"  Trader kazanc: ${pf['trader_net']:+,.0f}  ({pf['payout_count']} payout)"
        )

    hdr("RİSK ANALİZİ")
    if pf:
        max_dd = pf.get("max_dd_abs", 0)
        max_dd_pct = pf.get("max_dd_pct", 0)
        dd_limit_pct = PROP_FIRM['max_drawdown'] * 100
        dd_limit = result.get("pf_start", 100_000) * PROP_FIRM['max_drawdown']
        print(
            f"  Max Trailing DD: ${max_dd:,.0f}  (%{max_dd_pct:.1f})  "
            f"→ {'ASILMADI ✓' if max_dd_pct < dd_limit_pct else 'ASILDI ✗'}"
        )
        print(f"  DD Limiti      : ${dd_limit:,.0f} / %{dd_limit_pct:.0f}")
        print(f"  Peak           : ${pf['peak']:,.0f}")
        print(f"  Floor (izin)   : ${pf['floor']:,.0f}")

    hdr("SEMBOL BAZLI PERFORMANS")
    print(f"  {'Sembol':<10} {'İşlem':>5} {'WR':>7} {'PNL':>12}  Yorum")
    print(f"  {'─'*55}")
    for sym, d in sorted(
        result["symbol_stats"].items(), key=lambda x: -x[1].get("pnl", 0)
    ):
        if d["total"] == 0:
            continue
        wr = d.get("win_rate", 0)
        yorum = "✓ iyi" if wr >= 55 else ("~ orta" if wr >= 45 else "✗ zayif")
        print(
            f"  {sym:<10} {d['total']:>5} {f'%{wr:.0f}':>7} ${d['pnl']:>+10,.0f}  {yorum}"
        )

    hdr("GİRİŞ TİPİ ANALİZİ")
    for et, d in result["entry_analysis"].items():
        if d["count"] == 0:
            continue
        yorum = "✓ kullan" if d["win_rate"] >= 53 else "✗ kapat"
        print(
            f"  {et:<12} {d['count']:>3} islem | WR:%{d['win_rate']:>4.1f} | ${d['pnl']:>+10,.0f}  {yorum}"
        )

    hdr("AYLIK PERFORMANS")
    print(f"  {'Ay':<10} {'İşlem':>5} {'TP':>4} {'SL':>4} {'WR':>6}  {'PNL':>12}")
    print(f"  {'─'*50}")
    for m, v in result["monthly_pnl"].items():
        mt = result.get("monthly_trades", {}).get(m, {"tp": 0, "sl": 0})
        tp, sl = mt["tp"], mt["sl"]
        total_m = tp + sl
        wr_m = round(tp / total_m * 100) if total_m > 0 else 0
        isaretli = f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"
        durum = "✓" if v >= 0 else "✗"
        print(
            f"  {durum} {m}  {total_m:>5} {tp:>4} {sl:>4} {f'%{wr_m}':>6}  {isaretli:>12}"
        )

    hdr("SAAT ANALİZİ (broker saati) — En İyi Saatler")
    saat_list = sorted(result["hour_stats"].items(), key=lambda x: -x[1]["pnl"])
    for h, d in saat_list:
        avg = d["pnl"] / d["count"] if d["count"] > 0 else 0
        durum = "✓" if avg > 0 else "✗"
        print(f"  {durum} {h:02d}:00  {d['count']:>3} islem  avg: ${avg:>+8,.0f}/islem")

    if pf and pf.get("payout_events"):
        hdr(f"PAYOUT GEÇMİŞİ ({pf['payout_count']} kez)")
        print(f"  {'#':>3} {'Sembol':<10} {'Tarih':<14} {'Payout':>12}")
        print(f"  {'─'*42}")
        for ev in pf["payout_events"]:
            print(
                f"  {ev['no']:>3} {ev['symbol']:<10} {ev['date']:<14} ${ev['profit']:>+10,.0f}"
            )
        print(f"\n  Toplam payout : ${pf['total_payouts']:,.0f}")
        print(f"  Trader net    : ${pf['trader_net']:,.0f}  (%80 pay)")

    # Günlük P&L tablosu
    if result.get("trades"):
        hdr("GÜNLÜK P&L")
        print(
            f"  {'Tarih':<12} {'İşlem':>5} {'TP':>4} {'SL':>4}  {'Günlük P&L':>12}  {'Bakiye':>12}  Durum"
        )
        print(f"  {'─'*65}")
        gunluk = {}
        pf_baslangic = result.get("pf_start", 10_000)
        # Payout günlerini ve miktarlarını topla
        payout_gunler = {}
        if pf and pf.get("payout_events"):
            for ev in pf["payout_events"]:
                gun = str(ev["date"])[:10]
                payout_gunler[gun] = payout_gunler.get(gun, 0) + ev["profit"]
        for t in result["trades"]:
            gun = str(t.get("cikis_ts", t.get("giris_ts", "")))[:10]
            if gun not in gunluk:
                gunluk[gun] = {"tp": 0, "sl": 0, "pnl": 0.0}
            if t["sonuc"] == "TP":
                gunluk[gun]["tp"] += 1
                gunluk[gun]["pnl"] += t["pnl"]
            else:
                gunluk[gun]["sl"] += 1
                gunluk[gun]["pnl"] += t["pnl"]  # SL pnl zaten negatif kayıtlı
        kumulatif = pf_baslangic
        for gun in sorted(gunluk.keys()):
            d = gunluk[gun]
            toplam = d["tp"] + d["sl"]
            kumulatif += d["pnl"]
            # Payout olduysa bakiye sıfırlanır
            if gun in payout_gunler:
                payout_notu = f"  ← PAYOUT ${payout_gunler[gun]:,.0f}"
                kumulatif = pf_baslangic
            else:
                payout_notu = ""
            isaretli = (
                f"+${d['pnl']:,.0f}" if d["pnl"] >= 0 else f"-${abs(d['pnl']):,.0f}"
            )
            durum = "✓" if d["pnl"] >= 0 else "✗"
            print(
                f"  {durum} {gun}  {toplam:>5} {d['tp']:>4} {d['sl']:>4}  {isaretli:>12}  ${kumulatif:>10,.0f}{payout_notu}"
            )

    if show_trades and result.get("trades"):
        hdr(f"TÜM İŞLEMLER ({len(result['trades'])})")
        for i, t in enumerate(result["trades"], 1):
            print(
                f"  {i:>3} {t['symbol']:<7} {t['yon']:<5} {str(t['giris_ts'])[:16]} "
                f"{t.get('entry_type','?'):<12} {t['sonuc']} ${t['pnl']:>+9,.0f}"
            )

    print(f"\n  {'='*W}\n")


def main():
    parser = argparse.ArgumentParser(description="SOFiNARD SMT Divergence v1")
    parser.add_argument(
        "--months",
        type=int,
        default=11,
        choices=[1, 2, 3, 6, 9, 11, 12, 18, 20, 22, 24],
    )
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--output", default="backtest_smt_results.json")
    parser.add_argument("--show-trades", action="store_true")
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="In-sample + Out-of-sample bolumlu test",
    )
    parser.add_argument(
        "--in-sample-months", type=int, default=None,
        help="In-sample donem uzunlugu (ay). Verilmezse toplamin YARISI (esit IS/OOS)."
    )
    parser.add_argument(
        "--preset",
        choices=["A", "B", "C"],
        default=None,
        help="Hazir ayar: A=guvenli, B=hizli(varsayilan degerler), C=agresif",
    )
    parser.add_argument(
        "--tp",
        type=float,
        default=None,
        help="TP odul carpani (RR). 1.0=1:1, 2.0=1:2. Bu calistirma icin gecerli.",
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=None,
        help="Hesap boyutu (baslangic bakiyesi). Verilmezse .env ACCOUNT_SIZE, o da "
             "yoksa 10000. Ornek: --balance 50000 (canli botla ayni olcek).",
    )
    parser.add_argument(
        "--mode",
        choices=["A", "B", "C", "D"],
        default=None,
        help="Kar yonetimi modeli: A=0.75R'de tumunu kapat (kismi/BE yok), "
             "B=0.5R'de tumunu kapat (3W-1L garanti), C=TP1:1.5 kazanani kostur (kismi+BE), "
             "D=dumduz 1:1 (kismi/BE yok).",
    )

    global INITIAL_BALANCE

    args = parser.parse_args()

    if args.preset:
        config.apply_preset(args.preset)
        print(
            f"  >>> PRESET {args.preset} uygulandi | "
            f"RISK_PCT={config.RISK_PCT} MAX_LOSS=${config.MAX_LOSS_PER_TRADE_USD} "
            f"DAILY={config.DAILY_LOSS_PCT} MAX_OPEN={config.MAX_OPEN}"
        )
    if args.tp is not None:
        config.TP_R = args.tp
        print(f"  >>> TP_R = {config.TP_R} (RR 1:{config.TP_R:g}) uygulandi")

    # ── HESAP BOYUTU (canli bot ile ayni mantik) — preset'ten SONRA, tavani ezer ──
    # Oncelik: --balance > .env ACCOUNT_SIZE > 10000. Risk tavanlari yuzde-bazli
    # olarak bu boyuta gore olceklenir (oran sabit → sonuclar % olarak ayni kalir,
    # sadece $ rakamlar hesabina gore buyur).
    hesap = args.balance or config.ACCOUNT_SIZE or 10000.0
    INITIAL_BALANCE = hesap
    PROP_FIRM["starting_balance"] = hesap
    config.MAX_LOSS_PER_TRADE_USD = round(hesap * config.MAX_LOSS_PCT, 2)
    config.MAX_LOSS_PER_INDEX_TRADE_USD = round(hesap * config.MAX_LOSS_INDEX_PCT, 2)
    print(
        f"  >>> HESAP BOYUTU: ${hesap:,.0f} | islem tavani ${config.MAX_LOSS_PER_TRADE_USD:,.0f} "
        f"| endeks ${config.MAX_LOSS_PER_INDEX_TRADE_USD:,.0f} "
        f"| gunluk ${hesap*config.DAILY_LOSS_PCT:,.0f} | max DD ${hesap*config.MAX_DD_PCT:,.0f}"
    )

    # ── KÂR YÖNETİMİ MODELİ (--mode) — --tp'yi de ezer, en son uygulanır ──
    MODELS = {
        "A": {
            "TP_R": 0.75, "PROFIT_MGMT_ENABLED": False,
            "PARTIAL_CLOSE_PCT": 0.50, "PARTIAL_TP_R": 0.5, "BREAKEVEN_ENABLED": False,
            "baslik": "MODEL A (DUZ 0.75R) — 0.75R'de TUM pozisyonu kapat (kismi/BE YOK)",
            "satir1": "Kazanan: SABIT ~0.75R (~$375) | Kayip: -1R (-$500)",
            "satir2": "3W-1L asla zarar? EVET (3x375=1125>500) | Basa-bas WR ~%57 | Breakeven hatasi YOK",
        },
        "B": {
            "TP_R": 0.5, "PROFIT_MGMT_ENABLED": False,
            "PARTIAL_CLOSE_PCT": 0.50, "PARTIAL_TP_R": 0.5, "BREAKEVEN_ENABLED": False,
            "baslik": "MODEL B (SENIN FIKRIN) — 0.5R'de TUM pozisyonu kapat (kismi/BE YOK)",
            "satir1": "Kazanan: SABIT ~0.5R (~$235) | Kayip: -1R (-$500)",
            "satir2": "3W-1L asla zarar? EVET GARANTI (3x235>500) | Basa-bas WR ~%67 | Kazanani kosturmaz",
        },
        "C": {
            "TP_R": 1.5, "PROFIT_MGMT_ENABLED": True,
            "PARTIAL_CLOSE_PCT": 0.50, "PARTIAL_TP_R": 0.5, "BREAKEVEN_ENABLED": True,
            "baslik": "MODEL C (KAZANANI KOSTUR) — Kismi %50 @0.5R + Breakeven, TP 1:1.5",
            "satir1": "Kazanan: BUYUK ~1.0R ort | Kayip: -1R (-$500)",
            "satir2": "3W-1L asla zarar? HAYIR | Basa-bas WR ~%47 (EN DAYANIKLI) | Kotu gun kirmizi olabilir",
        },
        "D": {
            "TP_R": 1.0, "PROFIT_MGMT_ENABLED": False,
            "PARTIAL_CLOSE_PCT": 0.50, "PARTIAL_TP_R": 0.5, "BREAKEVEN_ENABLED": False,
            "baslik": "MODEL D (DUMDUZ 1:1) — Kismi YOK, Breakeven YOK, saf 1R TP / 1R SL",
            "satir1": "Kazanan: SABIT +1R (~$500) | Kayip: -1R (~$500) — tek tip sonuc",
            "satir2": "Basa-bas WR ~%50 (maliyetle ~%52) | En sade model | WR gercekci (sisme yok)",
        },
    }
    if args.mode:
        m = MODELS[args.mode]
        config.TP_R = m["TP_R"]
        config.PROFIT_MGMT_ENABLED = m["PROFIT_MGMT_ENABLED"]
        config.PARTIAL_CLOSE_PCT = m["PARTIAL_CLOSE_PCT"]
        config.PARTIAL_TP_R = m["PARTIAL_TP_R"]
        config.BREAKEVEN_ENABLED = m["BREAKEVEN_ENABLED"]
        print("  " + "=" * 70)
        print(f"  >>> {m['baslik']}")
        print(f"      {m['satir1']}")
        print(f"      {m['satir2']}")
        print(f"      Ayar: TP_R={config.TP_R} | Kismi={'ACIK %'+str(int(config.PARTIAL_CLOSE_PCT*100))+' @'+str(config.PARTIAL_TP_R)+'R' if config.partial_aktif() else 'KAPALI'} | BE={'ACIK' if config.BREAKEVEN_ENABLED else 'KAPALI'}")
        print("  " + "=" * 70)
    else:
        print(
            f"  >>> MODEL: C (config varsayilani — SECILEN model) | TP_R={config.TP_R} "
            f"Kismi %{int(config.PARTIAL_CLOSE_PCT*100)}@{config.PARTIAL_TP_R}R BE={'ACIK' if config.BREAKEVEN_ENABLED else 'KAPALI'}"
        )
        print("      Farkli model denemek icin: --mode A / B / D")

    symbols = args.symbols or BACKTEST_SYMBOLS
    # Kapatılan sembolleri çıkar (canlı bot ile parite)
    if config.DISABLED_SYMBOLS:
        atlanan = [s for s in symbols if s in config.DISABLED_SYMBOLS]
        symbols = [s for s in symbols if s not in config.DISABLED_SYMBOLS]
        if atlanan:
            print(f"  Kapatilan semboller (DISABLED): {', '.join(atlanan)}")

    if args.walk_forward:
        now = datetime.now(tz=timezone.utc)
        total_months = args.months
        # --in-sample-months verilmezse EŞİT böl (12→6/6, 18→9/9, 20→10/10).
        is_months = args.in_sample_months if args.in_sample_months else total_months // 2
        oos_months = total_months - is_months

        is_end = now - timedelta(days=30 * oos_months)
        is_start = is_end - timedelta(days=30 * is_months)
        oos_start = is_end
        oos_end = now

        W = 72
        print(f"\n{'='*W}")
        print(f"  {'WALK-FORWARD ANALİZİ':^{W}}")
        print(f"{'='*W}")
        print(
            f"  In-Sample  : {is_start.strftime('%Y-%m-%d')} → {is_end.strftime('%Y-%m-%d')} ({is_months} ay)"
        )
        print(
            f"  Out-Sample : {oos_start.strftime('%Y-%m-%d')} → {oos_end.strftime('%Y-%m-%d')} ({oos_months} ay)"
        )

        print(f"\n{'─'*W}")
        print(f"  IN-SAMPLE SONUCU ({is_months} ay — strateji bu donemde geliştirildi)")
        print(f"{'─'*W}")
        r_is = run_backtest(
            symbols, is_months, PROP_FIRM, start_dt=is_start, end_dt=is_end
        )
        print_report(r_is, show_trades=args.show_trades)

        print(f"\n{'─'*W}")
        print(
            f"  OUT-OF-SAMPLE SONUCU ({oos_months} ay — strateji bu dönemi hiç görmedi)"
        )
        print(f"{'─'*W}")
        r_oos = run_backtest(
            symbols, oos_months, PROP_FIRM, start_dt=oos_start, end_dt=oos_end
        )
        print_report(r_oos, show_trades=args.show_trades)

        is_wr = r_is["stats"]["win_rate"]
        oos_wr = r_oos["stats"]["win_rate"]
        is_pf = r_is["stats"]["profit_factor"]
        oos_pf = r_oos["stats"]["profit_factor"]
        print(f"\n{'='*W}")
        print(f"  WALK-FORWARD OZET")
        print(f"  {'─'*40}")
        print(f"  {'':20} {'In-Sample':>12} {'Out-Sample':>12}")
        print(f"  {'WR':20} {f'%{is_wr}':>12} {f'%{oos_wr}':>12}")
        print(f"  {'PF':20} {f'{is_pf:.2f}':>12} {f'{oos_pf:.2f}':>12}")
        print(
            f"  {'Islem':20} {r_is['stats']['total_trades']:>12} {r_oos['stats']['total_trades']:>12}"
        )
        wr_diff = abs(is_wr - oos_wr)
        overfitting = "⚠ ASIRI UYUM RİSKİ" if wr_diff > 10 else "✓ TUTARLI"
        print(f"  {'WR Farki':20} {f'%{wr_diff:.1f}':>12}  {overfitting}")
        print(f"{'='*W}\n")

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": str(datetime.now()),
                    "in_sample": r_is,
                    "out_of_sample": r_oos,
                },
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        print(f"  Kaydedildi: {args.output}\n")

        return

    result = run_backtest(symbols, args.months, PROP_FIRM)
    print_report(result, show_trades=args.show_trades)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(
            {"generated_at": str(datetime.now()), "result": result},
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    print(f"  Kaydedildi: {args.output}\n")

    print_report(result, show_trades=args.show_trades)


if __name__ == "__main__":
    main()
