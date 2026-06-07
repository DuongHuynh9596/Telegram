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
from chart_generator import generate as generate_chart
from telegram_notify import (send_signal_alert, send_trail_activated,
                              send_order_closed, test_connection)

MAGIC        = 20260607
COMMON_FILES = r"C:\Users\durable1\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
SCREENSHOT_PATH = os.path.join(COMMON_FILES, "msnr_chart.png")
LAST_SS_MTIME   = 0.0

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
    "M1":mt5.TIMEFRAME_M1,  "M5":mt5.TIMEFRAME_M5,
    "M15":mt5.TIMEFRAME_M15,"M30":mt5.TIMEFRAME_M30,
    "H1":mt5.TIMEFRAME_H1,  "H4":mt5.TIMEFRAME_H4,
    "D1":mt5.TIMEFRAME_D1,
}

# ── State ─────────────────────────────────────────────────────────
# ticket -> {action, price_open, sl, tp, volume, trail_notified}
g_positions = {}

# Luu du lieu cycle gan nhat de dung khi EA vao lenh
g_last_signal      = None   # signal dict
g_last_df          = None   # OHLCV dataframe
g_last_fresh       = []     # fresh levels
g_last_trendlines  = []     # trendlines


def get_ea_screenshot():
    """Doc screenshot tu EA (Common Files), None neu khong co moi"""
    global LAST_SS_MTIME
    if not os.path.exists(SCREENSHOT_PATH):
        return None
    mtime = os.path.getmtime(SCREENSHOT_PATH)
    if mtime > LAST_SS_MTIME:
        LAST_SS_MTIME = mtime
        return SCREENSHOT_PATH
    return None


def monitor_positions():
    """
    Khi EA vao lenh moi:
      1. Tao chart (Python-generated dark theme)
      2. Gui Telegram: analysis + chart (1 tin duy nhat)
    Khi trail 1R: gui update SL
    Khi dong lenh: gui P&L
    """
    global g_positions

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
            # ── Lenh moi: EA vua action ───────────────────────────
            log.info(f"EA action: new position #{ticket} {action} @ {pos.price_open}")
            g_positions[ticket] = {**pos_info, "trail_notified": False}

            # Doi EA chup screenshot (neu co)
            time.sleep(3)
            ea_screenshot = get_ea_screenshot()

            # Chon chart tot nhat: EA screenshot > Python-generated
            chart_path = ea_screenshot

            if not chart_path and g_last_df is not None and g_last_signal is not None:
                # Dung Python chart neu EA chua kip chup
                py_signal = dict(g_last_signal)
                # Cap nhat entry chinh xac tu MT5 (gia thuc te vao lenh)
                py_signal["entry"] = pos.price_open
                py_signal["sl"]    = pos.sl
                py_signal["tp"]    = pos.tp
                chart_path = generate_chart(
                    g_last_df, py_signal, g_last_fresh, g_last_trendlines
                )

            # Gui 1 tin duy nhat: analysis + chart
            signal_data = g_last_signal or {
                "action"        : action,
                "entry"         : pos.price_open,
                "sl"            : pos.sl,
                "tp"            : pos.tp,
                "lot"           : pos.volume,
                "sl_usd"        : FIXED_SL_USD,
                "rr"            : round(abs(pos.tp - pos.price_open) / FIXED_SL_USD, 1),
                "confluence"    : 0,
                "p3_trendline"  : False,
                "fresh_level"   : False,
                "analysis_items": [],
                "analysis_tf"   : PRIMARY_TF,
            }
            # Gan ticket vao signal de hien thi
            signal_data = dict(signal_data)
            signal_data["ticket"]      = ticket
            signal_data["entry"]       = pos.price_open
            signal_data["sl"]          = pos.sl
            signal_data["tp"]          = pos.tp
            signal_data["lot"]         = pos.volume

            send_signal_alert(signal_data, chart_path)

        else:
            # ── Check trail 1R ────────────────────────────────────
            prev = g_positions[ticket]
            if not prev["trail_notified"]:
                if action == "BUY"  and pos.sl >= pos.price_open:
                    send_trail_activated(pos_info, pos.sl)
                    g_positions[ticket]["trail_notified"] = True
                elif action == "SELL" and 0 < pos.sl <= pos.price_open:
                    send_trail_activated(pos_info, pos.sl)
                    g_positions[ticket]["trail_notified"] = True
            g_positions[ticket]["sl"] = pos.sl

    # ── Lenh da dong ─────────────────────────────────────────────
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
    global g_last_signal, g_last_df, g_last_fresh, g_last_trendlines

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
        log.info(f"Setup found: {signal['action']} Entry:{signal['entry']} "
                 f"SL:{signal['sl']} TP:{signal['tp']} RR:{signal['rr']}:1 "
                 f"— waiting for EA to action...")
        # Luu lai de dung khi EA vao lenh
        g_last_signal     = signal
        g_last_df         = df.copy()
        g_last_fresh      = fresh
        g_last_trendlines = trendlines
    else:
        log.info("No setup this cycle")
        g_last_signal = None   # reset khi khong con setup

    sg.write_signal(signal)

    # Monitor: phat hien EA vao lenh -> moi gui Telegram
    monitor_positions()


def main():
    log.info("=" * 55)
    log.info("MSNR v2.5 | Notify on EA action only")
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
