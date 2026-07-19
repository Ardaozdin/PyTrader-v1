#!/usr/bin/env python3
"""
run_ablation.py — Filtre Ablation Testi

NE YAPAR:
  Her filtreyi tek tek kapatır, sistemin nasıl tepki verdiğini ölçer.
  Sonunda karar tablosu üretir: hangi filtre değerli, hangisi gereksiz.

NASIL ÇALIŞIR:
  1. Veriyi MT5'ten BİR KERE çeker (cache)
  2. 11 senaryoyu sırayla çalıştırır:
     - 1 baseline (tüm filtreler aktif)
     - 10 ablation (her seferinde bir filtre kapalı)
  3. Sonuçları yan yana koyup karar tablosu basar

KULLANIM:
  python run_ablation.py --months 6
  python run_ablation.py --months 9 --symbols GBPUSD USDJPY
  python run_ablation.py --months 6 --output ablation_v7.json

TEST EDILEN FILTRELER:
  1. HTF Trend          (4H+1H trend zorunluluğu)
  2. Premium/Discount   (LONG ancak DISCOUNT, SHORT ancak PREMIUM)
  3. HTF Zone           (4H/1H OB+FVG dokunma zorunluluğu)
  4. Sweep              (likidite alımı zorunluluğu)
  5. MSS/CISD           (yapı kırılması zorunluluğu)
  6. Displacement       (güçlü itici mum zorunluluğu)
  7. OB Retest          (sweep mumuna fiyat dönüşü)
  8. Günlük Bias        (günün ilk 3 saatinin yönü filtresi)
  9. Session            (11-19 UTC dışı yok)
  10. Skor Eşiği        (skor < 55 reddi)
"""

import argparse
import copy
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# Backtest modülünü import et
try:
    import backtest_smc as bt
except ImportError:
    print("HATA: backtest_smc.py aynı klasörde olmalı!")
    sys.exit(1)


# ══════════════════════════════════════════════
# ABLATION SENARYOLARI
# ══════════════════════════════════════════════
#
# Her senaryo bir CONFIG değişikliğidir. "patch" anahtarı,
# baseline CONFIG üzerinden hangi alanları override edeceğini söyler.
# Bazı filtreler config patch ile kapanır, bazıları için kod patch lazım.
# Kod patch gerekenler için "monkey_patch" fonksiyonu kullanılır.

ABLATION_SCENARIOS = [
    {
        "name": "BASELINE",
        "desc": "Tüm filtreler aktif (referans)",
        "patch": {},
        "monkey_patch": None,
    },
    {
        "name": "no_htf_trend",
        "desc": "HTF Trend (4H+1H) kapalı",
        "patch": {"min_htf_guc": 0},  # 0 = trend filtresini bypass et
        "monkey_patch": "disable_htf_trend",
    },
    {
        "name": "no_premium_discount",
        "desc": "Premium/Discount filtresi kapalı",
        "patch": {},
        "monkey_patch": "disable_premium_discount",
    },
    {
        "name": "no_htf_zone",
        "desc": "HTF Zone (4H/1H OB+FVG) zorunluluğu kapalı",
        "patch": {"require_htf_zone": False},
        "monkey_patch": None,
    },
    {
        "name": "no_sweep",
        "desc": "Sweep zorunluluğu kapalı",
        "patch": {},
        "monkey_patch": "disable_sweep",
    },
    {
        "name": "no_mss_cisd",
        "desc": "MSS/CISD yapı kırılması zorunluluğu kapalı",
        "patch": {},
        "monkey_patch": "disable_mss_cisd",
    },
    {
        "name": "no_displacement",
        "desc": "Displacement (güçlü itici mum) kapalı",
        "patch": {},
        "monkey_patch": "disable_displacement",
    },
    {
        "name": "no_ob_retest",
        "desc": "OB Retest (sweep mumuna dönüş) kapalı",
        "patch": {},
        "monkey_patch": "disable_ob_retest",
    },
    {
        "name": "no_daily_bias",
        "desc": "Günlük bias filtresi kapalı",
        "patch": {},
        "monkey_patch": "disable_daily_bias",
    },
    {
        "name": "no_session",
        "desc": "Session filtresi kapalı (24 saat)",
        "patch": {"session_filter": False},
        "monkey_patch": None,
    },
    {
        "name": "no_score_threshold",
        "desc": "Skor eşiği kapalı (skor=1 bile geçerli)",
        "patch": {"score_threshold": 1, "makro_min": 1, "entry_min": 1},
        "monkey_patch": None,
    },
]


# ══════════════════════════════════════════════
# MONKEY PATCH'LER
# ══════════════════════════════════════════════
# Bazı filtreler config ile kapanmaz, fonksiyonları geçici olarak
# bypass etmek gerekir. Bu fonksiyonlar orijinal halini saklar,
# bypass eden versiyonu yerine koyar. Senaryo bittikten sonra geri alınır.

_originals: Dict = {}


def _save_original(name: str, fn):
    if name not in _originals:
        _originals[name] = fn


def apply_monkey_patch(patch_name: Optional[str]):
    """Bypass fonksiyonunu uygula."""
    if patch_name is None:
        return

    if patch_name == "disable_htf_trend":
        _save_original("get_combined_trend", bt.get_combined_trend)
        # Her zaman LONG döndür güc=2 (filtre yokmuş gibi)
        # Not: Bu filtreyi gerçek anlamda kapatmak için trend'i her zaman geçerli
        # saymak gerekir. LONG seçimi keyfi ama tutarlı.
        bt.get_combined_trend = lambda df_4h, df_1h: ("LONG", 2)

    elif patch_name == "disable_premium_discount":
        _save_original("_get_premium_discount", bt._get_premium_discount)

        # Hep DISCOUNT (LONG için) ya da PREMIUM (SHORT için) — yön tarafından
        # belirlenir, sinyal yön ile eşleşir
        def fake_pd(candles, cp, direction):
            zone = "DISCOUNT" if direction == "LONG" else "PREMIUM"
            return zone, 0.5, True, cp

        bt._get_premium_discount = fake_pd

    elif patch_name == "disable_sweep":
        _save_original("_find_recent_sweep", bt._find_recent_sweep)

        # Her zaman geçerli sweep var de (idx=0 döndür, son barlardan)
        def fake_sweep(candles, direction, window=30):
            return max(0, len(candles) - 5)  # geçerli ama yakın bir idx

        bt._find_recent_sweep = fake_sweep

    elif patch_name == "disable_mss_cisd":
        _save_original("_check_mss", bt._check_mss)
        _save_original("_check_cisd", bt._check_cisd)
        bt._check_mss = lambda candles, direction, cfg: True
        bt._check_cisd = lambda candles, direction, cfg: True

    elif patch_name == "disable_displacement":
        _save_original("_check_displacement", bt._check_displacement)
        bt._check_displacement = lambda candles, direction, avg_vol: True

    elif patch_name == "disable_ob_retest":
        _save_original("_check_ob_retest", bt._check_ob_retest)
        bt._check_ob_retest = lambda last_candle, ob, direction, cfg: True

    elif patch_name == "disable_daily_bias":
        _save_original("_get_gunluk_bias", bt._get_gunluk_bias)
        # YATAY = filtre devre dışı (yatayken her yön geçer)
        bt._get_gunluk_bias = lambda df_1h: "YATAY"

    else:
        print(f"  ⚠️ Bilinmeyen monkey patch: {patch_name}")


def restore_originals():
    """Tüm monkey patch'leri geri al — temiz state."""
    for name, fn in _originals.items():
        setattr(bt, name, fn)


# ══════════════════════════════════════════════
# VERİ ÖNBELLEK — TEK SEFER ÇEK, ÇOK KEZ KULLAN
# ══════════════════════════════════════════════

_data_cache: Dict = {}


def fetch_all_data(symbols: List[str], months: int, cfg: dict):
    """
    Tüm verileri MT5'ten bir kez çeker, _data_cache'e koyar.
    Sonraki run_backtest çağrılarında bu cache kullanılır.
    """
    global _data_cache
    if _data_cache:
        print("  Cache zaten dolu, veri çekme atlandı.")
        return

    print(f"\n  Veri çekme başlıyor ({months} ay, {len(symbols)} sembol)...")
    start_time = time.time()

    end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=30 * months)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)
    warmup_ms = start_ms - int(90 * 24 * 3600 * 1000)

    entry_tf = cfg["entry_tf"]
    struct_tf = cfg["struct_tf"]
    use_struct = entry_tf != struct_tf
    tf1 = cfg["trend_tf1"]
    tf2 = cfg["trend_tf2"]

    for sym in symbols:
        print(f"    {sym}...", end=" ", flush=True)
        df_e = bt.fetch_klines_mt5(sym, entry_tf, start_ms, end_ms)
        df_s = (
            bt.fetch_klines_mt5(sym, struct_tf, warmup_ms, end_ms)
            if use_struct
            else None
        )
        df_4h = bt.fetch_klines_mt5(sym, tf1, warmup_ms, end_ms)
        df_1h = bt.fetch_klines_mt5(sym, tf2, warmup_ms, end_ms)

        if df_e is None or df_4h is None or df_1h is None:
            print("HATA")
            continue
        if use_struct and df_s is None:
            print("HATA (struct)")
            continue
        if len(df_e) < 100:
            print(f"HATA (yetersiz: {len(df_e)})")
            continue

        print(f"OK ({len(df_e)} bar)")
        _data_cache[sym] = {"entry": df_e, "struct": df_s, "4h": df_4h, "1h": df_1h}

    elapsed = time.time() - start_time
    print(f"  Veri çekme tamam: {len(_data_cache)} sembol, {elapsed:.1f} saniye\n")


# ══════════════════════════════════════════════
# BACKTEST ÇALIŞTIRMA — CACHE KULLANARAK
# ══════════════════════════════════════════════


def run_with_cache(symbols: List[str], months: int, cfg: dict) -> dict:
    """
    backtest_smc.run_backtest'i çağırır ama veri çekme yerine cache kullanır.
    Bunun için bt.fetch_klines_mt5'i geçici olarak override ediyoruz.
    """
    original_fetch = bt.fetch_klines_mt5

    def cached_fetch(symbol, interval, start_ms, end_ms):
        if symbol not in _data_cache:
            return None
        d = _data_cache[symbol]
        tf_map = {
            cfg["entry_tf"]: "entry",
            cfg["struct_tf"]: "struct",
            cfg["trend_tf1"]: "4h",
            cfg["trend_tf2"]: "1h",
        }
        key = tf_map.get(interval)
        if key is None or d.get(key) is None:
            return None
        # Tarih aralığına göre filtrele
        df = d[key]
        dt_from = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        dt_to = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
        return df[
            (df["timestamp"] >= dt_from) & (df["timestamp"] <= dt_to)
        ].reset_index(drop=True)

    bt.fetch_klines_mt5 = cached_fetch
    try:
        result = bt.run_backtest(symbols, months, cfg)
    finally:
        bt.fetch_klines_mt5 = original_fetch
    return result


# ══════════════════════════════════════════════
# KARAR MOTORU
# ══════════════════════════════════════════════


def classify_filter(baseline: dict, scenario: dict) -> str:
    """
    Bir filtreyi kapatınca ne olduğuna göre karar üret.

    Mantık:
      - PNL'e ve işlem sayısına bak
      - Baseline'a göre değişimi yorumla
    """
    if not scenario or not scenario.get("summary"):
        return "VERI_YOK"

    b = baseline["summary"]
    s = scenario["summary"]

    bp = b.get("total_pnl", 0)
    sp = s.get("total_pnl", 0)
    bt_count = b.get("total_trades", 0)
    st_count = s.get("total_trades", 0)

    if bt_count == 0:
        return "BASELINE_BOS"
    if st_count == 0:
        return "ISLEM_YOK"

    pnl_change = sp - bp
    pnl_pct_change = (pnl_change / abs(bp) * 100) if bp != 0 else 0
    trade_increase_pct = (st_count - bt_count) / bt_count * 100

    # Karar mantığı
    if sp < 0 and bp > 0:
        return "KRITIK ✓ (kapatınca sistem zarara giriyor)"

    if pnl_pct_change < -30:
        return "FAYDALI ✓ (PNL %30+ düştü)"

    if pnl_pct_change < -15:
        return "ORTA (PNL %15+ düştü)"

    if pnl_pct_change > 15 and trade_increase_pct < 50:
        return "ZARARLI ✗ (kapatınca PNL arttı, sil!)"

    if abs(pnl_pct_change) < 10 and trade_increase_pct > 100:
        return "GEREKSIZ ✗ (PNL benzer, işlem 2x+ arttı)"

    if abs(pnl_pct_change) < 10:
        return "NÖTR (anlamlı fark yok)"

    return "BELİRSİZ"


# ══════════════════════════════════════════════
# RAPOR
# ══════════════════════════════════════════════


def print_summary_table(results: List[dict]):
    """Tüm senaryoları yan yana koyup karar tablosu bas."""

    print("\n" + "=" * 110)
    print(f"  {'ABLATION KARAR TABLOSU':^108}")
    print("=" * 110)

    # Header
    print(
        f"\n  {'SENARYO':<25} {'ISLEM':>6} {'WR%':>6} {'PNL$':>11} "
        f"{'PF':>6} {'DD$':>9} {'Δ PNL%':>8}  KARAR"
    )
    print(f"  {'-'*25} {'-'*6} {'-'*6} {'-'*11} {'-'*6} {'-'*9} {'-'*8}  {'-'*30}")

    baseline = results[0] if results else None
    if not baseline:
        print("  Veri yok")
        return

    bs = baseline.get("summary", {})
    bp = bs.get("total_pnl", 0)

    for i, r in enumerate(results):
        if not r or not r.get("summary"):
            print(f"  {ABLATION_SCENARIOS[i]['name']:<25}  HATA / VERI YOK")
            continue

        s = r["summary"]
        sn = ABLATION_SCENARIOS[i]
        delta = (s.get("total_pnl", 0) - bp) / abs(bp) * 100 if bp != 0 else 0
        delta_str = f"{delta:+.0f}%" if i > 0 else "  baz"

        karar = classify_filter(baseline, r) if i > 0 else "(referans)"

        print(
            f"  {sn['name']:<25} {s.get('total_trades', 0):>6} "
            f"{s.get('win_rate', 0):>5.1f}% "
            f"${s.get('total_pnl', 0):>+9,.0f} "
            f"{s.get('profit_factor', 0):>6.2f} "
            f"${s.get('max_drawdown', 0):>7,.0f} "
            f"{delta_str:>8}  {karar}"
        )

    print("\n  " + "=" * 108)
    print("\n  YORUMLAMA:")
    print("    KRITIK ✓     → Filtre olmadan sistem çöküyor, MUTLAKA TUT")
    print("    FAYDALI ✓    → PNL büyük düşüyor, TUT")
    print("    ORTA         → Bir miktar katkı sağlıyor, TUT")
    print("    NÖTR         → Anlamlı fark yok, kaldırmaya değer")
    print("    GEREKSIZ ✗   → Sadece işlem sayısını kısıtlıyor, KALDIR")
    print("    ZARARLI ✗    → Kapatınca PNL artıyor, KESİNLİKLE KALDIR")
    print()


def print_detail_table(results: List[dict]):
    """Daha detaylı sembol bazlı karşılaştırma."""
    print("\n  SEMBOL BAZLI DEĞİŞİM (BASELINE vs her senaryo)")
    print("  " + "=" * 108)

    baseline = results[0] if results else None
    if not baseline:
        return

    bs_syms = baseline.get("symbol_stats", {})

    for i, r in enumerate(results[1:], 1):
        if not r or not r.get("symbol_stats"):
            continue
        sn = ABLATION_SCENARIOS[i]
        print(f"\n  {sn['name']} — {sn['desc']}")
        print(f"    {'Sembol':<10} {'Δ İşlem':>10} {'Δ WR%':>8} {'Δ PNL$':>12}")
        for sym in bs_syms:
            b = bs_syms[sym]
            s = r["symbol_stats"].get(sym, {})
            d_trade = s.get("total", 0) - b["total"]
            d_wr = s.get("win_rate", 0) - b.get("win_rate", 0)
            d_pnl = s.get("pnl", 0) - b["pnl"]
            print(f"    {sym:<10} {d_trade:>+10} {d_wr:>+7.1f}% ${d_pnl:>+10,.0f}")


# ══════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Ablation Testi — filtre faydası ölçümü"
    )
    parser.add_argument("--months", type=int, default=6, choices=[1, 2, 3, 6, 9, 12])
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--output", default="ablation_results.json")
    parser.add_argument(
        "--detail", action="store_true", help="Sembol bazlı değişim tablosu da bas"
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=None,
        help="Sadece belirli senaryoları çalıştır (örn: BASELINE no_session)",
    )
    args = parser.parse_args()

    cfg = bt.CONFIG.copy()
    symbols = args.symbols or cfg["symbols_default"]

    # Filtre senaryoları
    scenarios_to_run = ABLATION_SCENARIOS
    if args.scenarios:
        scenarios_to_run = [
            s for s in ABLATION_SCENARIOS if s["name"] in args.scenarios
        ]
        if not scenarios_to_run:
            print(f"HATA: Belirtilen senaryolar bulunamadı: {args.scenarios}")
            sys.exit(1)
        # BASELINE her zaman olsun (referans için)
        if not any(s["name"] == "BASELINE" for s in scenarios_to_run):
            scenarios_to_run = [ABLATION_SCENARIOS[0]] + scenarios_to_run

    print(f"\n{'=' * 70}")
    print(f"  ABLATION TESTİ — {args.months} AY")
    print(f"{'=' * 70}")
    print(f"  Semboller: {', '.join(symbols)}")
    print(f"  Senaryo sayısı: {len(scenarios_to_run)}")
    print(
        f"  Tahmini süre: {len(scenarios_to_run) * 1.5:.0f} dakika "
        f"(veri çekme + her senaryo ~1.5dk)"
    )

    # 1. Veriyi bir kere çek
    fetch_all_data(symbols, args.months, cfg)
    if not _data_cache:
        print("HATA: Veri çekilemedi, çıkılıyor.")
        sys.exit(1)

    # 2. Senaryoları sırayla çalıştır
    all_results = []
    total_start = time.time()

    for i, scenario in enumerate(scenarios_to_run, 1):
        print(
            f"\n  [{i}/{len(scenarios_to_run)}] {scenario['name']} — {scenario['desc']}"
        )
        scenario_start = time.time()

        # Config patch uygula
        scenario_cfg = copy.deepcopy(cfg)
        scenario_cfg.update(scenario.get("patch", {}))

        # Monkey patch uygula
        try:
            apply_monkey_patch(scenario.get("monkey_patch"))

            # Backtest çalıştır (cache'den)
            # stdout'u sustur, sadece sonuç al
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = run_with_cache(symbols, args.months, scenario_cfg)

            elapsed = time.time() - scenario_start

            if result and result.get("summary"):
                s = result["summary"]
                print(
                    f"      ✓ {s.get('total_trades', 0)} işlem, "
                    f"WR %{s.get('win_rate', 0):.1f}, "
                    f"PNL ${s.get('total_pnl', 0):+,.0f}, "
                    f"PF {s.get('profit_factor', 0):.2f}  "
                    f"({elapsed:.1f}s)"
                )
            else:
                print(f"      ✗ Sonuç boş ({elapsed:.1f}s)")

            all_results.append(result)

        except Exception as e:
            print(f"      ✗ HATA: {e}")
            import traceback

            traceback.print_exc()
            all_results.append(None)
        finally:
            # Monkey patch'leri geri al
            restore_originals()

    total_elapsed = time.time() - total_start
    print(f"\n  Toplam süre: {total_elapsed/60:.1f} dakika")

    # 3. Karar tablosu
    print_summary_table(all_results)

    if args.detail:
        print_detail_table(all_results)

    # 4. JSON kaydet
    output_data = {
        "generated_at": str(datetime.now()),
        "months": args.months,
        "symbols": symbols,
        "scenarios": [
            {
                "name": ABLATION_SCENARIOS[i]["name"],
                "desc": ABLATION_SCENARIOS[i]["desc"],
                "summary": r.get("summary") if r else None,
                "symbol_stats": r.get("symbol_stats") if r else None,
                "monthly_pnl": r.get("monthly_pnl") if r else None,
                "score_analysis": r.get("score_analysis") if r else None,
            }
            for i, r in enumerate(all_results)
        ],
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n  Detay kaydedildi: {args.output}\n")


if __name__ == "__main__":
    main()
