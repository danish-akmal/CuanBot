# ======================================================================================================================
# == Bot Trading Profesional v7.0 (Server Ready)                                                                      ==
# == Dibuat berdasarkan diskusi dan permintaan Anda. Versi ini dirancang untuk berjalan di server cloud.                ==
# ==                                                                                                                  ==
# == DISCLAIMER:                                                                                                      ==
# == Kode ini disediakan untuk TUJUAN EDUKASI. Trading aset kripto memiliki RISIKO SANGAT TINGGI.                       ==
# == Anda bisa dan mungkin akan kehilangan uang. Penulis tidak bertanggung jawab atas kerugian finansial apa pun.       ==
# == Uji coba secara ekstensif dalam MODE SIMULASI sebelum mempertimbangkan penggunaan dengan uang sungguhan.            ==
# ======================================================================================================================

import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()  # otomatis cari dan baca file .env di folder project
# ==============================================================================
# --- PENGATURAN UTAMA BOT (SILAKAN UBAH DI SINI) ---
# ==============================================================================

# --- KONEKSI & KUNCI API (DIBACA DARI ENVIRONMENT VARIABLES) ---
# PERUBAHAN: Kunci API tidak lagi ditulis di sini. Bot akan membacanya dari pengaturan server.
INDODAX_API_KEY = os.environ.get("INDODAX_API_KEY")
INDODAX_API_SECRET = os.environ.get("INDODAX_API_SECRET")
COINMARKETCAL_API_KEY = os.environ.get('COINMARKETCAL_API_KEY')

# --- PENGATURAN TELEGRAM (DIBACA DARI ENVIRONMENT VARIABLES) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- MANAJEMEN MODAL & RISIKO ---
MODAL_PER_COIN_IDR = 10500
MAX_OPEN_POSITIONS = 5
ATR_MULTIPLIER_FOR_SL = 2.0

# --- MANAJEMEN PORTOFOLIO & SEKTOR ---
SECTOR_MAPPING = {
    'DOGE/IDR': 'MEME', 'SHIB/IDR': 'MEME', 'PEPE/IDR': 'MEME',
    'SOL/IDR': 'LAYER1', 'ETH/IDR': 'LAYER1', 'ADA/IDR': 'LAYER1',
    'POL/IDR': 'LAYER2', 'OP/IDR': 'LAYER2',
    'FET/IDR': 'AI',
}
MAX_POSITIONS_PER_SECTOR = {'MEME': 2, 'DEFAULT': 3}

# --- PENGATURAN STRATEGI KELUAR (EXIT STRATEGY) ---
TAKE_PROFIT_1_RR = 1.5
TRAILING_STOP_PERCENT = 0.05

# --- PENGATURAN STRATEGI & FILTER ---
H1_TIMEFRAME = '1h'
M15_TIMEFRAME = '15m'
H1_EMA_PERIOD = 50
M15_EMA_FAST = 13
M15_EMA_SLOW = 21
VOLUME_AVG_PERIOD = 20
ATR_PERIOD = 14
STOCH_RSI_PERIOD = 14

# --- MODE OPERASIONAL ---
# PERUBAHAN: Mode simulasi dan filter BTC bisa diatur melalui Environment Variables juga.
# Jika tidak diatur, akan menggunakan nilai default di bawah ini.
SIMULATION_MODE = os.environ.get('SIMULATION_MODE', 'False').lower() in ('true', '1', 't')
ENABLE_BTC_FILTER = os.environ.get('ENABLE_BTC_FILTER', 'False').lower() in ('true', '1', 't')
STATE_FILE = 'active_positions.json'
STATUS_UPDATE_INTERVAL = 3
SCAN_OPPORTUNITIES_INTERVAL = 5

# ==============================================================================
# --- KELAS UTAMA BOT (Logika trading tidak berubah dari v6.1) ---
# ==============================================================================

class ProfessionalBot:
    def __init__(self):
        # Validasi bahwa semua kunci rahasia penting sudah diatur
        if not all([INDODAX_API_KEY, INDODAX_API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
            print("❌ ERROR: Pastikan semua Environment Variables (INDODAX_API_KEY, INDODAX_API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID) sudah diatur di server.")
            exit()

        self.indodax = self._init_indodax()
        self.all_markets = self._fetch_all_markets()
        self.idr_markets = [m for m in self.all_markets if '/IDR' in m and self.all_markets.get(m, {}).get('active', False)]
        self.active_positions = self._load_state()
        self.cycle_counter = 0
        print("✅ Bot Profesional v7.0 (Server Ready) berhasil diinisialisasi.")
        self.send_telegram_message(
            f"🚀 **Bot Profesional v7.0 (Server Ready) Dimulai**\n\n"
            f"Mode: `{'Simulasi' if SIMULATION_MODE else '🔴 LIVE TRADING'}`\n"
            f"Filter BTC Aktif: `{'Ya' if ENABLE_BTC_FILTER else 'Tidak'}`\n"
            f"Modal per Trade: `Rp {MODAL_PER_COIN_IDR:,.0f}`"
        )
        self.send_manual_portfolio_update()

    def run(self):
        while True:
            try:
                self.cycle_counter += 1
                
                market_is_healthy = not ENABLE_BTC_FILTER or (ENABLE_BTC_FILTER and self.is_market_healthy())

                if market_is_healthy:
                    if self.cycle_counter % SCAN_OPPORTUNITIES_INTERVAL == 0:
                        if len(self.active_positions) < MAX_OPEN_POSITIONS:
                            print(f"\n[{time.strftime('%H:%M:%S')}] Menjalankan pemindaian peluang...")
                            candidates = self.momentum_engine()
                            self.process_candidates(candidates, "Momentum")
                else:
                    print(f"\n[{time.strftime('%H:%M:%S')}] Pasar BTC tidak sehat. Mode Aman Aktif.")

                self.manage_active_positions()
                
                if self.cycle_counter % STATUS_UPDATE_INTERVAL == 0:
                    self.send_status_update()

                print(f"[{time.strftime('%H:%M:%S')}] Siklus {self.cycle_counter} selesai. Menunggu 60 detik...", end="\r")
                time.sleep(60)

            except Exception as e:
                self.handle_error(f"Error di loop utama: {e}")
                time.sleep(60)

    def momentum_engine(self):
        print(f"  - Mesin Momentum: Memindai {len(self.idr_markets)} koin...")
        trending_coins = []
        for pair in self.idr_markets:
            try:
                ticker = self.indodax.fetch_ticker(pair)
                if ticker and ticker.get('percentage') is not None and ticker['percentage'] > 3:
                    trending_coins.append(pair)
            except Exception:
                pass
            time.sleep(0.5)
        return trending_coins

    def process_candidates(self, candidates, engine_type):
        for pair in candidates:
            if len(self.active_positions) >= MAX_OPEN_POSITIONS or any(p['pair'] == pair for p in self.active_positions):
                continue

            sector = SECTOR_MAPPING.get(pair, 'DEFAULT')
            max_for_sector = MAX_POSITIONS_PER_SECTOR.get(sector, MAX_OPEN_POSITIONS)
            current_sector_positions = sum(1 for p in self.active_positions if SECTOR_MAPPING.get(p['pair'], 'DEFAULT') == sector)

            if current_sector_positions >= max_for_sector:
                print(f"  - [{pair}] Sinyal diabaikan. Batas posisi untuk sektor '{sector}' ({max_for_sector}) sudah tercapai.")
                continue

            self.analyze_and_trade(pair, engine_type)

    def analyze_and_trade(self, pair, trade_type):
        h1_data = self.get_data_with_indicators(pair, H1_TIMEFRAME)
        if h1_data is None or h1_data.iloc[-1]['close'] < h1_data.iloc[-1][f'EMA_{H1_EMA_PERIOD}']:
            return

        m15_data = self.get_data_with_indicators(pair, M15_TIMEFRAME)
        if m15_data is None or len(m15_data) < 10: return
        
        last_m15 = m15_data.iloc[-2]
        prev_m15 = m15_data.iloc[-3]

        signal_crossover = prev_m15[f'EMA_{M15_EMA_FAST}'] < prev_m15[f'EMA_{M15_EMA_SLOW}'] and \
                           last_m15[f'EMA_{M15_EMA_FAST}'] > last_m15[f'EMA_{M15_EMA_SLOW}']
        
        volume_sma_col = f'VOLUME_SMA_{VOLUME_AVG_PERIOD}'
        signal_volume = last_m15['volume'] > last_m15[volume_sma_col]
        
        stoch_rsi_k_col = f'STOCHRSIk_{STOCH_RSI_PERIOD}_14_3_3'
        stoch_rsi_d_col = f'STOCHRSId_{STOCH_RSI_PERIOD}_14_3_3'
        
        signal_stoch_rsi = (prev_m15[stoch_rsi_k_col] < prev_m15[stoch_rsi_d_col]) and \
                           (last_m15[stoch_rsi_k_col] > last_m15[stoch_rsi_d_col])

        if signal_crossover and signal_volume and signal_stoch_rsi:
            self.execute_trade(pair, trade_type, m15_data.iloc[-1]['close'], last_m15[f'ATR_{ATR_PERIOD}'])

    def execute_trade(self, pair, trade_type, entry_price, atr_value):
        stop_loss_price = entry_price - (ATR_MULTIPLIER_FOR_SL * atr_value)
        risk_per_coin = entry_price - stop_loss_price
        take_profit_1_price = entry_price + (TAKE_PROFIT_1_RR * risk_per_coin)
        amount_to_buy = MODAL_PER_COIN_IDR / entry_price

        message = (f"🎯 **Sinyal Beli ({trade_type})**\n"
                   f"_Filter: Crossover, Volume, StochRSI Crossover_\n\n"
                   f"Pair: `{pair}`\n"
                   f"Harga Masuk: `Rp {entry_price:,.2f}`\n\n"
                   f"🔴 SL (basis ATR): `Rp {stop_loss_price:,.2f}`\n"
                   f"🟢 TP 1 (50%): `Rp {take_profit_1_price:,.2f}`\n"
                   f"📈 Sisa 50% dengan Trailing Stop `{TRAILING_STOP_PERCENT:.1%}`")
        self.send_telegram_message(message)

        if not SIMULATION_MODE:
            try:
                order = self.indodax.create_limit_buy_order(pair, amount_to_buy, entry_price)
            except Exception as e:
                self.handle_error(f"Gagal membuat order Beli untuk {pair}: {e}")
                return

        new_position = {
            "pair": pair, "entry_price": entry_price, "amount": amount_to_buy,
            "sl_price": stop_loss_price, "tp1_price": take_profit_1_price,
            "highest_price": entry_price, "tp1_hit": False, "type": trade_type
        }
        self.active_positions.append(new_position)
        self._save_state()
        self.send_telegram_message(f"✅ **Posisi Dibuka**\nPair: `{pair}` (Mode: `{'Simulasi' if SIMULATION_MODE else '🔴 LIVE'}`)")

    def manage_active_positions(self):
        for position in self.active_positions[:]:
            try:
                current_price = self.indodax.fetch_ticker(position['pair'])['last']
                if not position['tp1_hit'] and current_price >= position['tp1_price']:
                    self.scale_out_position(position, current_price)
                    continue
                if current_price > position['highest_price']:
                    position['highest_price'] = current_price
                    new_sl = current_price * (1 - TRAILING_STOP_PERCENT)
                    if new_sl > position['sl_price']:
                        position['sl_price'] = new_sl
                        self._save_state()
                if current_price <= position['sl_price']:
                    reason = "Stop Loss" if not position['tp1_hit'] else "Trailing Stop"
                    self.close_position(position, reason, current_price, position['amount'])
            except Exception as e:
                pass

    def scale_out_position(self, position, current_price):
        amount_to_sell = position['amount'] / 2
        if not SIMULATION_MODE:
            try:
                order = self.indodax.create_market_sell_order(position['pair'], amount_to_sell)
            except Exception as e:
                self.handle_error(f"Gagal menutup 50% posisi {position['pair']}: {e}")
                return
        position['amount'] /= 2
        position['sl_price'] = position['entry_price']
        position['tp1_hit'] = True
        self._save_state()
        self.send_telegram_message(f"💰 **TP 1 Tercapai**\n\n"
                                   f"Pair: `{position['pair']}`\n"
                                   f"Menjual 50% posisi. SL dipindahkan ke breakeven.")

    def close_position(self, position, reason, exit_price, amount):
        if not SIMULATION_MODE:
            try:
                order = self.indodax.create_market_sell_order(position['pair'], amount)
            except Exception as e:
                self.handle_error(f"Gagal menutup posisi {position['pair']}: {e}")
                return
        pnl = ((exit_price - position['entry_price']) / position['entry_price']) * 100
        icon = "🔴" if pnl < 0 else "🟢"
        message = (f"{icon} **Posisi Ditutup ({reason})**\n\n"
                   f"Pair: `{position['pair']}`\n"
                   f"Harga Keluar: `Rp {exit_price:,.2f}`\n"
                   f"Profit/Loss: `{pnl:.2f}%`")
        self.send_telegram_message(message)
        self.active_positions.remove(position)
        self._save_state()

    def is_market_healthy(self):
        try:
            btc_data = self.get_data_with_indicators('BTC/IDR', '4h')
            if btc_data is None: return False
            return btc_data.iloc[-1]['close'] > btc_data.iloc[-1]['EMA_50']
        except Exception:
            return False

    def get_data_with_indicators(self, pair, timeframe):
        try:
            limit = 100
            ohlcv = self.indodax.fetch_ohlcv(pair, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df.ta.ema(length=H1_EMA_PERIOD, append=True)
            df.ta.ema(length=M15_EMA_FAST, append=True)
            df.ta.ema(length=M15_EMA_SLOW, append=True)
            df.ta.atr(length=ATR_PERIOD, append=True)
            df.ta.sma(length=VOLUME_AVG_PERIOD, close='volume', prefix='VOLUME', append=True)
            df.ta.stochrsi(length=STOCH_RSI_PERIOD, append=True)
            return df
        except Exception:
            return None

    def _init_indodax(self):
        try:
            return ccxt.indodax({'apiKey': INDODAX_API_KEY, 'secret': INDODAX_API_SECRET})
        except Exception as e:
            self.handle_error(f"Gagal koneksi ke Indodax: {e}")
            exit()

    def _fetch_all_markets(self):
        try:
            markets = self.indodax.load_markets()
            print(f"✅ Berhasil memuat {len(markets)} total market dari Indodax.")
            return markets
        except Exception as e:
            self.handle_error(f"Gagal memuat daftar market dari Indodax: {e}")
            return {}
    
    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    content = f.read()
                    if not content: return []
                    return json.loads(content)
            except json.JSONDecodeError:
                return []
        else:
            self._save_state([])
            return []

    def _save_state(self, positions=None):
        with open(STATE_FILE, 'w') as f:
            data_to_save = positions if positions is not None else self.active_positions
            json.dump(data_to_save, f, indent=4)

    def send_status_update(self):
        if not self.active_positions:
            message = "✅ **Laporan Status Bot**\n\nTidak ada posisi aktif yang dikelola bot."
            self.send_telegram_message(message)
            return
        summary_message = "📊 **Laporan Status Posisi Bot**\n\n"
        total_pnl_idr = 0
        for pos in self.active_positions:
            try:
                current_price = self.indodax.fetch_ticker(pos['pair'])['last']
                pnl_percent = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                pnl_idr = (current_price - pos['entry_price']) * pos['amount']
                if pos['tp1_hit']:
                    profit_from_tp1 = (pos['tp1_price'] - pos['entry_price']) * pos['amount']
                    pnl_idr += profit_from_tp1
                total_pnl_idr += pnl_idr
                icon = "🟢" if pnl_percent >= 0 else "🔴"
                summary_message += (f"*{pos['pair']}*\n"
                                    f"{icon} PNL: `{pnl_percent:+.2f}%` (`Rp {pnl_idr:,.0f}`)\n"
                                    f"Status: `{'Trailing Stop' if pos['tp1_hit'] else 'Menuju TP1'}`\n\n")
            except Exception as e:
                summary_message += f"*{pos['pair']}*\n Gagal mengambil data: `{e}`\n\n"
        summary_message += f"*Total Floating PNL (Bot): Rp {total_pnl_idr:,.0f}*"
        self.send_telegram_message(summary_message)
    
    def send_manual_portfolio_update(self):
        try:
            message = "📋 **Laporan Snapshot Portfolio Manual**\n_(Posisi yang tidak dikelola bot)_\n\n"
            balances = self.indodax.fetch_balance()
            bot_assets = [p['pair'].split('/')[0] for p in self.active_positions]
            manual_assets = []
            total_manual_value_idr = 0
            idr_balance = balances['free'].get('IDR', 0)
            if idr_balance > 0:
                total_manual_value_idr += idr_balance
            for asset, balance in balances['total'].items():
                if balance > 0 and asset != 'IDR' and asset not in bot_assets:
                    pair = f"{asset}/IDR"
                    asset_data = {'asset': asset, 'balance': balance, 'value_idr': 0, 
                                  'percentage_change': None, 'value_change_24h': None, 'status': 'OK'}
                    market_info = self.all_markets.get(pair)
                    if market_info:
                        if not market_info['active']:
                            asset_data['status'] = 'Maintenance / Market Tidak Aktif'
                            try:
                                last_price = float(market_info['info'].get('last', 0))
                                if last_price > 0:
                                    value_idr = balance * last_price
                                    total_manual_value_idr += value_idr
                                    asset_data['value_idr'] = value_idr
                            except (TypeError, ValueError, KeyError):
                                pass
                        else:
                            try:
                                ticker = self.indodax.fetch_ticker(pair)
                                current_price = ticker['last']
                                value_idr = balance * current_price
                                total_manual_value_idr += value_idr
                                asset_data['value_idr'] = value_idr
                                if ticker.get('percentage') is not None and ticker.get('open') is not None and ticker['open'] > 0:
                                    asset_data['percentage_change'] = ticker['percentage']
                                    previous_value_idr = balance * ticker['open']
                                    asset_data['value_change_24h'] = value_idr - previous_value_idr
                            except Exception:
                                asset_data['status'] = 'Maintenance / Data Error'
                    else:
                        asset_data['status'] = 'Tidak diperdagangkan di IDR'
                    manual_assets.append(asset_data)
            manual_assets.sort(key=lambda x: x['value_idr'], reverse=True)
            if idr_balance > 0:
                 message += f"*{'IDR'}*\n  Saldo Tersedia: `Rp {idr_balance:,.0f}`\n\n"
            for data in manual_assets:
                message += f"*{data['asset']}*\n"
                message += f"  Saldo: `{data['balance']}`\n"
                if data['status'] == 'OK':
                    message += f"  Nilai: `Rp {data['value_idr']:,.0f}`\n"
                    if data['percentage_change'] is not None:
                        icon = "📈" if data['percentage_change'] >= 0 else "📉"
                        message += f"  24jam: {icon} `{data['percentage_change']:+.2f}%` (`Rp {data['value_change_24h']:+,.0f}`)\n"
                else:
                    if data['value_idr'] > 0:
                         message += f"  Nilai Est: `Rp {data['value_idr']:,.0f}`\n"
                    message += f"  Status: `{data['status']}`\n"
                message += "\n"
            if not manual_assets and idr_balance == 0:
                message += "Tidak ada posisi manual lain yang terdeteksi."
            else:
                 message += f"*------------------------------*\n"
                 message += f"*Estimasi Total Nilai Manual: Rp {total_manual_value_idr:,.0f}*"
            self.send_telegram_message(message)
        except Exception as e:
            self.handle_error(f"Gagal mengirim laporan portfolio manual: {e}")

    def send_telegram_message(self, message):
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        try:
            requests.post(url, json=payload)
        except Exception as e:
            print(f"  - Gagal mengirim notifikasi Telegram: {e}")

    def handle_error(self, error_message):
        print(f"\n❌ ERROR: {error_message}")
        self.send_telegram_message(f"❌ **ERROR KRITIS PADA BOT**\n`{error_message}`")

if __name__ == "__main__":
    bot = ProfessionalBot()
    bot.run()
