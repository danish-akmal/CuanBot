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
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()  # otomatis cari dan baca file .env di folder project

# ==============================================================================
# --- CONFIGURATION CLASS ---
# ==============================================================================

@dataclass
class BotConfig:
    """Configuration class for the trading bot."""
    # API Credentials
    indodax_api_key: Optional[str] = None
    indodax_api_secret: Optional[str] = None
    coinmarketcal_api_key: Optional[str] = None

    # Telegram Settings
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Risk Management
    modal_per_coin_idr: float = 10500
    max_open_positions: int = 5
    atr_multiplier_for_sl: float = 2.0

    # Portfolio Management
    sector_mapping: Dict[str, str] = None
    max_positions_per_sector: Dict[str, int] = None

    # Exit Strategy
    take_profit_1_rr: float = 1.5
    trailing_stop_percent: float = 0.05

    # Strategy Settings
    h1_timeframe: str = '1h'
    m15_timeframe: str = '15m'
    h1_ema_period: int = 50
    m15_ema_fast: int = 13
    m15_ema_slow: int = 21
    volume_avg_period: int = 20
    atr_period: int = 14
    stoch_rsi_period: int = 14

    # Operational Modes
    simulation_mode: bool = False
    virtual_initial_idr: float = 1000000.0
    enable_btc_filter: bool = False
    state_file: str = 'active_positions.json'
    status_update_interval: int = 3
    scan_opportunities_interval: int = 5
    log_file: str = 'bot_v7_log.csv'

    def __post_init__(self):
        if self.sector_mapping is None:
            self.sector_mapping = {
                'DOGE/IDR': 'MEME', 'SHIB/IDR': 'MEME', 'PEPE/IDR': 'MEME',
                'SOL/IDR': 'LAYER1', 'ETH/IDR': 'LAYER1', 'ADA/IDR': 'LAYER1',
                'POL/IDR': 'LAYER2', 'OP/IDR': 'LAYER2',
                'FET/IDR': 'AI',
            }
        if self.max_positions_per_sector is None:
            self.max_positions_per_sector = {'MEME': 2, 'DEFAULT': 3}

def load_config() -> BotConfig:
    """Load configuration from environment variables."""
    return BotConfig(
        indodax_api_key=os.environ.get("INDODAX_API_KEY"),
        indodax_api_secret=os.environ.get("INDODAX_API_SECRET"),
        coinmarketcal_api_key=os.environ.get('COINMARKETCAL_API_KEY'),
        telegram_token=os.environ.get("TELEGRAM_TOKEN"),
def _log_event(event_type: str, pair: str = '', message: str = '', data: Optional[Dict[str, Any]] = None) -> None:
    """Log event with structured data."""
    log_message = f"{event_type} - {pair} - {message}"
    if data:
        log_message += f" - {json.dumps(data, ensure_ascii=False)}"
    logger.info(log_message)


class ProfessionalBot:
    def __init__(self):        # Validasi environment (lebih fleksibel):
        # - LIVE butuh INDODAX_API_KEY/SECRET
        # - Telegram opsional (jika tidak di-set, bot tetap jalan tanpa notifikasi)
        if not SIMULATION_MODE and not all([INDODAX_API_KEY, INDODAX_API_SECRET]):
            print("ERROR: LIVE mode butuh INDODAX_API_KEY dan INDODAX_API_SECRET (env).")
            exit()

        self.telegram_enabled = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)

        self.indodax = self._init_indodax()
        self.all_markets = self._fetch_all_markets()
        self.idr_markets = [m for m in self.all_markets if '/IDR' in m and self.all_markets.get(m, {}).get('active', False)]
        self.active_positions = self._load_state()
        # --- SIMULASI: saldo virtual (hanya dipakai saat SIMULATION_MODE) ---
        self.virtual_idr = VIRTUAL_INITIAL_IDR if SIMULATION_MODE else None

        self.cycle_counter = 0
        print("[ok] Bot Profesional v7.0 (Server Ready) berhasil diinisialisasi.")
        self.send_telegram_message(
            f"🚀 **Bot Profesional v7.0 (Server Ready) Dimulai**\n\n"
            f"Mode: `{'🔵 Simulasi' if SIMULATION_MODE else '🔴 LIVE TRADING'}`\n"
            f"Filter BTC Aktif: `{'Ya' if ENABLE_BTC_FILTER else 'Tidak'}`\n"
            f"Modal per Trade: `Rp {MODAL_PER_COIN_IDR:,.0f}`"
        )
        self.send_manual_portfolio_update()
        self.send_account_status_line()

    def _safe_amount(self, pair, amount):
        # Clamp amount to market precision and limits when possible
        try:
            market = self.indodax.market(pair)
            amount = float(self.indodax.amount_to_precision(pair, amount))
            min_amt = (market.get('limits', {}).get('amount', {}) or {}).get('min')
            if min_amt and amount < float(min_amt):
                return 0.0
            return amount
        except Exception:
            return float(amount)

    def _safe_price(self, pair, price):
        try:
            return float(self.indodax.price_to_precision(pair, price))
        except Exception:
            return float(price)

    def _can_trade_pair(self, pair, entry_price, amount):
        # Basic sanity checks: market active + minimum notional if available
        try:
            m = self.all_markets.get(pair) or {}
            if m and (m.get('active') is False):
                return False, 'Market tidak aktif'
            market = self.indodax.market(pair)
            min_cost = (market.get('limits', {}).get('cost', {}) or {}).get('min')
            if min_cost:
                cost = float(entry_price) * float(amount)
                if cost < float(min_cost):
                    return False, f'Cost < min_cost ({min_cost})'
            return True, ''
        except Exception:
            return True, ''

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
        raw_amount = MODAL_PER_COIN_IDR / entry_price
        amount_to_buy = self._safe_amount(pair, raw_amount)

        message = (f"🎯 **Sinyal Beli ({trade_type})**\n"
                   f"_Filter: Crossover, Volume, StochRSI Crossover_\n\n"
                   f"Pair: `{pair}`\n"
                   f"Harga Masuk: `Rp {entry_price:,.2f}`\n\n"
                   f"🔴 SL (basis ATR): `Rp {stop_loss_price:,.2f}`\n"
                   f"🟢 TP 1 (50%): `Rp {take_profit_1_price:,.2f}`\n"
                   f"📈 Sisa 50% dengan Trailing Stop `{TRAILING_STOP_PERCENT:.1%}`")
        self.send_telegram_message(message)

        # validasi amount minimal
        if amount_to_buy <= 0:
            _log_event('SKIP_TRADE', pair, 'amount_to_buy di bawah minimum/precision', {'raw_amount': raw_amount, 'entry_price': entry_price})
            return

        entry_price = self._safe_price(pair, entry_price)
        ok, why = self._can_trade_pair(pair, entry_price, amount_to_buy)
        if not ok:
            _log_event('SKIP_TRADE', pair, why, {'entry_price': entry_price, 'amount': amount_to_buy})
            return

        # --- SIMULASI: cek & potong saldo virtual saat BUY ---
        if SIMULATION_MODE:
            est_cost = float(entry_price) * float(amount_to_buy)
            if est_cost > float(self.virtual_idr):
                _log_event('SKIP_TRADE', pair, 'virtual_idr tidak cukup', {'virtual_idr': self.virtual_idr, 'est_cost': est_cost})
                return
            self.virtual_idr -= est_cost
            _log_event('SIM_VIRTUAL_BUY', pair, 'virtual_idr deducted', {'virtual_idr': self.virtual_idr, 'cost': est_cost})


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
        _log_event('OPEN', pair, 'position_opened', new_position)
        self._save_state()
        _log_event('NOTIFY', pair, 'posisi dibuka')
        self.send_telegram_message(f"[ok] **Posisi Dibuka**\nPair: `{pair}` (Mode: `{'Simulasi' if SIMULATION_MODE else '🔴 LIVE'}`)")

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
                _log_event('MANAGE_ERROR', position.get('pair',''), str(e))

    def scale_out_position(self, position, current_price):
        amount_to_sell = self._safe_amount(position['pair'], position['amount'] / 2)
        # --- SIMULASI: kredit saldo virtual saat jual 50% (TP1) ---
        if SIMULATION_MODE:
            proceeds = float(current_price) * float(amount_to_sell)
            self.virtual_idr += proceeds
            _log_event('SIM_VIRTUAL_SELL_TP1', position['pair'], 'virtual_idr credited', {'virtual_idr': self.virtual_idr, 'proceeds': proceeds})

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
        _log_event('TP1', position['pair'], 'tp1_hit', {'exit_price': current_price, 'amount_sold': amount_to_sell})
        self.send_telegram_message(f"💰 **TP 1 Tercapai**\n\n"
                                   f"Pair: `{position['pair']}`\n"
                                   f"Menjual 50% posisi. SL dipindahkan ke breakeven.")

    def close_position(self, position, reason, exit_price, amount):
        if not SIMULATION_MODE:
            try:
                amount = self._safe_amount(position['pair'], amount)
                order = self.indodax.create_market_sell_order(position['pair'], amount)
            except Exception as e:
                self.handle_error(f"Gagal menutup posisi {position['pair']}: {e}")
                return
        # --- SIMULASI: kredit saldo virtual saat close posisi ---
        if SIMULATION_MODE:
            proceeds = float(exit_price) * float(amount)
            self.virtual_idr += proceeds
            _log_event('SIM_VIRTUAL_SELL_CLOSE', position['pair'], 'virtual_idr credited', {'virtual_idr': self.virtual_idr, 'proceeds': proceeds})

        pnl = ((exit_price - position['entry_price']) / position['entry_price']) * 100
        icon = "🔴" if pnl < 0 else "🟢"
        message = (f"{icon} **Posisi Ditutup ({reason})**\n\n"
                   f"Pair: `{position['pair']}`\n"
                   f"Harga Keluar: `Rp {exit_price:,.2f}`\n"
                   f"Profit/Loss: `{pnl:.2f}%`")
        self.send_telegram_message(message)
        _log_event('CLOSE', position['pair'], reason, {'exit_price': exit_price, 'amount': amount, 'pnl_percent': pnl})
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
            print(f"[ok] Berhasil memuat {len(markets)} total market dari Indodax.")
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
    
    def _virtual_equity_idr(self):
        # Equity simulasi = saldo IDR virtual + nilai market semua posisi bot (mark-to-market)
            if not SIMULATION_MODE:
                return None
            equity = float(getattr(self, 'virtual_idr', 0.0) or 0.0)
            for pos in self.active_positions:
                try:
                    last = float(self.indodax.fetch_ticker(pos['pair'])['last'])
                    equity += float(pos['amount']) * last
                except Exception:
                    pass
            return equity

    
    def send_status_update(self):
        if not self.active_positions:
            message = "[ok] **Laporan Status Bot**\n\nTidak ada posisi aktif yang dikelola bot."
            self.send_telegram_message(message)
            return
        summary_message = "📊 **Laporan Status Posisi Bot**\n\n"
        # Baris status akun untuk laporan berkala
        if SIMULATION_MODE:
            veq = self._virtual_equity_idr()
            summary_message += f"🏦 Status Akun (SIM): Virtual IDR `Rp {self.virtual_idr:,.0f}`\n"
            if veq is not None:
                summary_message += f"🏦 Virtual Equity: `Rp {veq:,.0f}`\n\n"
        else:
            try:
                bal = self.indodax.fetch_balance()
                idr_free = float((bal.get('free', {}) or {}).get('IDR', 0) or 0)
                idr_total = float((bal.get('total', {}) or {}).get('IDR', 0) or 0)
                summary_message += f"🏦 Status Akun (LIVE): IDR free `Rp {idr_free:,.0f}` | IDR total `Rp {idr_total:,.0f}`\n\n"
            except Exception as e:
                summary_message += f"🏦 Status Akun (LIVE): gagal fetch_balance ({e})\n\n"

        if SIMULATION_MODE:
            veq = self._virtual_equity_idr()
            summary_message += f"💼 Virtual IDR: `Rp {self.virtual_idr:,.0f}`\n"
            if veq is not None:
                summary_message += f"📈 Virtual Equity: `Rp {veq:,.0f}`\n\n"

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
    
    def send_account_status_line(self):
            try:
                if SIMULATION_MODE:
                    veq = self._virtual_equity_idr()
                    msg = f"🏦 Status Akun (SIM): Virtual IDR={self.virtual_idr:,.0f}"
                    if veq is not None:
                        msg += f" | Virtual Equity={veq:,.0f}"
                    self.send_telegram_message(msg)
                    _log_event('ACCOUNT_STATUS', '', 'sim_account_status', {'virtual_idr': self.virtual_idr, 'virtual_equity': veq})
                else:
                    bal = self.indodax.fetch_balance()
                    idr_free = float((bal.get('free', {}) or {}).get('IDR', 0) or 0)
                    idr_total = float((bal.get('total', {}) or {}).get('IDR', 0) or 0)
                    msg = f"🏦 Status Akun (LIVE): IDR free={idr_free:,.0f} | IDR total={idr_total:,.0f}"
                    self.send_telegram_message(msg)
                    _log_event('ACCOUNT_STATUS', '', 'live_account_status', {'idr_free': idr_free, 'idr_total': idr_total})
            except Exception as e:
                _log_event('ACCOUNT_STATUS_ERROR', '', str(e))

    
    def send_telegram_message(self, message):
            # Selalu tampilkan ke terminal juga (biar kelihatan saat bot dijalankan)
            try:
                print(message)
            except Exception:
                pass

            # Jika telegram tidak diset, cukup berhenti di sini
            if not getattr(self, 'telegram_enabled', False):
                return

            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
            try:
                requests.post(url, json=payload)
            except Exception as e:
                print(f" - Gagal mengirim notifikasi Telegram: {e}")


if __name__ == "__main__":
    bot = ProfessionalBot()
    bot.run()
