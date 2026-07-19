<div align="center">
<h1>📈 SOFiNARD SMT Bot</h1>
<h3>Algorithmic Forex Trading Bot — MetaTrader 5 / ICT-SMC (Smart Money Concepts)</h3>
</div>
<br>
<table border="0" width="100%">
<tr>
<td width="50%" valign="top">

## 🇬🇧 EN — Overview

An automated forex trading bot built on **MetaTrader 5**, designed around **ICT / Smart Money Concepts (SMT)** — a price-action methodology that reads market structure, liquidity, and institutional order flow rather than classic lagging indicators.

The bot runs 24/7 on a VPS, manages risk automatically, and reports every action to Telegram in real time.

### 🧠 What is SMT / ICT-SMC?

Smart Money Concepts studies how liquidity and price move around key structural levels:
- **Market Structure (BOS / MSS / CHoCH):** detecting trend continuation vs. reversal via swing breaks
- **Liquidity Sweeps:** price hunting stops beyond prior highs/lows before reversing
- **Fair Value Gaps (FVG):** imbalance zones that price tends to revisit
- **Premium / Discount Zones:** where price sits relative to the recent range
- **SMT Divergence:** correlated pairs (e.g. Gold/Silver, GBPUSD/EURUSD) failing to confirm each other's move — a classic smart-money reversal signal

### 🚀 What's in this repo

| File | Purpose |
|---|---|
| `bot_worker.py` | Main live trading loop — connects to MT5, manages the full trade lifecycle |
| `backtest_smt.py` | Backtesting engine for validating the strategy on historical data |
| `run_ablation.py` | Ablation testing — measures which components actually add edge |
| `ICT_SMC_H1_H4.pine` | TradingView (Pine Script v6) indicator implementing the ICT/SMC signal logic visually — H1 execution with H4 bias filter |
| `watchdog.py` | Reliability layer — detects a frozen process via heartbeat and auto-restarts it |
| `notifier.py` | Telegram integration — live trade alerts, daily summaries, optional trade confirmation mode |
| `mt5_kontrol.py` | Broker compatibility diagnostic tool (symbol availability, trading permissions, fill modes) |
| `db.py` | SQLite + CSV persistence layer for full trade history and event logs |

> 🔒 **Note:** The core signal-generation and risk-parameter modules (`strategy.py`, `config.py`) are kept private, as they contain the live trading edge and account-specific risk settings. Everything else — the full operational stack — is open here.

### 🛠 Tech Stack

Python · MetaTrader5 API · Pandas · NumPy · SQLite3 · Telegram Bot API · Pine Script v6

### ⚙️ Engineering highlights

- **Backtested & ablation-tested** before going live — not just a hand-tuned script
- **Heartbeat-based watchdog** for unattended VPS operation
- **Real-time Telegram reporting**, with an optional manual-confirmation mode for every trade
- Secrets (MT5 login, Telegram tokens) are never hardcoded — loaded via `.env`

</td>
<td width="50%" valign="top">

## 🇹🇷 TR — Genel Bakış

**MetaTrader 5** üzerinde çalışan, **ICT / Smart Money Concepts (SMT)** mantığına dayalı otomatik bir forex trading botu. Klasik gecikmeli indikatörler yerine piyasa yapısını, likiditeyi ve kurumsal para akışını okuyan bir fiyat-aksiyonu metodolojisi kullanır.

Bot bir VPS üzerinde 7/24 çalışır, riski otomatik yönetir ve her işlemi anlık olarak Telegram'a bildirir.

### 🧠 SMT / ICT-SMC nedir?

Smart Money Concepts, likiditenin ve fiyatın kritik yapısal seviyeler etrafında nasıl hareket ettiğini inceler:
- **Piyasa Yapısı (BOS / MSS / CHoCH):** swing kırılımlarıyla trend devamı/dönüşünü tespit etme
- **Likidite Süpürmeleri:** fiyatın önceki tepe/diplerin ötesindeki stop'ları avlayıp geri dönmesi
- **Fair Value Gap (FVG):** fiyatın tekrar ziyaret etme eğiliminde olduğu dengesizlik bölgeleri
- **Premium / Discount Bölgeleri:** fiyatın güncel aralığa göre konumu
- **SMT Divergence:** korele enstrümanların (örn. Altın/Gümüş, GBPUSD/EURUSD) birbirini teyit etmemesi — klasik bir smart-money dönüş sinyali

### 🚀 Bu repo'da neler var

| Dosya | Amaç |
|---|---|
| `bot_worker.py` | Ana canlı işlem döngüsü — MT5'e bağlanır, işlem yaşam döngüsünü yönetir |
| `backtest_smt.py` | Stratejiyi geçmiş veri üzerinde doğrulayan backtest motoru |
| `run_ablation.py` | Ablation testleri — hangi bileşenin gerçekten katkı sağladığını ölçer |
| `ICT_SMC_H1_H4.pine` | ICT/SMC sinyal mantığını görselleştiren TradingView (Pine Script v6) göstergesi — H4 bias filtreli H1 işlem |
| `watchdog.py` | Güvenilirlik katmanı — heartbeat ile donmuş süreci tespit edip yeniden başlatır |
| `notifier.py` | Telegram entegrasyonu — anlık işlem bildirimleri, günlük özetler, opsiyonel onay modu |
| `mt5_kontrol.py` | Broker uyumluluk teşhis aracı (sembol erişimi, işlem izinleri, doldurma modları) |
| `db.py` | Tüm işlem geçmişi ve olay kayıtları için SQLite + CSV kalıcılık katmanı |

> 🔒 **Not:** Çekirdek sinyal üretimi ve risk parametresi modülleri (`strategy.py`, `config.py`) private tutulmuştur, çünkü canlı stratejinin ve hesaba özel risk ayarlarının kendisini içerir. Bunun dışındaki tüm operasyonel altyapı burada açık.

### 🛠 Teknolojiler

Python · MetaTrader5 API · Pandas · NumPy · SQLite3 · Telegram Bot API · Pine Script v6

### ⚙️ Mühendislik detayları

- Canlıya alınmadan önce **backtest ve ablation testlerinden** geçirildi — elle ayarlanmış bir script değil
- Gözetimsiz VPS çalışması için **heartbeat tabanlı watchdog**
- Her işlem için opsiyonel manuel onay moduyla **anlık Telegram raporlama**
- Hassas bilgiler (MT5 girişi, Telegram token'ları) asla koda gömülmez — `.env` üzerinden yüklenir

</td>
</tr>
</table>
<br>
<div align="center">
<h3>🛠️ Tech Stack & Tools</h3>
<p>
<img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/MetaTrader5-0B5FA5?style=for-the-badge&logo=metatrader&logoColor=white" />
<img src="https://img.shields.io/badge/Pandas-150458?style=for-the-badge&logo=pandas&logoColor=white" />
<img src="https://img.shields.io/badge/NumPy-013243?style=for-the-badge&logo=numpy&logoColor=white" />
<img src="https://img.shields.io/badge/SQLite-07405E?style=for-the-badge&logo=sqlite&logoColor=white" />
<img src="https://img.shields.io/badge/Telegram_Bot_API-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" />
<img src="https://img.shields.io/badge/Pine_Script-131722?style=for-the-badge&logo=tradingview&logoColor=white" />
</p>
<br>
<p><i>"Markets never sleep, neither do my bots."</i> 📈</p>
</div>

---

⚠️ **Disclaimer / Yasal Uyarı**

This software is for educational and portfolio purposes only. Trading involves substantial risk of loss. Use at your own risk.

Bu yazılım yalnızca eğitim ve portfolyo amaçlıdır. Trading önemli kayıp riski içerir. Kullanım tamamen kendi sorumluluğunuzdadır.
