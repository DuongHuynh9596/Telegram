import time, logging, sys, os
from datetime import datetime, timedelta
import pandas as pd
import MetaTrader5 as mt5

# stdout/stderr utf-8 (tranh UnicodeEncodeError khi console codepage = cp1252)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(__file__))
from config import (SYMBOL, PRIMARY_TF, LOOKBACK_BARS, LOG_FILE,
                    MT5_PATH, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER,
                    FIXED_SL_USD, FIXED_TP_USD, TRAIL_TRIGGER, TRAIL_LOCK_USD,
                    ZONE_MAX_TRADES, ZONE_BLOCK_HOURS, ZONE_BLOCK_TOL,
                    USE_STORYLINE, STORYLINE_TFS, STORYLINE_BARS,
                    ENTRY_TFS, ENTRY_BARS,
                    NO_TRADE_GMT7_START, NO_TRADE_GMT7_END)
from msnr_detector import MSNRDetector
from trendline import TrendlineEngine
from signal_generator import SignalGenerator, calc_lot
from storyline import build_storyline
from chart_generator import generate as generate_chart
from telegram_notify import (send_signal_alert, send_trail_activated,
                              send_order_closed, test_connection)

MAGIC        = 20260607
COMMON_FILES = r"C:\Users\durable1\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
SCREENSHOT_PATH = os.path.join(COMMON_FILES, "msnr_chart.png")
LAST_SS_MTIME   = 0.0

SYMBOL_CANDIDATES = ["XAUUSDm", "XAUUSD", "XAUUSDmicro"]

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
g_positions      = {}
g_startup_tickets = set()   # tickets da ton tai khi Python khoi dong (khong gui TG)
# Zone tracking: {action, entry, count, last_close, until}
# count = so lenh DA DONG tu zone nay; until > 0 = zone dang bi khoa
g_blocked_zone    = None

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


def enforce_fixed_risk():
    """
    Khu entry-drift: voi moi lenh MSNR dang mo CHUA trail (SL con phia lo),
    dat lai SL = entry ∓ FIXED_SL_USD, TP = entry ± FIXED_TP_USD theo GIA KHOP THAT.
    -> SL distance luon dung $12 -> risk = SL$ x lot x 100 (khong bi phinh do fill lech).
    Bo qua lenh dang crash-ride (tp==0) va lenh da BE/trail (SL qua entry).
    """
    positions = mt5.positions_get(symbol=SYMBOL) or []
    for pos in positions:
        if pos.magic != MAGIC:
            continue
        if pos.tp == 0:                       # crash-ride (EA da thao TP) -> bo qua
            continue
        entry  = pos.price_open
        is_buy = (pos.type == 0)
        # Da BE/trail? (SL qua entry ve phia loi) -> bo qua, de EA trail
        if is_buy and pos.sl != 0 and pos.sl >= entry:
            continue
        if (not is_buy) and pos.sl != 0 and pos.sl <= entry:
            continue
        sl_dist = (entry - pos.sl) if (is_buy and pos.sl != 0) else \
                  (pos.sl - entry) if ((not is_buy) and pos.sl != 0) else 999.0
        if abs(sl_dist - FIXED_SL_USD) <= 0.5:   # distance da dung -> thoi
            continue
        new_sl = round(entry - FIXED_SL_USD, 2) if is_buy else round(entry + FIXED_SL_USD, 2)
        new_tp = round(entry + FIXED_TP_USD, 2) if is_buy else round(entry - FIXED_TP_USD, 2)
        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": SYMBOL,
               "position": pos.ticket, "sl": new_sl, "tp": new_tp}
        r  = mt5.order_send(req)
        ok = bool(r) and r.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"Enforce risk: {'BUY' if is_buy else 'SELL'} #{pos.ticket} "
                 f"SLdist {sl_dist:.2f}->{FIXED_SL_USD:.0f} | SL={new_sl} TP={new_tp} | "
                 f"ok={ok}{'' if ok else ' ret='+str(getattr(r,'retcode','?'))}")


def monitor_positions():
    """
    Khi EA vao lenh moi:
      1. Tao chart (Python-generated dark theme)
      2. Gui Telegram: analysis + chart (1 tin duy nhat)
    Khi trail 1R: gui update SL
    Khi dong lenh: gui P&L
    """
    global g_positions, g_blocked_zone

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
            g_positions[ticket] = {**pos_info, "trail_notified": False}

            # Bo qua lenh cu da ton tai truoc khi Python khoi dong
            if ticket in g_startup_tickets:
                log.info(f"Startup position #{ticket} {action} @ {pos.price_open} — skip TG")
                continue

            # ── Lenh moi thuc su: EA vua action ──────────────────
            log.info(f"EA action: new position #{ticket} {action} @ {pos.price_open}")

            # Doi EA chup screenshot (neu co)
            time.sleep(3)
            ea_screenshot = get_ea_screenshot()
            chart_path = ea_screenshot

            # Python-generated chart — chi dung khi g_last_signal CUNG CHIEU voi position
            if (not chart_path
                    and g_last_df is not None
                    and g_last_signal is not None
                    and g_last_signal.get("action") == action):  # ← phai cung chieu
                py_signal = dict(g_last_signal)
                py_signal["entry"] = pos.price_open
                py_signal["sl"]    = pos.sl
                py_signal["tp"]    = pos.tp
                chart_path = generate_chart(
                    g_last_df, py_signal, g_last_fresh, g_last_trendlines
                )

            # Signal data: dung g_last_signal neu cung chieu, khong thi dung position data
            if g_last_signal and g_last_signal.get("action") == action:
                signal_data = dict(g_last_signal)
            else:
                signal_data = {
                    "action"        : action,
                    "entry"         : pos.price_open,
                    "sl"            : pos.sl,
                    "tp"            : pos.tp,
                    "lot"           : pos.volume,
                    "sl_usd"        : FIXED_SL_USD,
                    "rr"            : round(abs(pos.tp - pos.price_open) / FIXED_SL_USD, 1),
                    "confluence"    : 3,
                    "p3_trendline"  : True,
                    "fresh_level"   : True,
                    "gap_snr"       : True,
                    "analysis_items": [],
                    "analysis_tf"   : PRIMARY_TF,
                }

            signal_data["ticket"] = ticket
            signal_data["entry"]  = pos.price_open
            signal_data["sl"]     = pos.sl
            signal_data["tp"]     = pos.tp
            signal_data["lot"]    = pos.volume

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

            # ── Zone tracking: toi da ZONE_MAX_TRADES lenh / zone ────
            now = time.time()
            same_zone = (g_blocked_zone is not None
                         and g_blocked_zone["action"] == prev["action"]
                         and abs(prev["price_open"] - g_blocked_zone["entry"]) <= ZONE_BLOCK_TOL
                         and now - g_blocked_zone["last_close"] <= ZONE_BLOCK_HOURS * 3600)
            if same_zone:
                g_blocked_zone["count"]     += 1
                g_blocked_zone["last_close"] = now
                if g_blocked_zone["count"] >= ZONE_MAX_TRADES:
                    g_blocked_zone["until"] = now + ZONE_BLOCK_HOURS * 3600
                    log.info(f"Zone LOCKED: {prev['action']} ~{g_blocked_zone['entry']:.2f} "
                             f"(±${ZONE_BLOCK_TOL}) — {g_blocked_zone['count']} trades done, "
                             f"locked {ZONE_BLOCK_HOURS}h")
                else:
                    log.info(f"Zone trade {g_blocked_zone['count']}/{ZONE_MAX_TRADES}: "
                             f"{prev['action']} ~{g_blocked_zone['entry']:.2f} — con luot vao lai")
            else:
                g_blocked_zone = {
                    "action"    : prev["action"],
                    "entry"     : prev["price_open"],
                    "count"     : 1,
                    "last_close": now,
                    "until"     : 0,
                }
                log.info(f"Zone trade 1/{ZONE_MAX_TRADES}: {prev['action']} "
                         f"~{prev['price_open']:.2f} (±${ZONE_BLOCK_TOL}) — con luot vao lai")
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


def detect_symbol():
    """
    Tu dong tim symbol XAUUSD hop le tren account nay.
    1. Lay danh sach tat ca symbol chua 'XAU' tu terminal
    2. Thu tung symbol co data H1 thuc su
    3. Retry toi da 30s neu data feed chua san sang
    """
    global SYMBOL
    for attempt in range(1, 7):          # thu toi da 6 lan, moi lan cach 5s
        # Uu tien candidate list truoc
        candidates = list(SYMBOL_CANDIDATES)

        # Bo sung tu danh sach symbol that cua terminal (loc XAU*)
        all_syms = mt5.symbols_get()
        if all_syms:
            xau_syms = [s.name for s in all_syms if "XAU" in s.name.upper()]
            for s in xau_syms:
                if s not in candidates:
                    candidates.append(s)
            if xau_syms:
                log.info(f"XAU symbols on account: {xau_syms}")
        else:
            log.warning(f"symbols_get() returned None | error: {mt5.last_error()}")

        for sym in candidates:
            mt5.symbol_select(sym, True)
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 5)
            if rates is not None and len(rates) > 0:
                if sym != SYMBOL:
                    log.info(f"Symbol auto-detected: {sym} (was '{SYMBOL}') — switching")
                    SYMBOL = sym
                else:
                    log.info(f"Symbol OK: {sym}")
                return True

        log.warning(f"Attempt {attempt}/6: data feed not ready yet — retrying in 5s...")
        time.sleep(5)

    log.error(f"No valid XAU symbol found after retries. Last error: {mt5.last_error()}")
    return False


def diagnose_mt5():
    """Log day du thong tin MT5 de debug."""
    term = mt5.terminal_info()
    if term:
        log.info(f"Terminal: build={term.build} connected={term.connected} "
                 f"trade_allowed={term.trade_allowed} path={term.data_path}")
    acc = mt5.account_info()
    if acc:
        log.info(f"Account: login={acc.login} server={acc.server} "
                 f"balance={acc.balance:.2f} trade_mode={acc.trade_mode}")
    # Kiem tra xem symbols_get co hoat dong khong
    syms = mt5.symbols_get()
    if syms:
        xau = [s.name for s in syms if "XAU" in s.name.upper()]
        log.info(f"XAU symbols available ({len(xau)}): {xau}")
    else:
        log.warning(f"symbols_get() = None | error: {mt5.last_error()}")
    # Thu truc tiep symbol_info
    for sym in ["XAUUSDm", "XAUUSD"]:
        info = mt5.symbol_info(sym)
        log.info(f"symbol_info({sym}): {info}")


def connect_mt5():
    """
    Initial connection — ACCOUNT-AGNOSTIC: bám vào terminal đang chạy và DÙNG
    TÀI KHOẢN ĐANG LOGIN SẴN (không ép login theo config). Không tự logout.
    """
    # Thu 1: path only (dua vao session terminal hien co)
    if mt5.initialize(path=MT5_PATH):
        info = mt5.account_info()
        if info and info.login:
            log.info(f"MT5 OK (path-only) | Logged-in account: {info.login} "
                     f"Server:{info.server} Balance:{info.balance:.2f}")
            diagnose_mt5()
            return True
        mt5.shutdown()
    # Thu 2: attach terminal dang chay (khong path)
    log.info("Path-only no account yet - try attach running terminal...")
    if mt5.initialize():
        info = mt5.account_info()
        if info and info.login:
            log.info(f"MT5 OK (attach) | Logged-in account: {info.login} "
                     f"Server:{info.server} Balance:{info.balance:.2f}")
            diagnose_mt5()
            return True
        mt5.shutdown()
    log.error(f"MT5 init failed (terminal not logged in?): {mt5.last_error()}")
    return False


def check_and_reconnect_mt5():
    """Runtime reconnect — ACCOUNT-AGNOSTIC: never shutdown/logout, chấp nhận
    bất kỳ account nào đang login trên terminal."""
    term = mt5.terminal_info()
    if term:
        acc = mt5.account_info()
        if acc and acc.login:
            return True
    for attempt in range(1, 21):
        log.warning(f"MT5 reconnect attempt {attempt}/20...")
        if mt5.initialize(path=MT5_PATH) or mt5.initialize():
            acc = mt5.account_info()
            if acc and acc.login:
                mt5.symbol_select(SYMBOL, True)
                log.info(f"MT5 reconnected | Account:{acc.login}")
                return True
        time.sleep(30)
    log.error("MT5 reconnect failed after 20 attempts — will retry next cycle")
    return False


def get_ohlcv(symbol, tf, n):
    rates = mt5.copy_rates_from_pos(symbol, TF_MAP[tf], 0, n)
    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        log.warning(f"No data {symbol} {tf} | MT5 error: {err}")
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def run_cycle():
    global g_last_signal, g_last_df, g_last_fresh, g_last_trendlines

    # Dam bao symbol luon co trong Market Watch truoc khi fetch data
    if not mt5.symbol_select(SYMBOL, True):
        log.warning(f"symbol_select({SYMBOL}) failed | MT5 error: {mt5.last_error()}")

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        mt5.symbol_select(SYMBOL, True)
        return

    price   = tick.bid
    info    = mt5.account_info()
    balance = info.balance if info else 10000.0

    # Tai du lieu tat ca khung entry
    dfs = {}
    for tf in ENTRY_TFS:
        d = get_ohlcv(SYMBOL, tf, ENTRY_BARS)
        if not d.empty:
            dfs[tf] = d
    if not dfs:
        return

    log.info(f"Cycle | {SYMBOL} Price:{price:.2f} | Balance:{balance:.2f}")

    vn_hour     = (datetime.utcnow() + timedelta(hours=7)).hour
    in_no_trade = NO_TRADE_GMT7_START <= vn_hour < NO_TRADE_GMT7_END
    if in_no_trade:
        log.info(f"No-trade window: phien sang GMT+7 [{NO_TRADE_GMT7_START}-"
                 f"{NO_TRADE_GMT7_END}h) (VN {vn_hour}h) — chi quan ly lenh, KHONG vao moi")

    # ── MTF Storyline: bias D1→H4 (+H1 context cho roadblock) ──
    storyline = None
    if USE_STORYLINE:
        tf_data = {}
        for tf in STORYLINE_TFS:
            sdf = get_ohlcv(SYMBOL, tf, STORYLINE_BARS)
            if not sdf.empty:
                tf_data[tf] = sdf
        if PRIMARY_TF in dfs:
            tf_data[PRIMARY_TF] = dfs[PRIMARY_TF]
        if tf_data:
            storyline = build_storyline(tf_data, price)
            log.info(f"Storyline | {storyline.summary()}")

    # ── Quet entry tung khung theo UU TIEN KHUNG LON; khung dau co setup thang ──
    signal = None
    sg     = None
    sel_df = sel_fresh = sel_tls = None
    for tf in ENTRY_TFS:
        if in_no_trade:
            break
        if tf not in dfs:
            continue
        d   = dfs[tf]
        det = MSNRDetector(d)
        det.detect_all()
        tle = TrendlineEngine(d, det.levels)
        tls = tle.detect()
        sg  = SignalGenerator(det, tle, price, balance, storyline=storyline, tf=tf)
        s   = sg.generate(tls)
        log.info(f"  [{tf}] Levels:{len(det.levels)} Fresh:{len(det.get_fresh_levels())} "
                 f"TL:{len(tls)} -> {('SETUP '+s['action']) if s else 'none'}")

        # Zone LOCKED -> bo qua setup khung nay, thu khung nho hon
        if s and g_blocked_zone and g_blocked_zone["until"] > time.time() \
                and s["action"] == g_blocked_zone["action"] \
                and abs(s["entry"] - g_blocked_zone["entry"]) <= ZONE_BLOCK_TOL:
            log.info(f"  [{tf}] {s['action']} @ {s['entry']:.2f} — zone locked, skip")
            s = None

        if s:
            signal    = s
            sel_df    = d
            sel_fresh = det.get_fresh_levels()
            sel_tls   = tls
            break   # uu tien khung lon

    if signal:
        log.info(f"Setup [{signal.get('entry_tf','?')}]: {signal['action']} "
                 f"Entry:{signal['entry']} SL:{signal['sl']} TP:{signal['tp']} "
                 f"RR:{signal['rr']}:1 ({signal.get('entry_type')}/{signal.get('order_type')}) "
                 f"— waiting for EA...")
        g_last_signal     = signal
        g_last_df         = sel_df.copy()
        g_last_fresh      = sel_fresh
        g_last_trendlines = sel_tls
    else:
        log.info("No setup this cycle")
        g_last_signal = None

    SignalGenerator.write_signal(signal)

    enforce_fixed_risk()   # khu entry-drift: SL/TP = entry +- fixed -> risk dung <1%

    # Monitor: phat hien EA vao lenh -> moi gui Telegram
    monitor_positions()


def main():
    global g_startup_tickets

    log.info("=" * 55)
    log.info("MSNR v3.0 | Storyline MTF + QM/411 + Rejection + 2 Entry (CONFIRMED/LIMIT)")
    log.info("=" * 55)

    retries = 0
    while not connect_mt5():
        retries += 1
        if retries > 10:
            log.critical("Cannot connect MT5"); sys.exit(1)
        log.warning(f"Retry {retries}/10 in 30s..."); time.sleep(30)

    detect_symbol()
    ok = test_connection()
    log.info(f"Telegram: {'OK' if ok else 'FAILED'}")

    # Scan lenh dang mo TRUOC KHI vao loop
    # -> danh dau la startup positions, KHONG gui Telegram cho nhung lenh nay
    existing = mt5.positions_get(symbol=SYMBOL) or []
    for pos in existing:
        if pos.magic == MAGIC:
            g_startup_tickets.add(pos.ticket)
            log.info(f"Startup position found: #{pos.ticket} "
                     f"{'BUY' if pos.type==0 else 'SELL'} @ {pos.price_open} — will not notify")

    try:
        while True:
            try:
                if not check_and_reconnect_mt5():
                    log.warning("MT5 not available — skipping cycle, will retry in 60s")
                    time.sleep(60)
                    continue
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
