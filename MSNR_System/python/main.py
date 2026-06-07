import time, logging, sys, os
import pandas as pd
import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(__file__))
from config import (SYMBOL, PRIMARY_TF, LOOKBACK_BARS, LOG_FILE,
                    MT5_PATH, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER,
                    FIXED_SL_USD, TRAIL_TRIGGER, TRAIL_LOCK_USD)
from msnr_detector import MSNRDetector
from trendline import TrendlineEngine
from signal_generator import SignalGenerator, calc_lot
from telegram_notify import (send_signal_alert, send_order_executed,
                              send_trail_activated, send_order_closed,
                              test_connection)

MAGIC = 20260607
# Track last signal sent to Telegram — tranh duplicate notification
g_last_tg_signal = {'action': None, 'entry': None}
# EA saves screenshot to Common\Files — this is the fixed path on this VPS
COMMON_FILES    = r"C:\Users\durable1\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
SCREENSHOT_PATH = os.path.join(COMMON_FILES, "msnr_chart.png")
LAST_SCREENSHOT_MTIME = 0.0

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("MSNR.Main")

TF_MAP = {
    "M1":mt5.TIMEFRAME_M1,"M5":mt5.TIMEFRAME_M5,
    "M15":mt5.TIMEFRAME_M15,"M30":mt5.TIMEFRAME_M30,
    "H1":mt5.TIMEFRAME_H1,"H4":mt5.TIMEFRAME_H4,"D1":mt5.TIMEFRAME_D1,
}

# ticket -> {action, price_open, sl, tp, volume, trail_notified}
g_positions = {}


def get_new_screenshot():
    """Tra ve path neu co screenshot moi tu EA, None neu khong"""
    global LAST_SCREENSHOT_MTIME
    if not os.path.exists(SCREENSHOT_PATH):
        return None
    mtime = os.path.getmtime(SCREENSHOT_PATH)
    if mtime > LAST_SCREENSHOT_MTIME:
        LAST_SCREENSHOT_MTIME = mtime
        return SCREENSHOT_PATH
    return None


def monitor_positions():
    global LAST_SCREENSHOT_MTIME
    positions = mt5.positions_get(symbol=SYMBOL) or []
    current   = set()

    for pos in positions:
        if pos.magic != MAGIC:
            continue
        ticket = pos.ticket
        current.add(ticket)
        action = "BUY" if pos.type == 0 else "SELL"

        pos_info = {
            "ticket"    : ticket,
            "action"    : action,
            "price_open": pos.price_open,
            "sl"        : pos.sl,
            "tp"        : pos.tp,
            "volume"    : pos.volume,
        }

        if ticket not in g_positions:
            # New position — wait briefly for EA to take screenshot
            log.info(f"New position #{ticket} {action} @ {pos.price_open}")
            g_positions[ticket] = {**pos_info, "trail_notified": False}
            time.sleep(3)   # give EA time to save screenshot
            screenshot = get_new_screenshot()
            send_order_executed(pos_info, screenshot)
        else:
            # Check trail 1R activation
            prev = g_positions[ticket]
            if not prev["trail_notified"]:
                if action == "BUY"  and pos.sl >= pos.price_open:
                    send_trail_activated(pos_info, pos.sl)
                    g_positions[ticket]["trail_notified"] = True
                elif action == "SELL" and 0 < pos.sl <= pos.price_open:
                    send_trail_activated(pos_info, pos.sl)
                    g_positions[ticket]["trail_notified"] = True
            g_positions[ticket]["sl"] = pos.sl

    # Closed positions
    for ticket in list(g_positions.keys()):
        if ticket not in current:
            prev = g_positions.pop(ticket)
            log.info(f"Position #{ticket} closed")
            pnl, close_price = 0.0, 0.0
            try:
                deals = mt5.history_deals_get(position=ticket)
                if deals:
                    for d in deals:
                        pnl += d.profit + d.swap + d.commission
                        if d.entry == 1:
                            close_price = d.price
            except Exception:
                pass
            send_order_closed(prev, close_price, pnl)


def _should_notify_telegram(signal):
    """
    Skip Telegram signal alert neu:
    1. Dang co lenh mo (khong spam khi dang trong trade)
    2. Tin hieu trung lap (cung action + entry voi lan gui truoc)
    """
    global g_last_tg_signal

    # Rule 1: skip neu dang co position voi magic MSNR
    positions = mt5.positions_get(symbol=SYMBOL) or []
    if any(p.magic == MAGIC for p in positions):
        log.info("TG skip: dang co lenh mo — khong gui signal moi")
        return False

    # Rule 2: skip neu trung lap (cung action + entry)
    if (signal.get('action') == g_last_tg_signal['action'] and
            signal.get('entry') == g_last_tg_signal['entry']):
        log.info("TG skip: tin hieu trung lap — da gui roi")
        return False

    return True


def connect_mt5():
    for attempt, kwargs in enumerate([
        {},
        {"path": MT5_PATH},
        {"path": MT5_PATH, "login": MT5_LOGIN,
         "password": MT5_PASSWORD, "server": MT5_SERVER},
    ], 1):
        if mt5.initialize(**kwargs):
            info = mt5.account_info()
            if info:
                log.info(f"MT5 OK (attempt {attempt}) | "
                         f"Account:{info.login} Balance:{info.balance}")
                return True
            mt5.shutdown()
    log.error(f"MT5 init failed: {mt5.last_error()}")
    return False


def get_ohlcv(symbol, tf, n):
    rates = mt5.copy_rates_from_pos(symbol, TF_MAP[tf], 0, n)
    if rates is None or len(rates) == 0:
        log.warning(f"No data {symbol} {tf}")
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def run_cycle():
    df = get_ohlcv(SYMBOL, PRIMARY_TF, LOOKBACK_BARS)
    if df.empty:
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        mt5.symbol_select(SYMBOL, True)
        return

    price   = tick.bid
    info    = mt5.account_info()
    balance = info.balance if info else 10000.0

    log.info(f"Cycle | {SYMBOL} Price:{price:.2f} | Balance:{balance:.2f}")

    detector   = MSNRDetector(df)
    levels     = detector.detect_all()
    fresh      = detector.get_fresh_levels()
    log.info(f"Levels:{len(levels)} | Fresh:{len(fresh)}")

    tl_engine  = TrendlineEngine(df, levels)
    trendlines = tl_engine.detect()
    p3s        = tl_engine.get_active_p3_signals(trendlines)
    log.info(f"Trendlines:{len(trendlines)} | P3:{len(p3s)}")

    sg     = SignalGenerator(detector, tl_engine, price, balance)
    signal = sg.generate(trendlines)

    if signal:
        log.info(f"SIGNAL {signal['action']} Entry:{signal['entry']} "
                 f"SL:{signal['sl']} TP:{signal['tp']} RR:{signal['rr']}:1")
        if _should_notify_telegram(signal):
            send_signal_alert(signal)
            g_last_tg_signal['action'] = signal['action']
            g_last_tg_signal['entry']  = signal['entry']
        # else: signal van ghi ra file cho EA, chi bo qua TG thoi
    else:
        # Reset tracker khi het setup
        g_last_tg_signal['action'] = None
        g_last_tg_signal['entry']  = None
        log.info("No setup this cycle")

    sg.write_signal(signal)
    monitor_positions()


def main():
    log.info("=" * 55)
    log.info("MSNR v2.3 | Chart drawing + Detailed analysis")
    log.info("=" * 55)

    retries = 0
    while not connect_mt5():
        retries += 1
        if retries > 5:
            log.critical("Cannot connect MT5"); sys.exit(1)
        log.warning(f"Retry {retries}/5 in 30s..."); time.sleep(30)

    mt5.symbol_select(SYMBOL, True)
    ok = test_connection()
    log.info(f"Telegram: {'OK' if ok else 'FAILED'}")

    try:
        while True:
            try:
                run_cycle()
            except Exception as e:
                log.exception(f"Cycle error: {e}")
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
