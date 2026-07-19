#!/usr/bin/env python3
"""
mt5_kontrol.py — BROKER YETENEK KONTROLÜ (sadece OKUR, emir GÖNDERMEZ)

NE İŞE YARAR:
  Canlı işleme geçmeden ÖNCE, broker'ın (demo/gerçek/PROP) her sembolde neye izin
  verdiğini kesin gösterir. "MT5 sıkıntı çıkarır mı?" sorusunun cevabı.

NASIL ÇALIŞTIRILIR:
  python mt5_kontrol.py                 # botun sembol listesini kontrol et
  python mt5_kontrol.py --hepsi         # BROKER'DAKİ TÜM sembolleri listele
                                        #   (FTM gibi prop'ta isimleri keşfetmek için)
  python mt5_kontrol.py --ara SPX NAS US30 GER XAU
                                        # anahtar kelimeyle sembol ara (FTM isim eşleştirme)

FARKLI BROKER / PROP (FTM) İÇİN:
  Prop firmalar sembol isimlerini farklı yazar (US500 -> SPX500 / US500.cash,
  USTEC -> NAS100, DE40 -> GER40 ...). Önce '--hepsi' veya '--ara' ile o broker'daki
  GERÇEK isimleri bul; sonra botun sembol listesini o isimlere göre güncelleriz.

OKUNAN DEĞERLER:
  - trade_mode      : İşleme açık mı? (FULL = tam serbest, CLOSEONLY/DISABLED = sorun)
  - stops_level     : SL/TP fiyata en az kaç 'point' uzakta olmalı (min mesafe)
  - freeze_level    : Fiyata bu kadar yakınken emir DEĞİŞTİRİLEMEZ
  - volume_min/step : En küçük lot ve adım
  - filling_modes   : Emir doldurma tipi (FOK/IOC/RETURN) — bot bunu otomatik seçer
"""

import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("HATA: MetaTrader5 paketi yok. pip install MetaTrader5")
    sys.exit(1)

# Bot ile aynı semboller (MetaQuotes-Demo isimleri — prop'ta farklı olabilir)
SYMBOLS = [
    "US500", "US100", "US30", "GBPUSD", "GBPJPY",
    "EURJPY", "UK100", "XAUUSD", "USDJPY", "GER40",
]

_TRADE_MODE = {
    0: "DISABLED (işlem YOK!)",
    1: "LONGONLY (sadece alış)",
    2: "SHORTONLY (sadece satış)",
    3: "CLOSEONLY (sadece kapatma!)",
    4: "FULL (tam serbest) ✓",
}


def _fill_str(fm: int) -> str:
    modes = []
    if fm & 1:
        modes.append("FOK")
    if fm & 2:
        modes.append("IOC")
    modes.append("RETURN")  # her zaman var
    return "/".join(modes)


def _mode_kisa(tm: int) -> str:
    return {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY",
            3: "CLOSEONLY", 4: "FULL"}.get(tm, f"?{tm}")


def _satir_bas():
    print(f"\n  {'SEMBOL':<16} {'DURUM':<12} {'MinStop':>8} {'Freeze':>7} "
          f"{'MinLot':>7} {'Adım':>6}  {'Dolum'}")
    print(f"  {'-'*16} {'-'*12} {'-'*8} {'-'*7} {'-'*7} {'-'*6}  {'-'*12}")


def _yaz(sym: str, si) -> None:
    print(f"  {sym:<16} {_mode_kisa(si.trade_mode):<12} {si.trade_stops_level:>8} "
          f"{si.trade_freeze_level:>7} {si.volume_min:>7g} {si.volume_step:>6g}  "
          f"{_fill_str(si.filling_mode)}")


def _hepsini_listele():
    """Broker'daki TÜM sembolleri trade_mode ile döker (FTM isim keşfi)."""
    syms = mt5.symbols_get()
    if not syms:
        print("  Sembol listesi alınamadı.")
        return
    print(f"\n  BROKER'DAKİ TÜM SEMBOLLER ({len(syms)} adet) — sadece FULL olanlar işlenebilir:")
    _satir_bas()
    for s in sorted(syms, key=lambda x: x.name):
        print(f"  {s.name:<16} {_mode_kisa(s.trade_mode):<12}")


def _ara(anahtarlar):
    """Anahtar kelimelerle sembol ara (FTM'de US500->SPX500 gibi isimleri bul)."""
    syms = mt5.symbols_get()
    if not syms:
        print("  Sembol listesi alınamadı.")
        return
    anahtarlar = [a.upper() for a in anahtarlar]
    bulunan = [s for s in syms if any(a in s.name.upper() for a in anahtarlar)]
    print(f"\n  ARAMA {anahtarlar} → {len(bulunan)} eşleşme:")
    _satir_bas()
    for s in sorted(bulunan, key=lambda x: x.name):
        si = mt5.symbol_info(s.name)
        if si:
            _yaz(s.name, si)


def main():
    args = [a for a in sys.argv[1:]]

    if not mt5.initialize():
        print(f"HATA: MT5 başlatılamadı: {mt5.last_error()}")
        print("MT5 terminali açık ve giriş yapılmış olmalı.")
        sys.exit(1)

    info = mt5.account_info()
    if info is None:
        print("HATA: Hesap bilgisi alınamadı.")
        sys.exit(1)

    print("=" * 78)
    print(f"  HESAP: login={info.login} | {info.server} | {info.currency} | "
          f"Bakiye ${info.balance:,.2f}")
    srv = str(info.server).lower()
    tur = "DEMO" if "demo" in srv else "GERÇEK/PROP (dikkat!)"
    print(f"  Tür: {tur}")
    print("=" * 78)

    # --hepsi: broker'daki tüm sembolleri listele (isim keşfi)
    if "--hepsi" in args:
        _hepsini_listele()
        mt5.shutdown()
        return
    # --ara KELIME...: anahtar kelimeyle sembol ara
    if "--ara" in args:
        idx = args.index("--ara")
        anahtarlar = args[idx + 1:]
        if not anahtarlar:
            anahtarlar = ["SPX", "US500", "NAS", "US30", "GER", "DE40",
                          "UK100", "XAU", "GBP", "JPY", "EUR"]
        _ara(anahtarlar)
        mt5.shutdown()
        return
    print(f"\n  {'SEMBOL':<9} {'DURUM':<22} {'MinStop':>8} {'Freeze':>7} "
          f"{'MinLot':>7} {'Adım':>6}  {'Dolum'}")
    print(f"  {'-'*9} {'-'*22} {'-'*8} {'-'*7} {'-'*7} {'-'*6}  {'-'*12}")

    sorunlu = []
    for sym in SYMBOLS:
        si = mt5.symbol_info(sym)
        if si is None:
            # 'm' sonekli varyantı dene (bazı broker'lar XAUUSDm kullanır)
            alt = sym + "m"
            si = mt5.symbol_info(alt)
            if si is None:
                print(f"  {sym:<9} BULUNAMADI (broker bu sembolü sunmuyor)")
                sorunlu.append(f"{sym}: sembol yok")
                continue
            sym = alt

        if not si.visible:
            mt5.symbol_select(sym, True)
            si = mt5.symbol_info(sym)

        mode = _TRADE_MODE.get(si.trade_mode, f"? ({si.trade_mode})")
        point = si.point or 0.00001
        min_stop = si.trade_stops_level          # point cinsinden
        freeze = si.trade_freeze_level
        min_stop_fiyat = min_stop * point        # fiyat cinsinden

        print(f"  {sym:<9} {mode:<22} {min_stop:>8} {freeze:>7} "
              f"{si.volume_min:>7g} {si.volume_step:>6g}  {_fill_str(si.filling_mode)}")

        if si.trade_mode != 4:
            sorunlu.append(f"{sym}: trade_mode={mode}")
        # 0.75R TP kabul edilir mi? min_stop çok büyükse dar stop'larda sorun olabilir
        if min_stop_fiyat > 0 and si.point:
            pass  # bilgi amaçlı; gerçek kontrol işlem anında yapılıyor

    print("\n" + "=" * 78)
    if sorunlu:
        print("  ⚠️  DİKKAT — şu sembollerde broker kısıtı var:")
        for s in sorunlu:
            print(f"      - {s}")
    else:
        print("  ✓ TÜM SEMBOLLER 'FULL' — broker açış/kapanış/TP'ye izin veriyor.")
    print("\n  KARAR:")
    print("    - Hepsi FULL ise: Model A (0.75R tam kapatma) hiçbir broker kısıtına")
    print("      takılmaz — kısmi kapama/SL taşıma yok, en basit emir tipi.")
    print("    - MinStop (stops_level) değeri: TP/SL fiyata bu kadar 'point' uzak olmalı.")
    print("      0.75R hedef bu mesafeden büyükse sorun olmaz (genelde olmaz).")
    print("    - trade_mode FULL değilse o sembolü DISABLED_SYMBOLS'e ekle.")
    print("=" * 78)

    mt5.shutdown()


if __name__ == "__main__":
    main()
