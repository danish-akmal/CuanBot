"""ui_hybrid_bot.py
UI-CLI minimalis untuk monitoring dan menjalankan hybrid_bot_v7_patched.py.

Menampilkan:
- Status Bot
- Status Trading (posisi aktif + floating PnL)
- Status Akun Indodax (detail saldo dan estimasi nilai IDR)

Mode operasi:
- Default: monitoring saja.
- Perintah 'start' akan menjalankan bot sebagai proses terpisah.
- Perintah 'stop' akan mengirim SIGTERM ke proses bot.

Env opsional:
- UI_REFRESH=0        -> manual (default)
- UI_REFRESH=5        -> auto refresh tiap 5 detik
- UI_TOP_ASSETS=15    -> jumlah aset ditampilkan
- BOT_PID_FILE=hybrid_bot.pid
- PYTHON_BIN=python   -> interpreter untuk menjalankan bot

Catatan penting:
- UI tidak meng-import/instantiate ProfessionalBot untuk menjalankan bot (karena run() blocking).
  Bot dijalankan via subprocess: `python hybrid_bot_v7_patched.py`.
"""

import os
import time
import signal
import subprocess
import atexit
import sys

from datetime import datetime, timedelta, timezone

import hybrid_bot_v7_patched as bot

from dotenv import load_dotenv

load_dotenv()  # otomatis cari dan baca file .env di folder project

WIB = timezone(timedelta(hours=7))

def wib_ts():
    return datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')

PID_FILE = os.environ.get('BOT_PID_FILE', 'hybrid_bot.pid')


def utc_ts():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def human_int(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def human_float(n, d=8):
    try:
        return f"{float(n):.{d}f}"
    except Exception:
        return str(n)


def safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, str(e)


def api_config_status():
    key_ok = bool((bot.INDODAX_API_KEY or '').strip())
    sec_ok = bool((bot.INDODAX_API_SECRET or '').strip())
    return key_ok and sec_ok


def _read_pid():
    try:
        if not os.path.exists(PID_FILE):
            return None
        return int(open(PID_FILE, 'r', encoding='utf-8').read().strip())
    except Exception:
        return None


def bot_is_running():
    pid = _read_pid()
    if not pid:
        return False, None
    try:
        os.kill(pid, 0)
        return True, pid
    except Exception:
        return False, pid


def start_bot():
    running, pid = bot_is_running()
    if running:
        return False, f"Bot sudah berjalan (pid={pid})"

    base_dir = os.path.dirname(os.path.abspath(__file__))

    py = os.environ.get('PYTHON_BIN')
    if not py:
        # coba venv lokal
        cand = os.path.join(base_dir, 'venv', 'Scripts', 'python.exe')  # Windows
        if os.path.exists(cand):
            py = cand
        else:
            py = 'python'
    cmd = [py, 'hybrid_bot_v7_patched.py']

    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(base_dir, 'bot_process.log')

    try:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0

        logf = open(log_path, 'a', encoding='utf-8')

        # copy env + paksa UTF-8
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"

        p = subprocess.Popen(
            cmd,
            cwd=base_dir,
            stdout=logf,
            stderr=logf,
            creationflags=creationflags,
            env=env,               # <-- tambah baris ini
        )

        time.sleep(0.5)
        if p.poll() is not None:
            return False, f"Bot gagal start (exit={p.returncode}). Cek: {log_path}"

        with open(PID_FILE, 'w', encoding='utf-8') as f:
            f.write(str(p.pid))

        return True, f"Bot started (pid={p.pid}). Log: {log_path}"
    except Exception as e:
        return False, str(e)



def stop_bot():
    pid = _read_pid()
    if not pid:
        return False, 'PID file tidak ditemukan'

    try:
        os.kill(pid, signal.SIGTERM)
        try:
            os.remove(PID_FILE)
        except Exception:
            pass
        return True, f"Stop signal sent (pid={pid})"
    except Exception as e:
        return False, str(e)

def cleanup_on_exit():
    running, pid = bot_is_running()
    if running:
        stop_bot()

def build_indodax_client():
    # UI membuat client sendiri (monitoring) agar tidak memanggil __init__ bot.
    import ccxt
    return ccxt.indodax({'apiKey': bot.INDODAX_API_KEY, 'secret': bot.INDODAX_API_SECRET})


def load_positions_state():
    path = getattr(bot, 'STATE_FILE', 'active_positions.json')
    if not os.path.exists(path):
        return [], None
    try:
        import json
        raw = open(path, 'r', encoding='utf-8').read().strip()
        if not raw:
            return [], None
        data = json.loads(raw)
        if isinstance(data, list):
            return data, None
        return [], 'STATE_FILE bukan list'
    except Exception as e:
        return [], str(e)


def fetch_account_snapshot(ex, markets=None, top_n=15):
    bal, err = safe_call(ex.fetch_balance)
    if err:
        return None, err

    free = bal.get('free', {}) or {}
    total = bal.get('total', {}) or {}

    idr_free = float(free.get('IDR', 0) or 0)
    idr_total = float(total.get('IDR', 0) or 0)

    assets = []
    for asset, amt in total.items():
        try:
            amt = float(amt or 0)
        except Exception:
            continue
        if asset == 'IDR' or amt <= 0:
            continue
        assets.append((asset, amt, float(free.get(asset, 0) or 0)))

    est_idr = idr_total
    rows = []

    if markets is None:
        markets, _ = safe_call(ex.load_markets)
        markets = markets or {}

    for asset, amt_total, amt_free in assets:
        pair = f"{asset}/IDR"
        last = None
        value = None
        status = 'OK'

        m = markets.get(pair)
        if m and (m.get('active') is False):
            status = 'Maintenance'

        if m:
            t, terr = safe_call(ex.fetch_ticker, pair)
            if terr:
                status = 'TickerError'
            else:
                try:
                    last = float(t.get('last') or 0) if t else None
                except Exception:
                    last = None

        if last and last > 0:
            value = amt_total * last
            est_idr += value

        rows.append({
            'asset': asset,
            'total': amt_total,
            'free': amt_free,
            'pair': pair,
            'last_idr': last,
            'value_idr': value,
            'status': status,
        })

    rows.sort(key=lambda r: (r['value_idr'] or 0), reverse=True)
    rows = rows[:max(1, int(top_n))]

    return {
        'idr_free': idr_free,
        'idr_total': idr_total,
        'est_total_idr': est_idr,
        'assets': rows,
    }, None


def compute_positions_status(ex, positions):
    enriched = []
    total_pnl_idr = 0.0
    total_cost_idr = 0.0

    for p in positions:
        pair = p.get('pair')
        entry = float(p.get('entry_price') or 0)
        amt = float(p.get('amount') or 0)

        last = None
        pnl_idr = None
        pnl_pct = None
        err = None

        if pair:
            t, terr = safe_call(ex.fetch_ticker, pair)
            if terr:
                err = terr
            else:
                try:
                    last = float(t.get('last') or 0)
                except Exception:
                    last = None

        if last and entry > 0 and amt > 0:
            pnl_idr = (last - entry) * amt
            pnl_pct = ((last - entry) / entry) * 100
            total_pnl_idr += pnl_idr
            total_cost_idr += entry * amt

        enriched.append({
            'pair': pair,
            'type': p.get('type'),
            'entry': entry,
            'amount': amt,
            'last': last,
            'pnl_idr': pnl_idr,
            'pnl_pct': pnl_pct,
            'sl': p.get('sl_price'),
            'tp1': p.get('tp1_price'),
            'tp1_hit': bool(p.get('tp1_hit')),
            'err': err,
        })

    enriched.sort(key=lambda x: (x['pnl_idr'] or 0), reverse=True)

    return {
        'positions': enriched,
        'total_pnl_idr': total_pnl_idr,
        'total_cost_idr': total_cost_idr,
        'total_pnl_pct': (total_pnl_idr / total_cost_idr * 100) if total_cost_idr > 0 else None,
    }


def fetch_btc_health(ex):
    if not getattr(bot, 'ENABLE_BTC_FILTER', False):
        return None, 'BTC filter disabled'
    try:
        inst = bot.ProfessionalBot.__new__(bot.ProfessionalBot)
        inst.indodax = ex
        inst.all_markets = safe_call(ex.load_markets)[0] or {}
        ok = inst.is_market_healthy()
        return bool(ok), None
    except Exception as e:
        return None, str(e)


def check_indodax_connection(ex):
    # 1) Public check
    t, err = safe_call(ex.fetch_time)
    if err:
        return {"public_ok": False, "private_ok": False, "msg": f"Public FAIL: {err}"}

    # 2) Private check (auth)
    b, err = safe_call(ex.fetch_balance)
    if err:
        return {"public_ok": True, "private_ok": False, "msg": f"Private FAIL: {err}"}

    return {"public_ok": True, "private_ok": True, "msg": "Public OK, Private OK"}


def render(start_ts):
    refresh_s = float(os.environ.get('UI_REFRESH', '0') or 0)
    top_assets = int(os.environ.get('UI_TOP_ASSETS', '15') or 15)

    running, pid = bot_is_running()

    ex = build_indodax_client()
    markets, _ = safe_call(ex.load_markets)
    markets = markets or {}

    positions, pos_err = load_positions_state()
    acct, acct_err = fetch_account_snapshot(ex, markets=markets, top_n=top_assets)
    pstat = compute_positions_status(ex, positions)
    btc_ok, btc_err = fetch_btc_health(ex)

    uptime = int(time.time() - start_ts)
    conn = check_indodax_connection(ex)

    clear_screen()
    print('     ╔[==  CuanBot v.1  ==]╗')
    print('     ╚[===================]╝')
    print(f"WIB: {wib_ts()} | Uptime: {uptime}s")
    print(f"Koneksi Indodax    : {conn['msg']}")
    print('')

    print('== Status Bot ==')
    print(f"SIMULATION_MODE    : {getattr(bot, 'SIMULATION_MODE', None)}")
    print(f"ENABLE_BTC_FILTER  : {getattr(bot, 'ENABLE_BTC_FILTER', None)}")
    print(f"SCAN_INTERVAL      : {getattr(bot, 'SCAN_OPPORTUNITIES_INTERVAL', None)}")
    print(f"STATUS_INTERVAL    : {getattr(bot, 'STATUS_UPDATE_INTERVAL', None)}")
    print(f"STATE_FILE         : {getattr(bot, 'STATE_FILE', None)}")
    print(f"BOT_LOG_FILE       : {getattr(bot, 'LOG_FILE', None)}")
    print(f"API key/secret ok  : {api_config_status()}")
    print(f"Process running    : {running} (pid={pid if pid else '-'})")
    if btc_ok is not None:
        print(f"BTC market healthy : {btc_ok}")
    elif btc_err:
        print(f"BTC health error   : {btc_err}")
    print('')

    print('== Status Trading ==')
    if pos_err:
        print(f"State error        : {pos_err}")
    print(f"Open positions     : {len(positions)}")
    tpct = pstat.get('total_pnl_pct')
    print(f"Floating PnL (IDR) : {human_int(pstat['total_pnl_idr'])}")
    print(f"Floating PnL (%)   : {tpct:.2f}%" if tpct is not None else "Floating PnL (%)   : -")

    if pstat['positions']:
        print('')
        print('Top positions:')
        for x in pstat['positions'][:5]:
            last_s = human_int(x['last']) if x['last'] else '-'
            pnl_idr = human_int(x['pnl_idr']) if x['pnl_idr'] is not None else '-'
            pnl_pct = f"{x['pnl_pct']:+.2f}%" if x['pnl_pct'] is not None else '-'
            tp1hit = 'Y' if x['tp1_hit'] else 'N'
            print(f"- {x['pair']:<10} last={last_s:<12} pnl={pnl_idr:<12} ({pnl_pct}) tp1={tp1hit}")
            if x['err']:
                print(f"  err: {x['err']}")
    print('')

    print('== Status Akun Indodax ==')

    if acct_err:
        print(f"Account error      : {acct_err}")
    else:
        print(f"IDR free           : {human_int(acct['idr_free'])}")
        print(f"IDR total          : {human_int(acct['idr_total'])}")
        print(f"Estimasi total IDR : {human_int(acct['est_total_idr'])}")
        print('')
        print(f"Top assets (by value, max {top_assets}):")
        for a in acct['assets']:
            last = human_int(a['last_idr']) if a['last_idr'] else '-'
            val = human_int(a['value_idr']) if a['value_idr'] else '-'
            print(f"- {a['asset']:<6} total={human_float(a['total'], 8):<14} free={human_float(a['free'], 8):<14} last={last:<12} value={val:<14} {a['status']}")

    print('')
    if refresh_s and refresh_s > 0:
        print(f"Auto refresh: {refresh_s}s | Commands: start | stop | q")
    else:
        print('Commands: [Enter]=refresh | start | stop | q')

atexit.register(cleanup_on_exit)

def _signal_handler(signum, frame):
    cleanup_on_exit()
    raise SystemExit(0)

signal.signal(signal.SIGINT, _signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, _signal_handler)  # terminate


def main():
    start_ts = time.time()

    while True:
        render(start_ts)

        refresh_s = float(os.environ.get('UI_REFRESH', '0') or 0)
        if refresh_s and refresh_s > 0:
            time.sleep(refresh_s)
            continue

        try:
            cmd = input('> ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            cleanup_on_exit()
            print('\nExit.')
            return

        if cmd in ('q', 'quit', 'exit'):
            cleanup_on_exit()
            print('Exit.')
            return


        if cmd == 'start':
            ok, msg = start_bot()
            print(msg)
            time.sleep(1)
            continue

        if cmd == 'stop':
            ok, msg = stop_bot()
            print(msg)
            time.sleep(1)
            continue


if __name__ == '__main__':
    main()
