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
PARTIAL_CLOSE_USD = 100      # dong 1 vi tri khi lai >= $15/oz (= cach SL)
BE_BUFFER_USD     = 50       # doi SL ve entry +/- $5 sau partial close
MIN_CONFIDENCE   = 60
MAGIC            = 20240101

# MT5 account — dien vao de Python ket noi dung terminal (tranh bi vao MT5 B)
MT5_PATH     = r"C:\Users\ADMIN\Desktop\Công việc\MT51\terminal64.exe"  # Exness Trial17 local
MT5_LOGIN    = 463207464       # so tai khoan MT5 local
MT5_PASSWORD = "Drduong9190@.@"     # mat khau MT5
MT5_SERVER   = "Exness-MT5Trial17"  # ten server

TELEGRAM_ENABLED = False  # Local machine — chi trade, khong gui Telegram

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
        return mt5.initialize(path=MT5_PATH, login=MT5_LOGIN,
                              password=MT5_PASSWORD, server=MT5_SERVER)
    return mt5.initialize(path=MT5_PATH)

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
    if last.get("signal") != new_signal.get("signal"):
        return False
    # Cung chieu — kiem tra MT5 co lenh mo khong
    # Neu khong co lenh mo thi cho phep vao lai (SL/TP da hit hoac Python bi tat truoc do)
    if mt5_init():
        symbol = get_mt5_symbol()
        has_open = False
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
            has_open = any(p.magic == MAGIC for p in (positions or []))
        mt5.shutdown()
        if not has_open:
            print(f"  Khong co lenh mo — cho phep vao lai cung chieu ({new_signal['signal']})")
            clear_last_signal()
            return False
    print(f"  Tin hieu trung ({new_signal['signal']}) — bo qua Telegram + MT5")
    return True

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
    """Chup anh cua so MT5 terminal va luu vao SCREENSHOT_FILE."""
    try:
        import win32gui, win32ui, win32con
        from PIL import Image

        # Tim cua so MT5
        mt5_hwnd = None
        def _find_mt5(hwnd, ctx):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if any(x in title for x in ['MetaTrader 5', 'MetaTrader5', 'Exness', 'MT5']):
                ctx.append(hwnd)
        candidates = []
        win32gui.EnumWindows(_find_mt5, candidates)
        if candidates:
            mt5_hwnd = candidates[0]

        if not mt5_hwnd:
            print("  Khong tim thay cua so MT5 — bo qua screenshot")
            return None

        # Lay kich thuoc cua so
        left, top, right, bot = win32gui.GetWindowRect(mt5_hwnd)
        w, h = right - left, bot - top
        if w <= 0 or h <= 0:
            return None

        # Chup bang win32 (hoat dong ca khi cua so bi an sau)
        hwndDC   = win32gui.GetWindowDC(mt5_hwnd)
        mfcDC    = win32ui.CreateDCFromHandle(hwndDC)
        saveDC   = mfcDC.CreateCompatibleDC()
        bmp      = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfcDC, w, h)
        saveDC.SelectObject(bmp)
        saveDC.BitBlt((0, 0), (w, h), mfcDC, (0, 0), win32con.SRCCOPY)

        bmpinfo = bmp.GetInfo()
        bmpstr  = bmp.GetBitmapBits(True)
        img = Image.frombuffer('RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                               bmpstr, 'raw', 'BGRX', 0, 1)

        win32gui.DeleteObject(bmp.GetHandle())
        saveDC.DeleteDC(); mfcDC.DeleteDC()
        win32gui.ReleaseDC(mt5_hwnd, hwndDC)

        out = str(SCREENSHOT_FILE)
        img.save(out)
        print(f"  Screenshot MT5 OK ({w}x{h}px)")
        return out
    except Exception as e:
        print(f"  Loi screenshot MT5: {e}")
    return None

# ============================================================
# CLAUDE ANALYSIS
# ============================================================
def _find_signal(obj):
    if isinstance(obj, dict):
        if 'signal' in obj: return obj
        for v in obj.values():
            r = _find_signal(v)
            if r: return r
    return None


def analyze_with_claude(macro):
    import json as _j
    xau    = macro.get("XAUUSD", {})
    dxy    = macro.get("DXY",    {})
    us10y  = macro.get("US10Y",  {})
    vix    = macro.get("VIX",    {})
    silver = macro.get("SILVER", {})

    prompt = f"""Analyze gold (XAUUSD) trading signal. Reply with ONLY this JSON line, nothing else, no markdown:
{{"signal":"BUY|SELL|HOLD","confidence":50-90,"analysis":"reason"}}

Data: XAUUSD=${xau.get('price')}({xau.get('change_pct'):+.1f}%) DXY={dxy.get('price')}({dxy.get('change_pct'):+.1f}%) US10Y={us10y.get('price')}%({us10y.get('change_pct'):+.1f}%) VIX={vix.get('price')}({vix.get('change_pct'):+.1f}%) SILVER=${silver.get('price')}({silver.get('change_pct'):+.1f}%)

Rules: DXY+US10Y both rising=SELL gold. DXY+US10Y both falling=BUY gold. VIX>20=fear=BUY gold. Conflicting signals=HOLD.
Confidence 65-90 for clear BUY/SELL, 40-59 for HOLD. Example: {{"signal":"BUY","confidence":75,"analysis":"DXY falling, US10Y down, VIX elevated supports gold rally"}}
Output exactly one JSON line:"""

    try:
        claude_cmd = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
        _pf = str(MT5_COMMON / "claude_prompt.txt")
        with open(_pf, "w", encoding="utf-8") as _f:
            _f.write(prompt)
        result = subprocess.run(
            f'cmd /c type "{_pf}" | "{claude_cmd}" --print --dangerously-skip-permissions',
            capture_output=True, text=True, timeout=120, shell=True,
            encoding="utf-8", errors="ignore"
        )
        stdout = result.stdout
        if 'session limit' in stdout.lower():
            return {'signal': 'HOLD', 'confidence': 50, 'analysis': 'Claude session limit'}
        # 1. Try flat signal JSON
        m = re.search(r'\{[^{}]*"signal"\s*:\s*"(BUY|SELL|HOLD)"[^{}]*\}', stdout, re.DOTALL)
        if m:
            try:
                d = _j.loads(m.group())
                if 'signal' in d: return d
            except: pass
        # 2. Try code block
        m2 = re.search(r'```(?:json)?\s*([\s\S]+?)```', stdout)
        if m2:
            try:
                d = _j.loads(m2.group(1).strip())
                sig = _find_signal(d)
                if sig: return sig
            except: pass
        # 3. Keyword fallback
        kw = re.search(r'\b(BUY|SELL|HOLD)\b', stdout)
        conf_m = re.search(r'confidence[^0-9]*(\d+)', stdout, re.IGNORECASE)
        if kw:
            return {'signal': kw.group(1), 'confidence': int(conf_m.group(1)) if conf_m else 50, 'analysis': stdout[:200]}
        print(f"  Claude output: {stdout[:200]}")
    except Exception as e:
        print(f"  Loi Claude: {e}")

    return {"signal": "HOLD", "confidence": 50, "analysis": "Cannot analyze - hold"}


def get_mt5_symbol():
    for sym in ["XAUUSD", "XAUUSDm", "GOLD", "XAUUSDc", "XAUUSD."]:
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
            _tg_send(
                f"🏁 *XAUUSD — Vi tri da dong (SL/TP hit)*\n"
                f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                f"Direction: `{direction}` | Entry: `{entry_price}`\n"
                f"🤖 Cho tin hieu moi..."
            )
            clear_last_signal()
            break

        # Lay gia hien tai
        tick = None
        if mt5_init():
            tick = mt5.symbol_info_tick(symbol)
            mt5.shutdown()
        if tick is None:
            continue

        # Tinh lai bang USD (nhat quan voi cach tinh SL/TP)
        cur_price  = tick.bid if direction == "BUY" else tick.ask
        profit_usd = (cur_price - entry_price) if direction == "BUY" \
                     else (entry_price - cur_price)

        print(f"  [Manager] {direction} profit=${profit_usd:.2f} | positions={len(positions)}")

        if not partial_done and profit_usd >= PARTIAL_CLOSE_USD:
            print(f"  [Manager] Lai ${profit_usd:.2f} >= ${PARTIAL_CLOSE_USD} — dong 1 vi tri")
            if mt5_init():
                ok, close_msg = close_position(positions[0])
                print(f"  [Manager] {close_msg}")
                if ok:
                    _tg_send(
                        f"💰 *XAUUSD — Partial Close*\n"
                        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                        f"Direction: `{direction}` | Profit: `${profit_usd:.2f}`\n"
                        f"Da dong 1 vi tri, chuyen SL ve Breakeven +${BE_BUFFER_USD}"
                    )

                positions = [p for p in (mt5.positions_get(symbol=symbol) or [])
                             if p.magic == MAGIC]

                if not be_done:
                    be_price = (entry_price + BE_BUFFER_USD) if direction == "BUY" \
                               else (entry_price - BE_BUFFER_USD)
                    be_results = []
                    for p in positions:
                        ok2 = modify_sl(p.ticket, be_price)
                        print(f"  [Manager] Doi SL ticket={p.ticket} ve BE+${BE_BUFFER_USD}: {'OK' if ok2 else 'FAIL'}")
                        be_results.append(ok2)
                    if any(be_results):
                        _tg_send(
                            f"🛡 *XAUUSD — SL doi ve Breakeven*\n"
                            f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                            f"Direction: `{direction}` | BE price: `{be_price}`\n"
                            f"Con lai {len(positions)} vi tri dang mo"
                        )
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
                    ok, rev_msg = close_position(pos)
                    print(f"  {rev_msg}")
                    if ok:
                        _tg_send(
                            f"🔄 *XAUUSD — Dao chieu lenh*\n"
                            f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                            f"Da dong `{pos_dir}` ticket={pos.ticket}\n"
                            f"Chuan bi vao `{signal['signal']}` theo tin hieu moi"
                        )
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

    # Notify Telegram: positions opened
    _dir_icon = "🟢" if signal["signal"] == "BUY" else "🔴"
    _tg_send(
        f"{_dir_icon} *XAUUSD — Vi tri da mo*\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"Signal: `{signal['signal']}` x{len(tickets)}/{NUM_POSITIONS}\n"
        f"💰 Entry: `{price}` | 🛑 SL: `{sl}` | 🎯 TP: `{tp}`\n"
        f"Tickets: {', '.join(str(t) for t in tickets)}"
    )

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
def _tg_send(msg, screenshot=None):
    """Send text or photo+caption to Telegram."""
    if not TELEGRAM_ENABLED:
        return  # Local machine — tat Telegram
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
    except Exception as e:
        print(f"  Loi Telegram: {e}")


def send_telegram(signal, macro, screenshot=None, mt5_msg=""):
    # HOLD: khong gui
    if signal.get("signal") == "HOLD":
        print("  HOLD — bo qua Telegram va MT5")
        return

    icon = "🟢" if signal["signal"] == "BUY" else "🔴"
    msg = (
        f"{icon} *XAUUSD {signal['signal']} SIGNAL*\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"📊 *Signal:* `{signal['signal']}` | 💪 *Confidence:* {signal['confidence']}%\n"
        f"💰 *Entry:* `{signal['entry']}`\n"
        f"🛑 *SL:* `{signal['sl']}` | 🎯 *TP:* `{signal['tp']}`\n\n"
        f"📝 {signal.get('analysis', '')}\n"
        f"🤖 MT5: {mt5_msg}"
    )
    _tg_send(msg, screenshot)
    print("  Telegram OK")

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
    signal.setdefault('signal', 'HOLD'); signal.setdefault('confidence', 50)
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
        print("  Khong lay duoc gia MT5, dung fallback GC=F (XAUUSD)")
        ref = macro.get("BTCUSD", {}).get("price", 0)
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
    print("XAUUSD Macro Analyzer v1 — Khoi dong")
    print(f"Signal file : {SIGNAL_FILE}")
    print(f"Chu ky      : moi 15 phut")
    print(f"Vi tri/signal: {NUM_POSITIONS} x {LOT_SIZE} lot")
    print(f"Partial close: lai >= ${PARTIAL_CLOSE_USD}")
    print(f"BE buffer   : entry +/- ${BE_BUFFER_USD}\n")

    run()

    schedule.every(15).minutes.do(run)
    while True:
        try:
            schedule.run_pending()
        except Exception as _e:
            print(f'  [Loop error] {_e}')
        time.sleep(1)
