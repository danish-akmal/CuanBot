# 🪙 CuanBot berbasis [Hybrid Trading Bot v7.0](https://github.com/nizardy/bot-indodax)

Bot trading otomatis untuk **Indodax** berbasis Python.  
Menggunakan indikator teknikal (EMA, ATR, Volume SMA, StochRSI) dengan manajemen risiko terintegrasi, serta notifikasi real-time via Telegram.

> ⚠️ **DISCLAIMER:**  
> Bot ini dibuat untuk tujuan edukasi. Trading aset kripto memiliki risiko sangat tinggi.  
> Gunakan **SIMULATION_MODE** terlebih dahulu sebelum mempertimbangkan live trading dengan uang sungguhan.  
> Pembuat tidak bertanggung jawab atas kerugian finansial apa pun.

---

## ✨ Fitur Utama
- Koneksi ke **Indodax API** via [ccxt](https://github.com/ccxt/ccxt).
- Indikator teknikal: EMA crossover, ATR stop loss, Volume SMA, StochRSI.
- Manajemen risiko:
  - `MODAL_PER_COIN_IDR` (modal per trade).
  - `MAX_OPEN_POSITIONS` (batas posisi aktif).
  - Stop Loss berbasis ATR.
  - Take Profit 1 + Trailing Stop.
  - Batas posisi per sektor (MEME, LAYER1, LAYER2, AI).
- State posisi disimpan di `active_positions.json`.
- Notifikasi Telegram (status, sinyal beli, TP/SL, error).
- Mode **SIMULATION_MODE** untuk uji coba tanpa order nyata.
- Filter kondisi pasar BTC (opsional).

---

## 📦 Instalasi
1. Clone repo:
   ```bash
   git clone https://github.com/danish-akmal/CuanBot.git
      ```
2. Buat virtual environment & install requirements:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/Mac
   venv\Scripts\activate      # Windows
   pip install -r requirements.txt
   ```
3. Buat file `.env` berisi:
   ```env
   INDODAX_API_KEY=your_api_key
   INDODAX_API_SECRET=your_api_secret
   TELEGRAM_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   SIMULATION_MODE=True
   ENABLE_BTC_FILTER=True
   ```
4. Jalankan bot:
   ```bash
   python hybrid_bot_v7.py
   ```

---

## ⚙️ Konfigurasi
Parameter utama dapat diubah di dalam kode atau melalui `.env`:
- **Modal & Risiko**
  - `MODAL_PER_COIN_IDR` → modal per trade (default Rp10.500).
  - `MAX_OPEN_POSITIONS` → jumlah posisi aktif maksimum.
  - `ATR_MULTIPLIER_FOR_SL` → multiplier ATR untuk stop loss.
  - `TAKE_PROFIT_1_RR` → rasio TP1.
  - `TRAILING_STOP_PERCENT` → trailing stop.
- **Strategi**
  - Timeframe: `H1_TIMEFRAME`, `M15_TIMEFRAME`.
  - EMA: `H1_EMA_PERIOD`, `M15_EMA_FAST`, `M15_EMA_SLOW`.
  - Volume SMA: `VOLUME_AVG_PERIOD`.
  - ATR: `ATR_PERIOD`.
  - StochRSI: `STOCH_RSI_PERIOD`.

---

## 📲 Notifikasi Telegram
Bot akan mengirim:
- Sinyal beli (entry, SL, TP).
- Status posisi aktif.
- TP1 tercapai / posisi ditutup.
- Error kritis.

---

## 🛡️ Catatan Keamanan
- **Jangan commit file `.env`** ke repo publik.
- API key & secret hanya dibaca dari environment variables.
- Log/Telegram tidak menampilkan key/secret.

---

## 🚀 Roadmap
- Modularisasi kode (core, strategy, risk, execution, state).
- File config YAML/JSON.
- Modul backtesting.
- CLI interaktif (start, stop, status, backtest, config, logs).
- Risk management lebih lengkap (max daily loss, max trades/day).
- Laporan harian via Telegram.

---

## 📜 Lisensi
Proyek ini dilisensikan di bawah **MIT License**.  
Anda bebas menggunakan, memodifikasi, dan mendistribusikan kode ini dengan tetap mencantumkan atribusi.  

---

### 🔗 Sumber Referensi
Sebagian inspirasi dan referensi diambil dari proyek [nizardy/bot-indodax](https://github.com/nizardy/bot-indodax).
```
