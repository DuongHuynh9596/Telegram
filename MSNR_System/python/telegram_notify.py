import requests
import logging
from datetime import datetime

log = logging.getLogger("MSNR.Telegram")

BOT_TOKEN  = "8831434339:AAG_vFqfRsTtAwpJV9woIMnRtGQExND1X9c"
CHANNEL_ID = "-1003996984890"
BASE_URL   = "https://api.telegram.org/bot" + BOT_TOKEN

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
PENCIL = "✏️"
WARN   = "⚠️"


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
        "chat_id"    : CHANNEL_ID,
        "text"       : text,
        "parse_mode" : "HTML",
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


def _format_analysis(signal):
    """
    Su dung signal['analysis_items'] neu co (chi tiet),
    fallback ve phan tich don gian.
    """
    tf = signal.get('analysis_tf', 'H1')
    items = signal.get('analysis_items', [])

    if items:
        lines = [f"{PENCIL} <b>Phan tich MSNR ({tf}):</b>"]
        for it in items:
            lines.append(f"{it['icon']} {it['text']}")
            lines.append(f"   <i>{it['detail']}</i>")
        return "\n".join(lines)

    # Fallback don gian
    action = signal.get('action', '')
    p3     = signal.get('p3_trendline', False)
    fresh  = signal.get('fresh_level', False)
    entry  = signal.get('entry', 0)
    sl     = signal.get('sl', 0)
    tp     = signal.get('tp', 0)
    rr     = signal.get('rr', 0)
    lines  = [f"{PENCIL} <b>Phan tich MSNR ({tf}):</b>"]
    if action == 'BUY':
        if fresh:
            lines.append(f"🟢 V-Level (Ho Tro) FRESH ({tf}) — chua bi wick cham")
        if p3:
            lines.append(f"📐 P3 Trendline UP ({tf}) — wick cham, than nen trong zone")
        lines.append(f"🎯 TP tai A-Level @ <b>{tp:.2f}</b> ({tf}), RR {rr:.1f}:1")
    else:
        if fresh:
            lines.append(f"🔴 A-Level (Khang Cu) FRESH ({tf}) — chua bi wick cham")
        if p3:
            lines.append(f"📐 P3 Trendline DOWN ({tf}) — wick cham, than nen trong zone")
        lines.append(f"🎯 TP tai V-Level @ <b>{tp:.2f}</b> ({tf}), RR {rr:.1f}:1")
    return "\n".join(lines)


def send_signal_alert(signal, chart_path=None):
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
    conf   = signal.get("confluence", 0)
    tf     = signal.get("analysis_tf", "H1")
    analysis = _format_analysis(signal)
    now    = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    # Confluence rating
    if conf >= 2:
        conf_txt = f"<b>Manh</b> ({conf}/2) ✅"
    else:
        conf_txt = f"Trung binh ({conf}/2) {WARN}"

    msg = (
        f"{BELL} <b>MSNR SIGNAL {DASH} XAUUSD {lbl}</b>\n\n"
        f"{arr} <b>{action}</b> @ <code>{entry:.2f}</code>\n"
        f"{STOP} SL: <code>{sl:.2f}</code>  (-${sl_usd:.0f} | Khung: {tf})\n"
        f"{TARGET} TP: <code>{tp:.2f}</code>  (+${tp_usd} | RR <b>{rr:.1f}:1</b>)\n"
        f"{BOX} Lot: <code>{lot}</code>  | Risk: ~<b>${risk:.0f}</b>\n"
        f"🔗 Confluence: {conf_txt}\n\n"
        f"{analysis}\n\n"
        f"{CLOCK} {now} | #{tf}\n"
        f"#XAUUSD #{action} #MSNR"
    )
    if chart_path:
        ok = send_photo(chart_path, msg)
        log.info(f"Signal alert + chart sent OK={ok}")
    else:
        ok = send_message(msg)
        log.info(f"Signal alert (text only) sent OK={ok}")
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
        f"<i>Chart da duoc ve SL/TP + MSNR levels</i>\n"
        f"{CLOCK} {now}"
    )

    if screenshot_path:
        ok = send_photo(screenshot_path, caption)
        log.info(f"Order executed + chart screenshot OK={ok}")
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
    action = pos_info["action"]
    result = "THANG" if pnl > 0 else "THUA"
    emoji  = GREEN if pnl > 0 else RED
    arr    = UP if action == "BUY" else DOWN
    now    = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

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
        f"{CHECK} <b>MSNR System v2.3</b> online!\n"
        f"Telegram ket noi thanh cong. San sang nhan tin hieu XAUUSD."
    )
    return ok
