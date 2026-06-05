#!/usr/bin/env python3
# XAUUSD Macro Signal Analyzer
# Doc US10Y, DXY, VIX, SILVER, XAUUSD tu yfinance | Phan tich voi Claude
# HOLD: khong gui Telegram | Dao chieu: dong vi tri cu truoc khi mo moi
# Quan ly von: 3 vi tri, partial close + doi BE+50pts

import json, time, schedule, requests, subprocess, base64, os, re
import yfinance as yf
import MetaTrader5 as mt5
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIG
# ============================================================
TELEGRAM_TOKEN   = "8945392493:AAF593FIi70bhrGIc52U01F_YcUnC15liWA"
TELEGRAM_CHAT_ID = "-1003967823435"
CDP_PORT         = 9222
LOT_SIZE         = 0.01
NUM_POSITIONS    = 3        # so vi tri mo moi signal
PARTIAL_CLOSE_AT = 20       # dong 1 vi tri khi lai >= 20 points
BE_BUFFER        = 50       # doi SL ve BE + 50 points sau partial close
MIN_CONFIDENCE   = 60
MAGIC            = 20240101

# MT5 account — dien vao de Python ket noi dung terminal (tranh bi vao MT5 B)
MT5_LOGIN    = 0       # so tai khoan MT5, vi du: 12345678 (0 = tu dong)
MT5_PASSWORD = ""      # mat khau MT5
MT5_SERVER   = ""      # ten server, vi du: "OANDA-v20 Live-1"

MT5_COMMON = Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / "Common" / "Files"
MT5_COMMON.mkdir(parents=True, exist_ok=True)

SIGNAL_FILE      = MT5_COMMON / "signal.json"
SCREENSHOT_FILE  = MT5_COMMON / "screenshot.png"
LAST_SIGNAL_FILE = MT5_COMMON / "last_signal.json"

# ============================================================
# MT5 INIT HELPER — ket noi dung account, tranh nham MT5 B
# ============================================================
def mt5_init():
    if MT5_LOGIN:
        return mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    return mt5.initialize()

# ============================================================
# CHONG TRUNG TIN HIEU
# ============================================================
def load_last_signal():
    if not LAST_SIGNAL_FILE.exists():
        return None
    try:
        with open(LAST_SIGNAL_FILE, encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def save_last_signal(signal):
    with open(LAST_SIGNAL_FILE, "w", encoding="utf-8") as f:
        json.dump({"signal": signal["signal"], "entry": signal["entry"],
                   "timestamp": datetime.now().isoformat()}, f)

def clear_last_signal():
    # Goi khi het vi tri (SL/TP hit) — cho phep vao lai lenh cung chieu
    try:
        if LAST_SIGNAL_FILE.exists():
            LAST_SIGNAL_FILE.unlink()
    except:
        pass

def is_duplicate(new_signal):
    if new_signal.get("signal") == "HOLD":
        return False
    last = load_last_signal()
    if not last:
        return False
    if last.get("signal") == new_signal.get("signal"):
        print(f"  Tin hieu trung ({new_signal['signal']}) — bo qua Telegram + MT5")
        return True
    return False

# ============================================================
# MACRO DATA
# ============================================================
def get_macro_data():
    tickers = {
        "XAUUSD": "GC=F",
        "DXY":    "DX-Y.NYB",
        "US10Y":  "^TNX",
        "VIX":    "^VIX",
        "SILVER": "SI=F"
    }
    data = {}
    for name, ticker in tickers.items():
        try:
            df = yf.download(ticker, period="3d", interval="1h",
                             progress=False, auto_adjust=True)
            if not df.empty:
                close = df["Close"].squeeze()
                high  = df["High"].squeeze()
                low   = df["Low"].squeeze()
                cur   = float(close.iloc[-1])
                prev  = float(close.iloc[-2])
                data[name] = {
                    "price":      round(cur, 3),
                    "change_pct": round((cur - prev) / prev * 100, 2),
                    "high_24h":   round(float(high.iloc[-24:].max()), 3),
                    "low_24h":    round(float(low.iloc[-24:].min()), 3)
                }
                print(f"  {name}: {data[name]['price']} ({data[name]['change_pct']:+.2f}%)")
        except Exception as e:
            print(f"  Loi {name}: {e}")
    return data

# ============================================================
# SCREENSHOT TRADINGVIEW
# ============================================================
def take_screenshot():
    try:
        import websocket
        pages = requests.get(f"http://localhost:{CDP_PORT}/json", timeout=5).json()
        chart = next((p for p in pages if "tradingview.com/chart" in p.get("url", "")), None)
        if not chart:
            print("  Khong tim thay TradingView chart")
            return None
        ws = websocket.create_connection(chart["webSocketDebuggerUrl"], timeout=10)
        ws.send(json.dumps({
            "id": 1, "method": "Page.captureScreenshot",
            "params": {"format": "png", "quality": 85}
        }))
        result = json.loads(ws.recv())
        ws.close()
        if "result" in result and "data" in result["result"]:
            with open(SCREENSHOT_FILE, "wb") as f:
                f.write(base64.b64decode(result["result"]["data"]))
            print("  Screenshot OK")
            return str(SCREENSHOT_FILE)
    except Exception as e:
        print(f"  Loi screenshot: {e}")
    return None

# ============================================================
# CLAUDE ANALYSIS
# ============================================================
def analyze_with_claude(macro):
    xau    = macro.get("XAUUSD", {})
    dxy    = macro.get("DXY",    {})
    us10y  = macro.get("US10Y",  {})
    vix    = macro.get("VIX",    {})
    silver = macro.get("SILVER", {})

    prompt = f"""Phan tich vi mo XAUUSD. Chi tra ve JSON, khong text khac. Viet analysis bang tieng Viet co dau.

DU LIEU (GC Futures dung de tham khao macro):
- XAUUSD : ${xau.get('price')} ({xau.get('change_pct'):+.2f}%) | H24: ${xau.get('high_24h')} L24: ${xau.get('low_24h')}
- DXY    : {dxy.get('price')} ({dxy.get('change_pct'):+.2f}%)
- US10Y  : {us10y.get('price')}% ({us10y.get('change_pct'):+.2f}%)
- VIX    : {vix.get('price')} ({vix.get('change_pct'):+.2f}%)
- SILVER : ${silver.get('price')} ({silver.get('change_pct'):+.2f}%)

QUY TAC:
- confidence >= 60 va xu huong ro rang -> signal = BUY hoac SELL
- confidence < 60 hoac thi truong khong ro rang -> signal = HOLD

JSON format (chi JSON, khong tinh entry/sl/tp):
{{"signal":"BUY|SELL|HOLD","confidence":50-95,"analysis":"<phan tich bang tieng Viet co dau>"}}"""

    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", prompt],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="ignore"
        )
        match = re.search(r'\{[^{}]*\}', result.stdout, re.DOTALL)
        if match:
            return json.loads(match.group())
        print(f"  Claude output: {result.stdout[:200]}")
    except Exception as e:
        print(f"  Loi Claude: {e}")

    return {"signal": "HOLD", "confidence": 50, "analysis": "Khong phan tich duoc — giu nguyen"}


def get_mt5_symbol():
    for sym in ["XAUUSD", "XAUUSDm", "GOLD", "XAUUSD.", "XAUUSDc"]:
        info = mt5.symbol_info(sym)
        if info is not None:
            return sym
    return None


def get_entry_sl_tp(signal_dir):
    if not mt5_init():
        return None, None, None

    symbol = get_mt5_symbol()
    if not symbol:
        mt5.shutdown()
        return None, None, None

    if not mt5.symbol_info(symbol).visible:
        mt5.symbol_select(symbol, True)
        time.sleep(0.3)

    tick   = mt5.symbol_info_tick(symbol)
    digits = int(mt5.symbol_info(symbol).digits)
    mt5.shutdown()

    if signal_dir == "BUY":
        entry = round(tick.ask, digits)
        sl    = round(entry - 15, digits)
        tp    = round(entry + 30, digits)
    else:
        entry = round(tick.bid, digits)
        sl    = round(entry + 15, digits)
        tp    = round(entry - 30, digits)

    return entry, sl, tp

# ============================================================
# MT5 UTILITIES
# ============================================================
def get_filling_type(symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_IOC
    filling = info.filling_mode
    if filling & 1:
        return mt5.ORDER_FILLING_FOK
    if filling & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def close_position(pos):
    symbol   = pos.symbol
    ticket   = pos.ticket
    volume   = pos.volume
    pos_type = pos.type  # 0=BUY, 1=SELL

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, "Khong lay duoc gia"

    if pos_type == mt5.ORDER_TYPE_BUY:
        close_type  = mt5.ORDER_TYPE_SELL
        close_price = tick.bid
    else:
        close_type  = mt5.ORDER_TYPE_BUY
        close_price = tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       volume,
        "type":         close_type,
        "position":     ticket,
        "price":        close_price,
        "deviation":    30,
        "magic":        MAGIC,
        "comment":      "MacroClose",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": get_filling_type(symbol),
    }

    result = mt5.order_send(request)
    if result is None:
        return False, "order_send None"
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        return True, f"Dong ticket={ticket} OK"
    return False, f"retcode={result.retcode}: {result.comment}"


def close_all_by_magic(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return
    for pos in positions:
        if pos.magic == MAGIC:
            ok, msg = close_position(pos)
            print(f"  {msg}")


def modify_sl(ticket, new_sl):
    pos = None
    for p in mt5.positions_get():
        if p.ticket == ticket:
            pos = p
            break
    if pos is None:
        return False

    digits = int(mt5.symbol_info(pos.symbol).digits)
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   pos.symbol,
        "position": ticket,
        "sl":       round(new_sl, digits),
        "tp":       pos.tp,
    }
    result = mt5.order_send(request)
    if result is None:
        return False
    return result.retcode == mt5.TRADE_RETCODE_DONE

# ============================================================
# SMART POSITION MANAGER (goi sau khi mo vi tri)
# ============================================================
def manage_positions(symbol, direction, entry_price):
    # Lay thong tin symbol truoc khi vao vong lap
    if not mt5_init():
        print("  [Manager] MT5 init that bai — huy theo doi")
        return
    sym = mt5.symbol_info(symbol)
    if sym is None:
        mt5.shutdown()
        print("  [Manager] Khong lay duoc symbol info — huy")
        return
    point  = sym.point
    digits = int(sym.digits)
    mt5.shutdown()

    partial_done = False
    be_done      = False

    print(f"  [Manager] Bat dau theo doi {symbol} {direction} entry={entry_price}")

    while True:
        time.sleep(15)

        if not mt5_init():
            continue

        positions = [p for p in (mt5.positions_get(symbol=symbol) or [])
                     if p.magic == MAGIC]
        mt5.shutdown()

        if not positions:
            print("  [Manager] Het vi tri (SL/TP hit) — reset de cho phep vao lai lenh moi")
            clear_last_signal()
            break

        # Gia hien tai (dung price cua vi tri dau tien)
        tick = None
        if mt5_init():
            tick = mt5.symbol_info_tick(symbol)
            mt5.shutdown()
        if tick is None:
            continue

        cur_price = tick.bid if direction == "BUY" else tick.ask
        profit_pts = (cur_price - entry_price) if direction == "BUY" \
                     else (entry_price - cur_price)
        profit_pts = round(profit_pts / point)

        if not partial_done and profit_pts >= PARTIAL_CLOSE_AT:
            print(f"  [Manager] Lai {profit_pts} pts >= {PARTIAL_CLOSE_AT} — dong 1 vi tri")
            if mt5_init():
                # dong vi tri dau tien trong danh sach
                ok, msg = close_position(positions[0])
                print(f"  [Manager] {msg}")

                # cap nhat lai danh sach
                positions = [p for p in (mt5.positions_get(symbol=symbol) or [])
                             if p.magic == MAGIC]

                # doi SL cua vi tri con lai ve BE + buffer
                if not be_done:
                    be_buffer_price = (entry_price + BE_BUFFER * point) if direction == "BUY" \
                                       else (entry_price - BE_BUFFER * point)
                    for p in positions:
                        ok2 = modify_sl(p.ticket, be_buffer_price)
                        print(f"  [Manager] Doi SL ticket={p.ticket} ve BE+{BE_BUFFER}pts: {'OK' if ok2 else 'FAIL'}")
                    be_done = True

                mt5.shutdown()
                partial_done = True

# ============================================================
# MT5 EXECUTION
# ============================================================
def execute_mt5(signal):
    if signal["signal"] == "HOLD":
        return False, "HOLD — khong vao lenh"

    if signal["confidence"] < MIN_CONFIDENCE:
        return False, f"Confidence thap ({signal['confidence']}%)"

    if not mt5_init():
        return False, f"Khong ket noi MT5: {mt5.last_error()}"

    symbol = get_mt5_symbol()
    if not symbol:
        mt5.shutdown()
        return False, "Khong tim thay symbol XAUUSD tren MT5"

    sym_info = mt5.symbol_info(symbol)
    if not sym_info.visible:
        mt5.symbol_select(symbol, True)
        time.sleep(0.5)

    # Dong vi tri nguoc chieu (dao chieu)
    existing = mt5.positions_get(symbol=symbol)
    if existing:
        for pos in existing:
            if pos.magic == MAGIC:
                pos_dir = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
                if pos_dir != signal["signal"]:
                    print(f"  Dao chieu: dong {pos_dir} ticket={pos.ticket}")
                    ok, msg = close_position(pos)
                    print(f"  {msg}")
                else:
                    mt5.shutdown()
                    return False, f"Da co lenh {pos_dir} — bo qua"

    # Lap lai 1 giay de dam bao dong xong
    time.sleep(1)

    tick      = mt5.symbol_info_tick(symbol)
    digits    = int(sym_info.digits)
    is_buy    = signal["signal"] == "BUY"
    price     = tick.ask if is_buy else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    filling    = get_filling_type(symbol)

    sl = round(float(signal["sl"]), digits)
    tp = round(float(signal["tp"]), digits)

    tickets = []
    for i in range(NUM_POSITIONS):
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       LOT_SIZE,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    30,
            "magic":        MAGIC,
            "comment":      f"MacroSignal#{i+1}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        result = mt5.order_send(request)
        if result is None:
            print(f"  Vi tri {i+1}: order_send None")
        elif result.retcode == mt5.TRADE_RETCODE_DONE:
            tickets.append(result.order)
            print(f"  Vi tri {i+1}: OK ticket={result.order}")
        else:
            print(f"  Vi tri {i+1}: FAIL retcode={result.retcode} {result.comment}")

    mt5.shutdown()

    if not tickets:
        return False, "Khong mo duoc vi tri nao"

    entry_price = price
    # Chay manager trong thread rieng
    import threading
    t = threading.Thread(
        target=manage_positions,
        args=(symbol, signal["signal"], entry_price),
        daemon=True
    )
    t.start()

    msg = f"{signal['signal']} x{len(tickets)}/{NUM_POSITIONS} @ {price} | SL:{sl} TP:{tp}"
    return True, msg

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(signal, macro, screenshot=None, mt5_msg=""):
    # HOLD: khong gui
    if signal.get("signal") == "HOLD":
        print("  HOLD — bo qua Telegram")
        return

    icon = {"BUY": "🟢", "SELL": "🔴"}.get(signal["signal"], "⚪")
    xau  = macro.get("XAUUSD", {})

    msg = (
        f"{icon} *XAUUSD MACRO SIGNAL*\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"📊 *Signal:* `{signal['signal']}` | 💪 *Confidence:* {signal['confidence']}%\n"
        f"💰 *Entry:* `{signal['entry']}`\n"
        f"🛑 *SL:* `{signal['sl']}` | 🎯 *TP:* `{signal['tp']}`\n\n"
        f"📈 XAUUSD : ${xau.get('price')} ({xau.get('change_pct', 0):+.2f}%)\n"
        f"💵 DXY    : {macro.get('DXY',   {}).get('price')} ({macro.get('DXY',   {}).get('change_pct', 0):+.2f}%)\n"
        f"📊 US10Y  : {macro.get('US10Y', {}).get('price')}%\n"
        f"😱 VIX    : {macro.get('VIX',   {}).get('price')}\n"
        f"🥈 Silver : ${macro.get('SILVER',{}).get('price')}\n\n"
        f"📝 {signal.get('analysis', '')}\n"
        f"🤖 MT5: {mt5_msg}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    try:
        if screenshot and os.path.exists(screenshot):
            with open(screenshot, "rb") as photo:
                requests.post(f"{url}/sendPhoto",
                              data={"chat_id": TELEGRAM_CHAT_ID, "caption": msg,
                                    "parse_mode": "Markdown"},
                              files={"photo": photo}, timeout=30)
        else:
            requests.post(f"{url}/sendMessage",
                          json={"chat_id": TELEGRAM_CHAT_ID, "text": msg,
                                "parse_mode": "Markdown"}, timeout=30)
        print("  Telegram OK")
    except Exception as e:
        print(f"  Loi Telegram: {e}")

# ============================================================
# MAIN RUN
# ============================================================
def run():
    print(f"\n{'='*50}")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')} — Bat dau phan tich...")

    # 1. Macro data
    print("📊 Doc macro data...")
    macro = get_macro_data()
    if not macro:
        print("Khong doc duoc data — bo qua cycle nay")
        return

    # 2. Claude analysis
    print("Phan tich Claude...")
    signal = analyze_with_claude(macro)
    print(f"  -> {signal['signal']} (confidence: {signal['confidence']}%)")

    # 3. HOLD: ghi file roi thoat
    if signal["signal"] == "HOLD":
        signal["entry"] = macro.get("XAUUSD", {}).get("price", 0)
        signal["sl"]    = 0
        signal["tp"]    = 0
        with open(SIGNAL_FILE, "w", encoding="utf-8") as f:
            json.dump({**signal, "timestamp": datetime.now().isoformat(),
                       "macro": macro}, f, indent=2, ensure_ascii=False)
        print("  HOLD — bo qua Telegram va MT5")
        return

    # 4. Tinh Entry/SL/TP tu gia XAUUSD that tren MT5
    print("Lay gia XAUUSD tu MT5...")
    entry, sl, tp = get_entry_sl_tp(signal["signal"])
    if entry:
        signal["entry"] = entry
        signal["sl"]    = sl
        signal["tp"]    = tp
        print(f"  Entry: {entry} | SL: {sl} | TP: {tp}")
    else:
        print("  Khong lay duoc gia MT5, dung fallback GC=F")
        ref = macro.get("XAUUSD", {}).get("price", 0)
        signal["entry"] = ref
        signal["sl"]    = round(ref - 15, 2) if signal["signal"] == "BUY" else round(ref + 15, 2)
        signal["tp"]    = round(ref + 30, 2) if signal["signal"] == "BUY" else round(ref - 30, 2)

    # 5. Ghi signal.json
    with open(SIGNAL_FILE, "w", encoding="utf-8") as f:
        json.dump({**signal, "timestamp": datetime.now().isoformat(),
                   "macro": macro}, f, indent=2, ensure_ascii=False)
    print(f"  signal.json -> {SIGNAL_FILE}")

    # 6. Kiem tra trung tin hieu
    if is_duplicate(signal):
        print("Xong (bo qua do tin hieu trung)")
        return

    # 7. Luu tin hieu moi
    save_last_signal(signal)

    # 8. Screenshot
    print("Screenshot TradingView...")
    screenshot = take_screenshot()

    # 9. Thuc thi MT5
    print("Thuc thi MT5...")
    ok, mt5_msg = execute_mt5(signal)
    print(f"  {mt5_msg}")

    # 10. Telegram (chi BUY/SELL)
    print("Gui Telegram...")
    send_telegram(signal, macro, screenshot, mt5_msg)

    print("Xong!")


if __name__ == "__main__":
    print("XAUUSD Macro Analyzer — Khoi dong")
    print(f"Signal file : {SIGNAL_FILE}")
    print(f"Chu ky      : moi 15 phut")
    print(f"Vi tri/signal: {NUM_POSITIONS} x {LOT_SIZE} lot")
    print(f"Partial close: >= {PARTIAL_CLOSE_AT} pts")
    print(f"BE buffer   : +{BE_BUFFER} pts\n")

    run()

    schedule.every(15).minutes.do(run)
    while True:
        schedule.run_pending()
        time.sleep(1)
