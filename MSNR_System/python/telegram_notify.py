import requests
import logging
from datetime import datetime

log = logging.getLogger("MSNR.Telegram")

BOT_TOKEN  = "8831434339:AAG_vFqfRsTtAwpJV9woIMnRtGQExND1X9c"
CHANNEL_ID = "-1003996984890"
BASE_URL   = "https://api.telegram.org/bot" + BOT_TOKEN

# Pre-defined unicode (tranh backslash trong f-string Python 3.11)
BELL   = "\U0001f514"
CHART  = "\U0001f4ca"
BOX    = "\U0001f4e6"
CHECK  = "✅"
STOP   = "\U0001f6d1"
TARGET = "\U0001f3af"
LOCK   = "\U0001f512"
SHIELD = "\U0001f6e1"
MONEY  = "\U0001f4b0"
FLAG   = "\U0001f3c1"
CLOCK  = "⏰"
RED    = "\U0001f534"
GREEN  = "\U0001f7e2"
CLIP   = "\U0001f4cb"
UP     = "↗"
DOWN   = "↘"
DASH   = "—"


def _post(endpoint, **kwargs):
    try:
        r = requests.post(f"{BASE_URL}/{endpoint}", timeout=15, **kwargs)
        if not r.ok:
            log.warning(f"Telegram {endpoint} failed: {r.status_code} {r.text[:200]}")
        return r.ok
    except Exception as e:
        log.error(f"Telegram {endpoint} error: {e}")
        return False


def send_message(text):
    return _post("sendMessage", json={
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
    })


def send_photo(photo_path, caption=""):
    try:
        with open(photo_path, "rb") as f:
            return _post("sendPhoto",
                data={"chat_id": CHANNEL_ID, "caption": caption,
                      "parse_mode": "HTML"},
                files={"photo": f})
    except Exception as e:
        log.error(f"sendPhoto error: {e}")
        return False


def _vi_analysis(signal):
    """Phan tich ly do bang tieng Viet"""
    action = signal["action"]
    p3     = signal.get("p3_trendline", False)
    fresh  = signal.get("fresh_level", False)
    conf   = signal.get("confluence", 0)
    entry  = signal["entry"]
    sl     = signal["sl"]
    rr     = signal.get("rr", 0)

    lines = []
    if action == "BUY":
        if fresh:
            lines.append("- Gia dang test <b>V-Level (Ho Tro) fresh</b> chua bi wick cham")
        if p3:
            lines.append("- <b>P3 Trendline UP</b>: Wick cham trendline tang, than nen trong zone")
        if not fresh and not p3:
            lines.append("- Gia tiep can vung ho tro MSNR")
        lines.append(f"- SL dat ben duoi level <b>${abs(entry - sl):.1f}</b> gia vang")
        lines.append(f"- TP tai khang cu fresh tiep theo, RR <b>{rr:.1f}:1</b>")
    else:
        if fresh:
            lines.append("- Gia dang test <b>A-Level (Khang Cu) fresh</b> chua bi wick cham")
        if p3:
            lines.append("- <b>P3 Trendline DOWN</b>: Wick cham trendline giam, than nen trong zone")
        if not fresh and not p3:
            lines.append("- Gia tiep can vung khang cu MSNR")
        lines.append(f"- SL dat ben tren level <b>${abs(sl - entry):.1f}</b> gia vang")
        lines.append(f"- TP tai ho tro fresh tiep theo, RR <b>{rr:.1f}:1</b>")

    if conf >= 2:
        lines.append(f"- <b>Tin hieu manh</b>: {conf} diem hoi tu (Trendline + Level)")
    return "\n".join(lines)


def send_signal_alert(signal):
    action = signal["action"]
    entry  = signal["entry"]
    sl     = signal["sl"]
    tp     = signal["tp"]
    lot    = signal["lot"]
    rr     = signal.get("rr", 0)
    sl_usd = signal.get("sl_usd", 18)
    tp_usd = round(abs(tp - entry), 1)
    risk   = round(sl_usd * lot * 100, 0)
    arr    = UP if action == "BUY" else DOWN
    lbl    = "LONG" if action == "BUY" else "SHORT"
    analysis = _vi_analysis(signal)
    now    = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    msg = (
        f"{BELL} <b>MSNR SIGNAL {DASH} XAUUSD {lbl}</b>\n\n"
        f"{arr} <b>{action}</b> @ <code>{entry:.2f}</code>\n"
        f"{STOP} SL: <code>{sl:.2f}</code>  (-${sl_usd:.0f})\n"
        f"{TARGET} TP: <code>{tp:.2f}</code>  (+${tp_usd} | RR <b>{rr:.1f}:1</b>)\n"
        f"{BOX} Lot: <code>{lot}</code>  | Risk: ~<b>${risk:.0f}</b>\n\n"
        f"{CHART} <b>Phan tich MSNR:</b>\n"
        f"{analysis}\n\n"
        f"{CLOCK} {now}\n"
        f"#XAUUSD #{action} #MSNR"
    )
    ok = send_message(msg)
    log.info(f"Signal alert sent OK={ok}")
    return ok


def send_order_executed(pos_info, screenshot_path=None):
    action = pos_info["action"]
    arr    = UP if action == "BUY" else DOWN
    now    = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    caption = (
        f"{CHECK} <b>Lenh da vao {DASH} XAUUSD</b>\n\n"
        f"{CLIP} Ticket: <code>#{pos_info['ticket']}</code>\n"
        f"{arr} <b>{action}</b> @ <code>{pos_info['price_open']:.2f}</code>\n"
        f"{STOP} SL: <code>{pos_info['sl']:.2f}</code>\n"
        f"{TARGET} TP: <code>{pos_info['tp']:.2f}</code>\n"
        f"{BOX} Lot: <code>{pos_info['volume']}</code>\n\n"
        f"{CLOCK} {now}"
    )

    if screenshot_path:
        ok = send_photo(screenshot_path, caption)
        log.info(f"Order executed + screenshot OK={ok}")
    else:
        ok = send_message(caption)
        log.info(f"Order executed (no screenshot) OK={ok}")
    return ok


def send_trail_activated(pos_info, new_sl):
    action = pos_info["action"]
    open_p = pos_info["price_open"]
    lock   = round(abs(new_sl - open_p), 2)
    profit = round(lock * pos_info["volume"] * 100, 2)
    arr    = UP if action == "BUY" else DOWN
    now    = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    msg = (
        f"{LOCK} <b>Trail 1R kich hoat {DASH} XAUUSD</b>\n\n"
        f"{CLIP} Ticket: <code>#{pos_info['ticket']}</code>\n"
        f"{arr} {action} @ <code>{open_p:.2f}</code>\n"
        f"{SHIELD} SL moi: <code>{new_sl:.2f}</code>  <- Lock <b>${lock:.0f} profit</b>\n"
        f"{MONEY} Te nhat se lai: <b>+${profit:.2f}</b>\n\n"
        f"{CLOCK} {now}"
    )
    ok = send_message(msg)
    log.info(f"Trail activated sent OK={ok}")
    return ok


def send_order_closed(pos_info, close_price, pnl):
    action  = pos_info["action"]
    result  = "THANG" if pnl > 0 else "THUA"
    emoji   = GREEN if pnl > 0 else RED
    arr     = UP if action == "BUY" else DOWN
    now     = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    msg = (
        f"{emoji} <b>Lenh dong ({result}) {DASH} XAUUSD</b>\n\n"
        f"{CLIP} Ticket: <code>#{pos_info['ticket']}</code>\n"
        f"{arr} {action} @ <code>{pos_info['price_open']:.2f}</code>\n"
        f"{FLAG} Dong @ <code>{close_price:.2f}</code>\n"
        f"{emoji} P&L: <b>${pnl:+.2f}</b>\n\n"
        f"{CLOCK} {now}"
    )
    ok = send_message(msg)
    log.info(f"Order closed P&L={pnl:+.2f} sent OK={ok}")
    return ok


def test_connection():
    ok = send_message(
        f"{CHECK} <b>MSNR System</b> ket noi Telegram thanh cong!\n"
        f"Bot san sang nhan tin hieu giao dich XAUUSD."
    )
    return ok
