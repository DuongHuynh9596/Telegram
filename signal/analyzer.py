#!/usr/bin/env python3
"""
XAUUSD Macro Signal Analyzer
- Đọc US10Y, DXY, VIX, SILVER, XAUUSD từ yfinance
- Phân tích với Claude Code CLI
- Chống trùng tín hiệu (chỉ gửi khi đổi chiều)
- Thực thi MT5 với auto-detect filling type
- Gửi Telegram kèm screenshot TradingView
"""

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
MIN_CONFIDENCE   = 60
MAGIC            = 20240101

MT5_COMMON = Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / "Common" / "Files"
MT5_COMMON.mkdir(parents=True, exist_ok=True)

SIGNAL_FILE      = MT5_COMMON / "signal.json"
SCREENSHOT_FILE  = MT5_COMMON / "screenshot.png"
LAST_SIGNAL_FILE = MT5_COMMON / "last_signal.json"

# ============================================================
# CHỐNG TRÙNG TÍN HIỆU
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

def is_duplicate(new_signal):
    """Trả về True nếu tín hiệu giống lần trước (cùng chiều BUY/SELL)"""
    if new_signal.get("signal") == "HOLD":
        return False
    last = load_last_signal()
    if not last:
        return False
    if last.get("signal") == new_signal.get("signal"):
        print(f"  ⏭  Tín hiệu trùng ({new_signal['signal']}) — bỏ qua Telegram + MT5")
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
            print(f"  Lỗi {name}: {e}")
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
            print("  Không tìm thấy TradingView chart")
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
            print(f"  Screenshot OK")
            return str(SCREENSHOT_FILE)
    except Exception as e:
        print(f"  Lỗi screenshot: {e}")
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

    # Claude chỉ cần trả signal + confidence + analysis
    # Entry/SL/TP sẽ được tính từ giá XAUUSD thật trên MT5
    prompt = f"""Phân tích vĩ mô XAUUSD. Chỉ trả về JSON, không text khác.

DỮ LIỆU (GC Futures dùng để tham khảo macro):
- XAUUSD : ${xau.get('price')} ({xau.get('change_pct'):+.2f}%) | H24: ${xau.get('high_24h')} L24: ${xau.get('low_24h')}
- DXY    : {dxy.get('price')} ({dxy.get('change_pct'):+.2f}%)
- US10Y  : {us10y.get('price')}% ({us10y.get('change_pct'):+.2f}%)
- VIX    : {vix.get('price')} ({vix.get('change_pct'):+.2f}%)
- SILVER : ${silver.get('price')} ({silver.get('change_pct'):+.2f}%)

JSON format (chỉ JSON, không cần tính entry/sl/tp):
{{"signal":"BUY|SELL|HOLD","confidence":50-95,"analysis":"<tiếng Việt>"}}"""

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
        print(f"  Lỗi Claude: {e}")

    return {"signal": "HOLD", "confidence": 50, "analysis": "Không phân tích được — giữ nguyên"}


def get_mt5_symbol():
    """Tìm symbol XAUUSD trên MT5"""
    for sym in ["XAUUSD", "XAUUSDm", "GOLD", "XAUUSD.", "XAUUSDc"]:
        info = mt5.symbol_info(sym)
        if info is not None:
            return sym
    return None


def get_entry_sl_tp(signal_dir):
    """Lấy giá thật từ XAUUSD OANDA trên MT5, tính SL/TP cố định"""
    if not mt5.initialize():
        return None, None, None

    symbol = get_mt5_symbol()
    if not symbol:
        mt5.shutdown()
        return None, None, None

    if not mt5.symbol_info(symbol).visible:
        mt5.symbol_select(symbol, True)
        time.sleep(0.3)

    tick = mt5.symbol_info_tick(symbol)
    digits = int(mt5.symbol_info(symbol).digits)
    mt5.shutdown()

    if signal_dir == "BUY":
        entry = round(tick.ask, digits)
        sl    = round(entry - 15, digits)
        tp    = round(entry + 30, digits)
    else:  # SELL
        entry = round(tick.bid, digits)
        sl    = round(entry + 15, digits)
        tp    = round(entry - 30, digits)

    return entry, sl, tp

# ============================================================
# MT5 EXECUTION
# ============================================================
def get_filling_type(symbol):
    """Auto-detect filling type được broker hỗ trợ"""
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_IOC

    filling = info.filling_mode
    if filling & mt5.SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    if filling & mt5.SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN

def execute_mt5(signal):
    if signal["signal"] == "HOLD":
        return False, "HOLD — không vào lệnh"

    if signal["confidence"] < MIN_CONFIDENCE:
        return False, f"Confidence thấp ({signal['confidence']}%)"

    if not mt5.initialize():
        return False, f"Không kết nối MT5: {mt5.last_error()}"

    symbol = get_mt5_symbol()
    if not symbol:
        mt5.shutdown()
        return False, "Không tìm thấy symbol XAUUSD trên MT5"

    sym_info = mt5.symbol_info(symbol)
    if not sym_info.visible:
        mt5.symbol_select(symbol, True)
        time.sleep(0.5)

    # Kiểm tra đã có lệnh mở chưa
    open_pos = mt5.positions_get(symbol=symbol)
    if open_pos:
        for pos in open_pos:
            if pos.magic == MAGIC:
                mt5.shutdown()
                return False, f"Đã có lệnh mở ({symbol}) — bỏ qua"

    tick      = mt5.symbol_info_tick(symbol)
    digits    = int(sym_info.digits)
    is_buy    = signal["signal"] == "BUY"
    price     = tick.ask if is_buy else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

    sl = round(float(signal["sl"]), digits)
    tp = round(float(signal["tp"]), digits)

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
        "comment":      "MacroSignal",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": get_filling_type(symbol),
    }

    result = mt5.order_send(request)
    mt5.shutdown()

    if result is None:
        return False, "MT5 order_send trả về None"
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        return True, f"✅ {signal['signal']} {symbol} @ {price} | SL:{sl} TP:{tp}"
    return False, f"❌ retcode={result.retcode}: {result.comment}"

# ============================================================
# TELEGRAM
# ============================================================
def send_telegram(signal, macro, screenshot=None, mt5_msg=""):
    icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(signal["signal"], "⚪")
    xau = macro.get("XAUUSD", {})

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
        print(f"  Lỗi Telegram: {e}")

# ============================================================
# MAIN RUN
# ============================================================
def run():
    print(f"\n{'='*50}")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')} — Bắt đầu phân tích...")

    # 1. Macro data
    print("📊 Đọc macro data...")
    macro = get_macro_data()
    if not macro:
        print("❌ Không đọc được data — bỏ qua cycle này")
        return

    # 2. Claude analysis (chỉ lấy signal + confidence + analysis)
    print("🤖 Phân tích Claude...")
    signal = analyze_with_claude(macro)
    print(f"  → {signal['signal']} (confidence: {signal['confidence']}%)")

    # 3. Tính Entry/SL/TP từ giá XAUUSD thật trên MT5 (không dùng GC=F)
    if signal["signal"] in ("BUY", "SELL"):
        print("💱 Lấy giá XAUUSD từ MT5...")
        entry, sl, tp = get_entry_sl_tp(signal["signal"])
        if entry:
            signal["entry"] = entry
            signal["sl"]    = sl
            signal["tp"]    = tp
            print(f"  Entry: {entry} | SL: {sl} | TP: {tp}")
        else:
            print("  ⚠ Không lấy được giá MT5, dùng fallback GC=F")
            ref = macro.get("XAUUSD", {}).get("price", 0)
            signal["entry"] = ref
            signal["sl"]    = round(ref - 15, 2) if signal["signal"] == "BUY" else round(ref + 15, 2)
            signal["tp"]    = round(ref + 30, 2) if signal["signal"] == "BUY" else round(ref - 30, 2)
    else:
        signal["entry"] = macro.get("XAUUSD", {}).get("price", 0)
        signal["sl"]    = 0
        signal["tp"]    = 0

    # 4. Luôn ghi signal.json để EA MT5 đọc
    with open(SIGNAL_FILE, "w", encoding="utf-8") as f:
        json.dump({**signal, "timestamp": datetime.now().isoformat(),
                   "macro": macro}, f, indent=2, ensure_ascii=False)
    print(f"  signal.json → {SIGNAL_FILE}")

    # 5. Kiểm tra trùng tín hiệu
    if is_duplicate(signal):
        print("✅ Xong (bỏ qua do tín hiệu trùng)")
        return

    # 6. Lưu tín hiệu mới
    save_last_signal(signal)

    # 7. Screenshot
    print("📸 Screenshot TradingView...")
    screenshot = take_screenshot()

    # 8. Thực thi MT5
    print("🚀 Thực thi MT5...")
    ok, mt5_msg = execute_mt5(signal)
    print(f"  {mt5_msg}")

    # 9. Telegram
    print("📱 Gửi Telegram...")
    send_telegram(signal, macro, screenshot, mt5_msg)

    print("✅ Xong!")


if __name__ == "__main__":
    print("🚀 XAUUSD Macro Analyzer — Khởi động")
    print(f"📁 Signal file : {SIGNAL_FILE}")
    print(f"⏱  Chu kỳ     : mỗi 15 phút\n")

    run()  # Chạy ngay lần đầu

    schedule.every(15).minutes.do(run)
    while True:
        schedule.run_pending()
        time.sleep(1)
