#!/usr/bin/env python3
"""
notifier.py — Telegram bildirim & onay sistemi

- NOTIFY modu (varsayılan): bot TAM OTOMATİK çalışır, her olayı gruba bildirir.
- CONFIRM modu (opsiyonel): işlem açmadan önce [Onayla]/[İptal] sorar; süre
  içinde onaylanmazsa AÇMAZ (güvenli varsayılan).

Telegram erişilemezse bot ÇALIŞMAYA DEVAM EDER — tüm çağrılar try/except.
Sadece 'requests' kullanır (ek bağımlılık yok).
"""

import time

import config

try:
    import requests
except ImportError:
    requests = None

_API = "https://api.telegram.org/bot{token}/{method}"


def _enabled():
    return config.TELEGRAM_ENABLED and requests is not None


def _post(method: str, payload: dict, timeout: int = 10):
    if not _enabled():
        return None
    try:
        url = _API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
        r = requests.post(url, json=payload, timeout=timeout)
        return r.json() if r.ok else None
    except Exception:
        return None


def send(text: str):
    """Basit mesaj gönder (NOTIFY). Hata olsa bile sessiz geç."""
    _post("sendMessage", {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def durum() -> str:
    """Telegram neden çalışıyor/çalışmıyor — tek satır teşhis (başlangıçta loglanır)."""
    if requests is None:
        return "requests kütüphanesi yok (pip install requests)"
    if not config.TELEGRAM_BOT_TOKEN:
        return ".env'de TELEGRAM_BOT_TOKEN tanımlı DEĞİL"
    if not config.TELEGRAM_CHAT_ID:
        return ".env'de TELEGRAM_CHAT_ID tanımlı DEĞİL (chatid_bul.py ile bulabilirsin)"
    if not config.TELEGRAM_ENABLED:
        return "TELEGRAM_ENABLED False (token veya chat_id eksik)"
    return "AÇIK"


def self_test():
    """(ok, sebep) döndürür. Gerçekten bir test mesajı gönderip Telegram'ın
    kabul edip etmediğini doğrular — 'gitmiyor' sorununun kesin teşhisi."""
    d = durum()
    if d != "AÇIK":
        return False, d
    try:
        url = _API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendMessage")
        r = requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": "✅ <b>Telegram testi</b> — bot bildirimleri çalışıyor.",
            "parse_mode": "HTML",
        }, timeout=10)
        try:
            j = r.json()
        except Exception:
            return False, f"HTTP {r.status_code} (JSON yok)"
        if r.ok and j.get("ok"):
            return True, "test mesajı gönderildi"
        # Telegram'ın döndürdüğü gerçek hata sebebi (yanlış token/chat_id vb.)
        return False, j.get("description", f"HTTP {r.status_code}")
    except Exception as e:
        return False, f"bağlantı hatası: {e}"


# ── Olay şablonları ─────────────────────────────

def setup(symbol, yon, detay=""):
    send(f"🔍 <b>SETUP</b> | {symbol} {yon} | {detay} | giriş bekleniyor")


def trade_opened(ot: dict):
    # .get() ile savunmacı — eksik key bir KeyError ile işlem akışını bozmasın.
    d = ot
    try:
        if config.partial_aktif():
            kar_yon = (f"Kısmi: +{config.PARTIAL_TP_R}R'de "
                       f"%{int(config.PARTIAL_CLOSE_PCT*100)} kapanır → breakeven")
        else:
            kar_yon = f"Hepsi +{config.TP_R}R'de kapanır (kısmi/breakeven yok)"
        send(
            f"🟢 <b>İŞLEM AÇILDI</b> — {d.get('symbol','?')} {d.get('yon','?')} "
            f"({d.get('entry_type','?')})\n"
            f"Giriş: {d.get('giris',0):.5f} | SL: {d.get('sl',0):.5f}\n"
            f"TP: {d.get('tp',0):.5f}  |  {kar_yon}\n"
            f"Lot: {d.get('lot',0):.3f} | Risk: ${d.get('riske',0):.2f} "
            f"(%{d.get('risk_pct',0):.1f}) | Worst-case: ${d.get('worst_case',0):.0f}\n"
            f"Bakiye: ${d.get('balance_at_open',0):,.0f}"
        )
    except Exception:
        pass


def partial_be(symbol, pnl, kalan_pct, be_ok=True, be_price=None):
    if be_ok:
        be_str = (f"SL → breakeven ({be_price:.5f}) ✓" if be_price is not None
                  else "SL → breakeven ✓")
    else:
        be_str = "⚠️ SL breakeven'a TAŞINAMADI — orijinal stop devrede"
    send(
        f"🟡 <b>{symbol}</b> | +{config.PARTIAL_TP_R}R'de "
        f"%{int(config.PARTIAL_CLOSE_PCT*100)} kapandı (+${pnl:.2f}) | "
        f"{be_str} | kalan %{int(kalan_pct*100)} takipte"
    )


def trade_closed(symbol, yon, sonuc, pnl, bakiye, gun_sl_total, gun_limit,
                 slippage_R=None):
    ikon = "✅" if sonuc == "TP" else "🔴"
    slip = f" | Kayma: {slippage_R:.2f}R" if slippage_R is not None else ""
    isaret = "+" if pnl >= 0 else "-"
    send(
        f"{ikon} <b>{symbol} {yon}</b> | {sonuc} | PNL: {isaret}${abs(pnl):.2f}"
        f"{slip}\nBakiye: ${bakiye:,.2f} | Gün: ${gun_sl_total:.0f}/${gun_limit:.0f}"
    )


def daily_summary(text: str):
    send(f"📊 <b>GÜNLÜK ÖZET</b>\n{text}")


def alarm(mesaj: str):
    send(f"🚨 <b>ALARM</b>\n{mesaj}")


def heartbeat(bakiye, acik):
    send(f"💓 Bot ayakta | Bakiye: ${bakiye:,.0f} | Açık işlem: {acik}")


# ── CONFIRM modu ───────────────────────────────

def ask_confirmation(ot: dict) -> bool:
    """
    İşlem detayını [✅ Onayla]/[❌ İptal] butonlarıyla gönderir, cevabı bekler.
    Onaylanırsa True, iptal/timeout → False (güvenli). NOTIFY modunda çağrılmaz.
    Telegram yoksa True döner (bot otomatik devam etsin — CONFIRM sadece
    telegram varken anlamlı).
    """
    if not _enabled():
        return True
    try:
        # Son update id'yi al (eski callback'leri atla)
        offset = _last_update_id() + 1
        markup = {
            "inline_keyboard": [[
                {"text": "✅ Onayla", "callback_data": "ok"},
                {"text": "❌ İptal", "callback_data": "no"},
            ]]
        }
        _post("sendMessage", {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": (
                f"❓ <b>ONAY</b> — {ot['symbol']} {ot['yon']} ({ot.get('entry_type','?')})\n"
                f"Giriş {ot['giris']:.5f} SL {ot['sl']:.5f} TP {ot['tp']:.5f}\n"
                f"Risk ${ot['riske']:.2f} | {config.CONFIRM_TIMEOUT_SEC}sn içinde onayla, "
                f"yoksa AÇILMAZ."
            ),
            "parse_mode": "HTML",
            "reply_markup": markup,
        })
        deadline = time.time() + config.CONFIRM_TIMEOUT_SEC
        while time.time() < deadline:
            upd = _post("getUpdates", {"offset": offset, "timeout": 5}, timeout=10)
            if upd and upd.get("ok"):
                for u in upd["result"]:
                    offset = u["update_id"] + 1
                    cb = u.get("callback_query")
                    if cb and "data" in cb:
                        _post("answerCallbackQuery", {"callback_query_id": cb["id"]})
                        return cb["data"] == "ok"
            time.sleep(1)
        send("⏱️ Onay gelmedi — işlem AÇILMADI.")
        return False
    except Exception:
        # Onay mekanizması patlarsa güvenli taraf: açma
        return False


def _last_update_id() -> int:
    upd = _post("getUpdates", {"timeout": 0}, timeout=10)
    if upd and upd.get("ok") and upd["result"]:
        return upd["result"][-1]["update_id"]
    return 0
