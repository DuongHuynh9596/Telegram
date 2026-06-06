"""
analyzer2.py — XAUUSD Macro Signal Bot v2
Local laptop only | MT5 account 46320764 | Telegram OFF
3 Tiers: Multi-TF Technical + Session Filter + ATR SL/TP
"""

import time, json, subprocess, traceback, csv, os
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import yfinance as yf
import numpy as np
import pandas as pd
import schedule

# ─── CONFIG ────────────────────────────────────────────────────────────────────
MT5_PATH     = r"C:\Users\ADMIN\Desktop\Công việc\MT51\terminal64.exe"
MT5_LOGIN    = 463207464
MT5_PASSWORD = "Drduong9190@.@"
MT5_SERVER   = "Exness-MT5Trial17"

TELEGRAM_ENABLED = False   # Local machine — chỉ trade, không gửi Telegram

LOT_SIZE     = 0.01
NUM_POSITIONS = 3          # max số lệnh đồng thời
MIN_CONFIDENCE = 65        # ngưỡng confidence tối thiểu
MIN_CONFLUENCE = 4         # tối thiểu 4/7 factors
MAGIC        = 20240102    # khác VPS bot (20240101)

SL_ATR_MULT  = 1.5
TP1_ATR_MULT = 1.5
TP2_ATR_MULT = 3.0

MT5_COMMON       = Path(os.environ.get("APPDATA","C:/Users/ADMIN/AppData/Roaming")) / "MetaQuotes/Terminal/Common/Files"
SIGNAL_FILE      = MT5_COMMON / "signal_v2.json"
LAST_SIGNAL_FILE = MT5_COMMON / "last_signal_v2.json"
LOG_FILE         = Path("C:/signal/signal_log.csv")

# Session definitions (UTC)
SESSIONS = {
    "london":    (8,  12),
    "new_york":  (13, 17),
    "pre_london":(6,  8),
    "asian":     (0,  6),
}

# ─── INDICATORS ────────────────────────────────────────────────────────────────
def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calc_bbands(series: pd.Series, period=20, std_mult=2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower

# ─── MARKET STRUCTURE ─────────────────────────────────────────────────────────
def detect_swing_points(df: pd.DataFrame, window: int = 5):
    """Detect swing highs and swing lows"""
    highs, lows = [], []
    for i in range(window, len(df) - window):
        if df['High'].iloc[i] == df['High'].iloc[i-window:i+window+1].max():
            highs.append((df.index[i], df['High'].iloc[i]))
        if df['Low'].iloc[i] == df['Low'].iloc[i-window:i+window+1].min():
            lows.append((df.index[i], df['Low'].iloc[i]))
    return highs, lows

def detect_fvg(df: pd.DataFrame):
    """Detect Fair Value Gaps (imbalance zones)"""
    fvg_list = []
    for i in range(2, len(df)):
        # Bullish FVG: low[i] > high[i-2]
        if df['Low'].iloc[i] > df['High'].iloc[i-2]:
            fvg_list.append({
                'type': 'bullish',
                'top':  df['Low'].iloc[i],
                'bot':  df['High'].iloc[i-2],
                'time': df.index[i]
            })
        # Bearish FVG: high[i] < low[i-2]
        elif df['High'].iloc[i] < df['Low'].iloc[i-2]:
            fvg_list.append({
                'type': 'bearish',
                'top':  df['Low'].iloc[i-2],
                'bot':  df['High'].iloc[i],
                'time': df.index[i]
            })
    return fvg_list[-5:] if fvg_list else []  # return last 5 FVGs

def get_market_structure(df: pd.DataFrame):
    """Determine HH/HL (bullish) vs LH/LL (bearish) structure"""
    if len(df) < 20:
        return "unknown"
    highs, lows = detect_swing_points(df, window=3)
    if len(highs) < 2 or len(lows) < 2:
        return "ranging"
    last_2h = [h[1] for h in highs[-2:]]
    last_2l = [l[1] for l in lows[-2:]]
    hh = last_2h[1] > last_2h[0]
    hl = last_2l[1] > last_2l[0]
    lh = last_2h[1] < last_2h[0]
    ll = last_2l[1] < last_2l[0]
    if hh and hl:   return "bullish"
    if lh and ll:   return "bearish"
    return "ranging"

# ─── SESSION ───────────────────────────────────────────────────────────────────
def get_current_session():
    utc_hour = datetime.now(timezone.utc).hour
    if 8 <= utc_hour < 12:   return "london"
    if 13 <= utc_hour < 17:  return "new_york"
    if 6  <= utc_hour < 8:   return "pre_london"
    if 0  <= utc_hour < 6:   return "asian"
    return "off"

def should_analyze():
    """Chỉ phân tích trong session có thanh khoản cao"""
    sess = get_current_session()
    allowed = ["london", "new_york", "pre_london"]
    if sess in allowed:
        print(f"  [Session] {sess.upper()} — GO")
        return True
    print(f"  [Session] {sess.upper()} — SKIP (low liquidity)")
    return False

def get_asian_range():
    """Lấy Asian session high/low (22:00-07:00 UTC previous day)"""
    try:
        df = yf.download("GC=F", period="3d", interval="1h", progress=False, auto_adjust=True)
        if df.empty:
            return None, None
        df.index = df.index.tz_localize(None) if df.index.tzinfo is None else df.index.tz_convert(None)
        # Asian = UTC 22:00 prev day to 07:00 today
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        asian_end   = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)
        asian_start = now_utc.replace(hour=22, minute=0, second=0, microsecond=0) - pd.Timedelta(days=1)
        mask = (df.index >= asian_start) & (df.index <= asian_end)
        asian_df = df[mask]
        if asian_df.empty:
            return None, None
        return float(asian_df['High'].max()), float(asian_df['Low'].min())
    except Exception as e:
        print(f"  [Asian range] Error: {e}")
        return None, None

# ─── DATA FETCH ────────────────────────────────────────────────────────────────
def fetch_gold_mtf():
    """
    Fetch XAUUSD data: D1, H4 (resampled từ H1), H1
    Returns dict with keys: d1, h4, h1
    """
    result = {}
    try:
        # H1 — 200 bars cho H1 và resample H4
        df_h1 = yf.download("GC=F", period="30d", interval="1h", progress=False, auto_adjust=True)
        if df_h1.empty:
            print("  [MTF] Không lấy được H1 data")
            return {}
        df_h1.columns = [c[0] if isinstance(c, tuple) else c for c in df_h1.columns]
        df_h1 = df_h1.dropna()

        # H4 = resample từ H1
        df_h4 = df_h1.resample('4h').agg({
            'Open': 'first', 'High': 'max',
            'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        # D1
        df_d1 = yf.download("GC=F", period="90d", interval="1d", progress=False, auto_adjust=True)
        df_d1.columns = [c[0] if isinstance(c, tuple) else c for c in df_d1.columns]
        df_d1 = df_d1.dropna()

        result['h1'] = df_h1.tail(100)
        result['h4'] = df_h4.tail(60)
        result['d1'] = df_d1.tail(60)
        print(f"  [MTF] D1:{len(result['d1'])}bars H4:{len(result['h4'])}bars H1:{len(result['h1'])}bars")
    except Exception as e:
        print(f"  [MTF] Error: {e}")
        traceback.print_exc()
    return result

def fetch_enhanced_macro():
    """
    Fetch macro data nâng cao:
    GC=F, DXY, TNX, VIX, SI=F, TIP (real yield proxy), TLT, JPY=X, CL=F
    """
    tickers = {
        "XAUUSD": "GC=F",
        "DXY":    "DX-Y.NYB",
        "US10Y":  "^TNX",
        "VIX":    "^VIX",
        "SILVER": "SI=F",
        "TIP":    "TIP",     # TIPS ETF — real yield proxy, corr -0.82 with gold
        "TLT":    "TLT",     # Long bond ETF
        "JPY":    "JPY=X",   # USD/JPY — safe haven
        "OIL":    "CL=F",    # Crude oil — risk/inflation proxy
    }
    macro = {}
    for name, ticker in tickers.items():
        try:
            df = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=True)
            if df.empty or len(df) < 2:
                macro[name] = {"price": 0, "change_pct": 0, "prev": 0}
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            price = float(df['Close'].iloc[-1])
            prev  = float(df['Close'].iloc[-2])
            chg   = (price - prev) / prev * 100 if prev else 0
            # 5-day trend
            price_5d = float(df['Close'].iloc[0])
            trend_5d = (price - price_5d) / price_5d * 100 if price_5d else 0
            macro[name] = {
                "price": round(price, 4),
                "prev":  round(prev, 4),
                "change_pct": round(chg, 2),
                "trend_5d": round(trend_5d, 2),
            }
        except Exception as e:
            macro[name] = {"price": 0, "change_pct": 0, "prev": 0}
            print(f"  [Macro] {name} error: {e}")
    return macro

# ─── PRE-SCORING ───────────────────────────────────────────────────────────────
def calculate_pre_score(mtf: dict, macro: dict, session: str):
    """
    Pre-score 7 factors trước khi gọi Claude API.
    Trả về (score, max_score, direction_hint, factors_dict)
    """
    factors = {}
    bull_score = 0
    bear_score = 0

    # --- Factor 1: D1 trend (EMA 21/50/200) ---
    d1 = mtf.get('d1', pd.DataFrame())
    if not d1.empty and len(d1) >= 50:
        ema21_d1 = calc_ema(d1['Close'], 21).iloc[-1]
        ema50_d1 = calc_ema(d1['Close'], 50).iloc[-1]
        price_d1 = d1['Close'].iloc[-1]
        if price_d1 > ema21_d1 > ema50_d1:
            factors['d1_trend'] = 'bullish'
            bull_score += 1
        elif price_d1 < ema21_d1 < ema50_d1:
            factors['d1_trend'] = 'bearish'
            bear_score += 1
        else:
            factors['d1_trend'] = 'ranging'
    else:
        factors['d1_trend'] = 'unknown'

    # --- Factor 2: H4 structure ---
    h4 = mtf.get('h4', pd.DataFrame())
    if not h4.empty and len(h4) >= 20:
        h4_struct = get_market_structure(h4)
        factors['h4_structure'] = h4_struct
        if h4_struct == 'bullish':   bull_score += 1
        elif h4_struct == 'bearish': bear_score += 1
    else:
        factors['h4_structure'] = 'unknown'

    # --- Factor 3: H1 RSI momentum ---
    h1 = mtf.get('h1', pd.DataFrame())
    if not h1.empty and len(h1) >= 20:
        rsi_h1 = calc_rsi(h1['Close']).iloc[-1]
        factors['rsi_h1'] = round(float(rsi_h1), 1)
        if rsi_h1 < 40:   bull_score += 1   # oversold = potential bounce
        elif rsi_h1 > 60: bear_score += 1   # overbought = potential drop
    else:
        factors['rsi_h1'] = 50

    # --- Factor 4: Real Yield (TIP ETF) ---
    tip = macro.get('TIP', {})
    tip_chg = tip.get('change_pct', 0)
    factors['tip_change'] = tip_chg
    # TIP falling = real yield rising = BEARISH for gold
    # TIP rising  = real yield falling = BULLISH for gold
    if tip_chg > 0.1:
        factors['real_yield_signal'] = 'bullish'
        bull_score += 1
    elif tip_chg < -0.1:
        factors['real_yield_signal'] = 'bearish'
        bear_score += 1
    else:
        factors['real_yield_signal'] = 'neutral'

    # --- Factor 5: DXY trend ---
    dxy = macro.get('DXY', {})
    dxy_chg = dxy.get('change_pct', 0)
    dxy_5d  = dxy.get('trend_5d', 0)
    factors['dxy_change'] = dxy_chg
    # DXY rising = BEARISH for gold
    if dxy_chg < -0.1 or dxy_5d < -0.3:
        factors['dxy_signal'] = 'bullish'
        bull_score += 1
    elif dxy_chg > 0.1 or dxy_5d > 0.3:
        factors['dxy_signal'] = 'bearish'
        bear_score += 1
    else:
        factors['dxy_signal'] = 'neutral'

    # --- Factor 6: JPY safe haven ---
    jpy = macro.get('JPY', {})
    jpy_chg = jpy.get('change_pct', 0)
    # USD/JPY falling = JPY strengthening = safe haven = BULLISH gold
    if jpy_chg < -0.2:
        factors['jpy_signal'] = 'bullish'
        bull_score += 1
    elif jpy_chg > 0.2:
        factors['jpy_signal'] = 'bearish'
        bear_score += 1
    else:
        factors['jpy_signal'] = 'neutral'
    factors['jpy_change'] = jpy_chg

    # --- Factor 7: Session quality ---
    session_weight = {'london': 2, 'new_york': 2, 'pre_london': 1, 'asian': 0, 'off': 0}
    sess_score = session_weight.get(session, 0)
    factors['session'] = session
    factors['session_quality'] = sess_score
    if sess_score >= 2:
        bull_score += 0.5
        bear_score += 0.5  # session counts for both sides

    # Final
    total = bull_score + bear_score
    if bull_score > bear_score:
        direction = "BUY"
        conf_score = int(bull_score / 7 * 100) if total > 0 else 0
    elif bear_score > bull_score:
        direction = "SELL"
        conf_score = int(bear_score / 7 * 100) if total > 0 else 0
    else:
        direction = "HOLD"
        conf_score = 40

    confluence = max(int(bull_score), int(bear_score))
    factors['bull_score'] = round(bull_score, 1)
    factors['bear_score'] = round(bear_score, 1)

    print(f"  [PreScore] BULL={bull_score:.1f} BEAR={bear_score:.1f} → {direction} conf≈{conf_score}% confluence≈{confluence}/7")
    return conf_score, confluence, direction, factors

# ─── CLAUDE PROMPT ─────────────────────────────────────────────────────────────
def build_claude_context(mtf: dict, macro: dict, pre_factors: dict, session: str, asian_hi, asian_lo):
    """Build structured JSON context để gửi Claude"""

    # Technical summary
    d1 = mtf.get('d1', pd.DataFrame())
    h4 = mtf.get('h4', pd.DataFrame())
    h1 = mtf.get('h1', pd.DataFrame())

    tech = {}
    if not d1.empty and len(d1) >= 50:
        d1_close = d1['Close']
        tech['d1'] = {
            'close': round(float(d1_close.iloc[-1]), 2),
            'ema21': round(float(calc_ema(d1_close, 21).iloc[-1]), 2),
            'ema50': round(float(calc_ema(d1_close, 50).iloc[-1]), 2),
            'ema200': round(float(calc_ema(d1_close, 200).iloc[-1]), 2) if len(d1) >= 200 else None,
            'rsi': round(float(calc_rsi(d1_close).iloc[-1]), 1),
            'atr': round(float(calc_atr(d1['High'], d1['Low'], d1_close).iloc[-1]), 2),
            'trend': pre_factors.get('d1_trend', 'unknown'),
        }
    if not h4.empty and len(h4) >= 20:
        h4_close = h4['Close']
        macd_l, macd_s, macd_h = calc_macd(h4_close)
        bbu, bbm, bbl = calc_bbands(h4_close)
        tech['h4'] = {
            'close': round(float(h4_close.iloc[-1]), 2),
            'ema21': round(float(calc_ema(h4_close, 21).iloc[-1]), 2),
            'ema50': round(float(calc_ema(h4_close, 50).iloc[-1]), 2),
            'rsi': round(float(calc_rsi(h4_close).iloc[-1]), 1),
            'atr': round(float(calc_atr(h4['High'], h4['Low'], h4_close).iloc[-1]), 2),
            'macd_hist': round(float(macd_h.iloc[-1]), 3),
            'bb_upper': round(float(bbu.iloc[-1]), 2),
            'bb_lower': round(float(bbl.iloc[-1]), 2),
            'structure': pre_factors.get('h4_structure', 'unknown'),
        }
        # FVG
        fvgs = detect_fvg(h4.tail(20))
        if fvgs:
            tech['h4']['fvg_recent'] = [{'type': f['type'], 'zone': [round(f['bot'],2), round(f['top'],2)]} for f in fvgs[-2:]]
    if not h1.empty and len(h1) >= 20:
        h1_close = h1['Close']
        tech['h1'] = {
            'close': round(float(h1_close.iloc[-1]), 2),
            'ema21': round(float(calc_ema(h1_close, 21).iloc[-1]), 2),
            'rsi': round(float(calc_rsi(h1_close).iloc[-1]), 1),
            'atr': round(float(calc_atr(h1['High'], h1['Low'], h1_close).iloc[-1]), 2),
        }

    # ATR for SL/TP calculation
    atr_h1 = tech.get('h1', {}).get('atr', tech.get('h4', {}).get('atr', 15))

    macro_summary = {
        "xauusd":       {"price": macro.get("XAUUSD",{}).get("price"), "chg1d%": macro.get("XAUUSD",{}).get("change_pct")},
        "dxy":          {"price": macro.get("DXY",{}).get("price"), "chg1d%": macro.get("DXY",{}).get("change_pct"), "trend5d%": macro.get("DXY",{}).get("trend_5d")},
        "us10y_yield":  {"value": macro.get("US10Y",{}).get("price"), "chg1d%": macro.get("US10Y",{}).get("change_pct")},
        "vix":          {"price": macro.get("VIX",{}).get("price"), "chg1d%": macro.get("VIX",{}).get("change_pct")},
        "silver_gsr":   {"silver": macro.get("SILVER",{}).get("price"), "gsr": round(macro.get("XAUUSD",{}).get("price",0) / max(macro.get("SILVER",{}).get("price",1),1), 1)},
        "tip_real_yield_proxy": {"price": macro.get("TIP",{}).get("price"), "chg1d%": macro.get("TIP",{}).get("change_pct"), "note": "TIP down=real yield up=gold bearish"},
        "tlt_bonds":    {"price": macro.get("TLT",{}).get("price"), "chg1d%": macro.get("TLT",{}).get("change_pct")},
        "usdjpy":       {"price": macro.get("JPY",{}).get("price"), "chg1d%": macro.get("JPY",{}).get("change_pct"), "note": "USDJPY down=JPY safe haven=gold bullish"},
        "crude_oil":    {"price": macro.get("OIL",{}).get("price"), "chg1d%": macro.get("OIL",{}).get("change_pct")},
    }

    context = {
        "task": "Analyze XAUUSD (gold) trading signal using top-down multi-timeframe analysis",
        "datetime_utc": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M"),
        "session": session,
        "asian_range": {"high": asian_hi, "low": asian_lo} if asian_hi else None,
        "pre_score": {
            "bull_factors": pre_factors.get('bull_score'),
            "bear_factors": pre_factors.get('bear_score'),
            "likely_direction": "BUY" if pre_factors.get('bull_score',0) > pre_factors.get('bear_score',0) else "SELL" if pre_factors.get('bear_score',0) > pre_factors.get('bull_score',0) else "HOLD",
        },
        "technical": tech,
        "macro": macro_summary,
        "atr_h1_for_sltp": atr_h1,
        "sl_atr_mult": SL_ATR_MULT,
        "tp1_atr_mult": TP1_ATR_MULT,
        "tp2_atr_mult": TP2_ATR_MULT,
    }

    prompt = f"""You are a professional gold (XAUUSD) trader. Analyze the following data using TOP-DOWN framework: D1 bias → H4 structure → H1 entry.

DATA (JSON):
{json.dumps(context, indent=2, default=str)}

ANALYSIS FRAMEWORK:
1. D1: Establish trend bias (above/below EMA21/50/200, RSI zone)
2. H4: Confirm structure (HH/HL bullish vs LH/LL bearish), MACD momentum, BB position, FVG zones
3. H1: Entry timing — RSI, EMA21 bounce/break, Asian range breakout
4. Macro: Real yield (TIP) has -0.82 correlation with gold — MOST IMPORTANT macro. DXY inverse. VIX>20 = safe haven bid. JPY falling = risk-off = gold up.
5. Session: London/NY = highest priority setups. Avoid Asian session entries.

SL/TP RULES (ATR-based):
- BUY:  entry=ask, SL=entry-(ATR×{SL_ATR_MULT}), TP1=entry+(ATR×{TP1_ATR_MULT}), TP2=entry+(ATR×{TP2_ATR_MULT})
- SELL: entry=bid, SL=entry+(ATR×{SL_ATR_MULT}), TP1=entry-(ATR×{TP1_ATR_MULT}), TP2=entry-(ATR×{TP2_ATR_MULT})
- Use ATR from H1 timeframe provided above. Round entry/sl/tp to 2 decimals.

CONFLUENCE REQUIRED (4+/7 factors for signal, else HOLD):
Factor 1: D1 trend aligns | Factor 2: H4 structure aligns | Factor 3: H1 RSI not over-extended
Factor 4: TIP signal aligns | Factor 5: DXY signal aligns | Factor 6: JPY signal aligns | Factor 7: Good session

OUTPUT — reply with ONLY this exact JSON, no markdown, no explanation:
{{"signal":"BUY|SELL|HOLD","confidence":65,"entry":3320.50,"sl":3298.50,"tp1":3342.50,"tp2":3364.50,"confluence":"5/7","reasons":["D1 bullish above EMA50","H4 HH/HL structure","RSI H1 at 45 room to run","TIP rising real yield falling","DXY weakening 5-day"],"analysis":"2-3 sentence summary","invalidation":"What would invalidate this trade"}}"""

    return prompt, atr_h1

# ─── CLAUDE API ────────────────────────────────────────────────────────────────
def analyze_with_claude(prompt: str):
    """Gọi Claude CLI để phân tích"""
    try:
        result = subprocess.run(
            ["claude.cmd", "--print", "--dangerously-skip-permissions"],
            input=prompt,
            capture_output=True, text=True, timeout=120,
            encoding='utf-8', errors='replace'
        )
        output = result.stdout.strip()
        if not output:
            output = result.stderr.strip()

        # Parse JSON từ output
        import re
        json_match = re.search(r'\{.*\}', output, re.DOTALL)
        if json_match:
            signal = json.loads(json_match.group())
            # Validate required fields
            required = ['signal', 'confidence', 'entry', 'sl', 'tp1', 'tp2']
            if all(k in signal for k in required):
                return signal
        print(f"  [Claude] Không parse được JSON: {output[:200]}")
        return None
    except subprocess.TimeoutExpired:
        print("  [Claude] Timeout 120s")
        return None
    except Exception as e:
        print(f"  [Claude] Error: {e}")
        traceback.print_exc()
        return None

# ─── SIGNAL LOG ────────────────────────────────────────────────────────────────
def log_signal(signal: dict, pre_factors: dict, session: str, mtf: dict):
    """Ghi signal vào CSV để track outcome"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not LOG_FILE.exists()

    h1 = mtf.get('h1', pd.DataFrame())
    rsi_h1 = round(float(calc_rsi(h1['Close']).iloc[-1]), 1) if not h1.empty and len(h1) >= 14 else 0

    row = {
        'timestamp':      datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
        'session':        session,
        'signal':         signal.get('signal',''),
        'confidence':     signal.get('confidence', 0),
        'confluence':     signal.get('confluence',''),
        'entry':          signal.get('entry', 0),
        'sl':             signal.get('sl', 0),
        'tp1':            signal.get('tp1', 0),
        'tp2':            signal.get('tp2', 0),
        'analysis':       signal.get('analysis','')[:100],
        'd1_trend':       pre_factors.get('d1_trend',''),
        'h4_structure':   pre_factors.get('h4_structure',''),
        'rsi_h1':         rsi_h1,
        'real_yield':     pre_factors.get('real_yield_signal',''),
        'dxy_trend':      pre_factors.get('dxy_signal',''),
        'likely_dir':     "BUY" if pre_factors.get('bull_score',0) > pre_factors.get('bear_score',0) else "SELL",
        'outcome':        '',   # fill later manually or via tracker
        'pnl_usd':        '',
    }
    with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    print(f"  [Log] Signal logged → {LOG_FILE}")

# ─── MT5 EXECUTION ─────────────────────────────────────────────────────────────
def init_mt5():
    """Khởi động MT5 — retry 3 lần, mỗi lần cách 10s"""
    for attempt in range(1, 4):
        # Thử kết nối terminal đang chạy (không cần path)
        if mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            info = mt5.account_info()
            if info:
                print(f"  [MT5] Connected (attempt {attempt}): {info.login} | Balance: {info.balance:.2f} {info.currency}")
            return True

        # Thử mở bằng path
        if mt5.initialize(path=MT5_PATH, login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            info = mt5.account_info()
            if info:
                print(f"  [MT5] Connected via path (attempt {attempt}): {info.login} | Balance: {info.balance:.2f} {info.currency}")
            return True

        err = mt5.last_error()
        print(f"  [MT5] Attempt {attempt}/3 failed: {err} — cho 10s...")
        mt5.shutdown()
        time.sleep(10)

    print(f"  [MT5] Khong ket noi duoc sau 3 lan thu")
    return False

def get_xauusd_symbol():
    """Tìm symbol XAUUSD trên MT5"""
    for sym in ["XAUUSD", "XAUUSDm", "GOLD", "XAUUSDc", "XAUUSD."]:
        info = mt5.symbol_info(sym)
        if info and info.visible:
            return sym
        if info:
            mt5.symbol_select(sym, True)
            return sym
    return None

def execute_mt5_v2(signal: dict):
    """
    Thực thi lệnh với ATR-based SL/TP từ Claude signal
    signal phải có: signal, entry, sl, tp1, tp2, confidence
    """
    sig_dir  = signal.get("signal", "HOLD")
    if sig_dir == "HOLD":
        print("  [MT5] HOLD — không mở lệnh")
        return False, "HOLD"

    conf = signal.get("confidence", 0)
    if conf < MIN_CONFIDENCE:
        print(f"  [MT5] Confidence {conf}% < {MIN_CONFIDENCE}% — bỏ qua")
        return False, f"Low confidence {conf}%"

    sym = get_xauusd_symbol()
    if not sym:
        return False, "Không tìm thấy symbol XAUUSD trên MT5"

    sym_info = mt5.symbol_info(sym)
    if not sym_info:
        return False, f"symbol_info({sym}) failed"

    tick = mt5.symbol_info_tick(sym)
    if not tick:
        return False, "Không lấy được tick"

    # Số lệnh đang mở với MAGIC này
    positions = mt5.positions_get(symbol=sym)
    magic_pos = [p for p in (positions or []) if p.magic == MAGIC]
    if len(magic_pos) >= NUM_POSITIONS:
        print(f"  [MT5] Đã có {len(magic_pos)}/{NUM_POSITIONS} lệnh — bỏ qua")
        return False, "Max positions reached"

    # Dùng SL/TP từ Claude (đã ATR-based)
    digits = sym_info.digits
    point  = sym_info.point

    if sig_dir == "BUY":
        entry = tick.ask
        sl    = round(float(signal.get('sl', entry - 15)), digits)
        tp1   = round(float(signal.get('tp1', entry + 15)), digits)
        tp2   = round(float(signal.get('tp2', entry + 30)), digits)
        order_type = mt5.ORDER_TYPE_BUY
    else:
        entry = tick.bid
        sl    = round(float(signal.get('sl', entry + 15)), digits)
        tp1   = round(float(signal.get('tp1', entry - 15)), digits)
        tp2   = round(float(signal.get('tp2', entry - 30)), digits)
        order_type = mt5.ORDER_TYPE_SELL

    # Mở 2 lệnh: TP1 (partial close target) + TP2 (full target)
    results = []
    for tp_val, label in [(tp1, "TP1"), (tp2, "TP2")]:
        req = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    sym,
            "volume":    LOT_SIZE,
            "type":      order_type,
            "price":     entry,
            "sl":        sl,
            "tp":        tp_val,
            "deviation": 20,
            "magic":     MAGIC,
            "comment":   f"analyzer2_{label}_c{conf}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"  [MT5] {sig_dir} {label} DONE | ticket={res.order} entry={entry:.2f} SL={sl:.2f} TP={tp_val:.2f}")
            results.append(res.order)
        else:
            err = mt5.last_error()
            code = res.retcode if res else "None"
            print(f"  [MT5] {sig_dir} {label} FAILED retcode={code} | {err}")

    if results:
        return True, f"Opened {len(results)} orders: {results}"
    return False, "All orders failed"

def manage_positions_v2():
    """
    Quản lý BE (Break Even) cho các lệnh đang chạy:
    - Khi H1 RSI > 70 (buy) hoặc < 30 (sell) → cân nhắc dời SL lên BE
    Được gọi mỗi lần run()
    """
    try:
        positions = mt5.positions_get()
        if not positions:
            return
        magic_pos = [p for p in positions if p.magic == MAGIC]
        if not magic_pos:
            return

        for pos in magic_pos:
            sym   = pos.symbol
            tick  = mt5.symbol_info_tick(sym)
            if not tick:
                continue
            profit_pts = abs(tick.bid - pos.price_open) if pos.type == mt5.ORDER_TYPE_BUY else abs(pos.price_open - tick.ask)
            # Simple BE: nếu lời >= 10 USD/lot thì dời SL lên mức hoà vốn
            if pos.profit > 0 and abs(pos.sl - pos.price_open) > 0:
                if pos.profit >= LOT_SIZE * 1000:   # ~$10/0.01lot tương đương
                    new_sl = pos.price_open + (1 if pos.type == mt5.ORDER_TYPE_BUY else -1) * 2 * mt5.symbol_info(sym).point
                    if pos.type == mt5.ORDER_TYPE_BUY and new_sl > pos.sl:
                        _move_sl(pos.ticket, new_sl)
                    elif pos.type == mt5.ORDER_TYPE_SELL and new_sl < pos.sl:
                        _move_sl(pos.ticket, new_sl)
    except Exception as e:
        print(f"  [ManagePos] Error: {e}")

def _move_sl(ticket: int, new_sl: float):
    """Dời SL của lệnh"""
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       new_sl,
    }
    res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"  [BE] Ticket {ticket} SL moved to {new_sl:.2f}")

# ─── SIGNAL FILE ───────────────────────────────────────────────────────────────
def write_signal_file(signal: dict):
    """Ghi signal.json vào MT5 Common/Files"""
    try:
        MT5_COMMON.mkdir(parents=True, exist_ok=True)
        sig_out = dict(signal)
        sig_out['timestamp'] = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        with open(SIGNAL_FILE, 'w') as f:
            json.dump(sig_out, f, indent=2)

        if signal.get('signal') != 'HOLD':
            with open(LAST_SIGNAL_FILE, 'w') as f:
                json.dump(sig_out, f, indent=2)
        print(f"  [SignalFile] Written: {SIGNAL_FILE}")
    except Exception as e:
        print(f"  [SignalFile] Error: {e}")

# ─── MAIN RUN ──────────────────────────────────────────────────────────────────
def run():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"[analyzer2] {now_str}")
    print(f"{'='*60}")

    # Session gate
    if not should_analyze():
        return

    session = get_current_session()

    # MT5 init
    if not init_mt5():
        print("  [MT5] Không kết nối được MT5")
        return

    try:
        # Manage existing positions
        manage_positions_v2()

        # Fetch data
        print("  Đang lấy dữ liệu multi-timeframe...")
        mtf   = fetch_gold_mtf()
        macro = fetch_enhanced_macro()

        if not mtf:
            print("  Không lấy được MTF data — bỏ qua")
            return

        # Asian range
        asian_hi, asian_lo = get_asian_range()

        # Pre-scoring
        pre_conf, pre_confluence, pre_dir, pre_factors = calculate_pre_score(mtf, macro, session)

        # Kiểm tra minimum confluence
        if pre_confluence < MIN_CONFLUENCE:
            print(f"  [PreScore] Confluence {pre_confluence}/7 < {MIN_CONFLUENCE} — bỏ qua, thị trường không rõ ràng")
            return

        print(f"  [PreScore] Đủ confluence {pre_confluence}/7 → gọi Claude API...")

        # Build Claude prompt
        prompt, atr_h1 = build_claude_context(mtf, macro, pre_factors, session, asian_hi, asian_lo)

        # Call Claude
        signal = analyze_with_claude(prompt)

        if not signal:
            print("  [Claude] Không nhận được signal hợp lệ")
            return

        sig_dir  = signal.get('signal', 'HOLD')
        sig_conf = signal.get('confidence', 0)
        sig_conf_str = signal.get('confluence', '?/7')
        print(f"\n  ▶ SIGNAL: {sig_dir} | confidence={sig_conf}% | confluence={sig_conf_str}")
        print(f"  ▶ Entry={signal.get('entry')} SL={signal.get('sl')} TP1={signal.get('tp1')} TP2={signal.get('tp2')}")
        if signal.get('analysis'):
            print(f"  ▶ Analysis: {signal.get('analysis','')[:150]}")

        # Log signal
        log_signal(signal, pre_factors, session, mtf)

        # Write signal file
        write_signal_file(signal)

        # Execute trade
        if sig_dir != "HOLD" and sig_conf >= MIN_CONFIDENCE:
            ok, msg = execute_mt5_v2(signal)
            print(f"  [Execute] {'✓' if ok else '✗'} {msg}")
        else:
            print(f"  [Execute] HOLD hoặc confidence thấp ({sig_conf}%) — không mở lệnh")

    except Exception as e:
        print(f"  [run] Exception: {e}")
        traceback.print_exc()
    finally:
        mt5.shutdown()
        print("  [MT5] shutdown")

# ─── SCHEDULER ─────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  XAUUSD Macro Signal Bot v2 — LOCAL LAPTOP")
    print(f"  MT5 account : {MT5_LOGIN} @ {MT5_SERVER}")
    print(f"  Telegram    : {'ON' if TELEGRAM_ENABLED else 'OFF'}")
    print(f"  Min Conf    : {MIN_CONFIDENCE}% | Min Confluence: {MIN_CONFLUENCE}/7")
    print(f"  SL/TP mult  : {SL_ATR_MULT}×ATR / {TP1_ATR_MULT}×ATR / {TP2_ATR_MULT}×ATR")
    print(f"  Log file    : {LOG_FILE}")
    print("=" * 60)

    # Chạy ngay lần đầu
    run()

    # Schedule mỗi 5 phút
    schedule.every(5).minutes.do(run)
    print("\n  Scheduler: mỗi 5 phút | Ctrl+C để dừng\n")

    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
