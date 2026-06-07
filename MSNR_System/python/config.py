import os

MT5_LOGIN    = 433731900
MT5_PASSWORD = 'Exness-MT5Trial7'
MT5_SERVER   = 'Exness-MT5Trial7'
MT5_PATH     = r'C:\Program Files\MetaTrader 5-2\terminal64.exe'

SYMBOL        = 'XAUUSDm'
PRIMARY_TF    = 'H1'
LOOKBACK_BARS = 500
PEAK_LOOKBACK = 3
MIN_LEVEL_GAP = 1.0

# ── Risk Parameters ────────────────────────────────────────────────
RISK_PCT         = 0.95    # <1% per trade (0.95% de co buffer)
FIXED_SL_USD     = 18.0    # SL co dinh $18 tu entry (gia vang)
MIN_RR           = 1.0     # TP toi thieu 1:1 (>= $18)
TRAIL_TRIGGER    = 23.0    # Khi lai $23 -> doi SL
TRAIL_LOCK_USD   = 18.0    # Doi SL ve entry + $18 (lock 1R profit)
MAX_LOT          = 2.0

# ── Prop Firm Guards ───────────────────────────────────────────────
MAX_DAILY_LOSS_PCT = 4.5
MAX_TOTAL_DD_PCT   = 9.0

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNAL_FILE = os.path.join(BASE_DIR, 'signals', 'signal.json')
LOG_FILE    = os.path.join(BASE_DIR, 'logs',    'msnr.log')

ALLOW_SWING_OVERNIGHT = True

TRENDLINE_TOUCH_TOLERANCE = 0.30
