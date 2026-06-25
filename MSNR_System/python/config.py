import os

MT5_LOGIN    = 257430889
MT5_PASSWORD = 'Duong8136@'
MT5_SERVER   = 'Exness-MT5Real36'
MT5_PATH     = r'C:\Program Files\MetaTrader 5-2\terminal64.exe'

SYMBOL        = 'XAUUSDc'
PRIMARY_TF    = 'H1'        # khung context cho storyline/roadblock + nhãn mặc định
LOOKBACK_BARS = 500
# Quét entry đa khung — ƯU TIÊN KHUNG LỚN (duyệt trái→phải, khung đầu có setup thắng).
# Vẫn chỉ 1 lệnh/lúc (EA AllowMultiPos=false). SL/TP giữ chung $12/$15 mọi khung.
ENTRY_TFS     = ['H1', 'M30', 'M15']
ENTRY_BARS    = 500

# ── No-trade window: KHONG vao lenh moi 5h sang (gold reopen ~05:00 GMT+7) ──
NO_TRADE_GMT7_START = 5     # gio bat dau chan (GMT+7)
NO_TRADE_GMT7_END   = 6     # gio het chan (GMT+7) -> chan [05:00, 06:00) chi ne phut vang mo cua

# ── Anti-extreme: ne entry xau (SELL day / BUY dinh) ──
USE_ANTI_EXTREME  = True
ANTI_EXT_LOOKBACK = 12      # so nen xet range gan day
ANTI_EXT_THRESH   = 0.30    # SELL chan neu gia < 30% range (sat day); BUY neu > 70% (sat dinh)
ANTI_EXT_STREAK   = 4       # so nen cung mau lien tiep = da duoi suc -> ne

PEAK_LOOKBACK = 3
MIN_LEVEL_GAP = 1.0

# ── Risk Parameters ────────────────────────────────────────────────
RISK_PCT         = 0.95
FIXED_SL_USD     = 12.0    # SL co dinh $12 (gia vang)
FIXED_TP_USD     = 10.0    # TP co dinh $10 (gia vang) -> RR 10/12 = 0.83
MIN_RR           = 0.8     # TP10<SL12 -> RR 0.83; ha nguong de KHONG chan het lenh
MAX_LOT          = 2.0
# ── Tran cung tien lo moi lenh (cent account) ──────────────────────
# Lo/lenh KHONG bao gio vuot MAX_SL_CENT cent du balance lon.
# calc_lot cap lot <= MAX_SL_CENT/(FIXED_SL_USD*100). Voi SL$12 -> lot <= 0.08.
MAX_SL_CENT      = 98.0

# ── Money management v3.1 (SL12/TP15 + BE@+10 + Crash ATR ride) ─────
# Phase 0 : SL = entry ∓ $12, TP = entry ± $15 (co dinh, RR 1.25)
# BE      : +$10 → SL = entry (breakeven)
# CRASH   : gia chay thuan huong ≥ CRASH_TRIG_ATR×ATR trong CRASH_LOOKBACK nen
#           → THAO TP (tp=0) + SL trail = gia hien tai ∓ ATR×CRASH_ATR_MULT
#           (chi siet, san BE; ride con song manh thay vi chot $15)
TRAIL_PH1_TRIGGER  = 8.0    # = BE trigger (gia di +$8)
TRAIL_PH1_LOCK     = 1.0    # +$8 -> SL = entry + $1 (lock duong 1 gia vang)
BE_TRIGGER         = 8.0    # +$8 profit → doi SL
BE_LOCK            = 1.0    # SL = entry + $1 (EA dung input BeTrigger/BeLock — phai sua + compile EA)
CRASH_TRIG_ATR     = 1.5    # cu chay thuan huong ≥ x×ATR(14) trong CRASH_LOOKBACK nen
CRASH_LOOKBACK     = 3
CRASH_ATR_MULT     = 1.0    # crash → SL trail = gia hien tai ∓ ATR×1.0
ATR_PERIOD         = 14
ATR_TRAIL_X        = 1.0    # (legacy) = CRASH_ATR_MULT
# Legacy Ph2/Ph3 — KHONG con dung (TP $15 dong truoc), giu de tuong thich import
TRAIL_PH2_TRIGGER  = 15.0
TRAIL_PH2_LOCK     = 10.0
TRAIL_PH3_TRIGGER  = 22.0
TRAIL_PH3_LOCK     = 3.0

# ── Zone Re-entry Block ────────────────────────────────────────────
# Moi zone+huong duoc phep toi da ZONE_MAX_TRADES lenh.
# Khi lenh thu N dong (SL/TP) -> zone bi khoa ZONE_BLOCK_HOURS gio
ZONE_MAX_TRADES  = 2
ZONE_BLOCK_HOURS = 4
ZONE_BLOCK_TOL   = 5.0   # USD — be rong zone
# Legacy aliases (backward compat)
TRAIL_PHASE1_PROFIT = TRAIL_PH2_TRIGGER
TRAIL_PHASE2_PROFIT = TRAIL_PH3_TRIGGER
TRAIL_PHASE2_LOCK   = TRAIL_PH3_LOCK
TRAIL_TRIGGER       = TRAIL_PH3_TRIGGER
TRAIL_LOCK_USD      = TRAIL_PH3_LOCK

# ── Confluence ─────────────────────────────────────────────────────
MIN_CONFLUENCE = 2     # bat ky 2 trong 3: A/V Level + Trendline + Gap SnR
CONFLUENCE_TOL = 3.0   # USD — khoang cach toi da giua gia va level/trendline

# Level UNFRESH (da cham <= MAX_LEVEL_TOUCHES lan) van duoc tinh confluence
# (MSNR: unfresh yeu hon fresh nhung van giao dich duoc)
ALLOW_UNFRESH_LEVELS = True
MAX_LEVEL_TOUCHES    = 2

# ── Prop Firm Guards ───────────────────────────────────────────────
MAX_DAILY_LOSS_PCT = 4.5
MAX_TOTAL_DD_PCT   = 9.0

# ══════════════════════════════════════════════════════════════════
#  MSNR v3.0 — Storyline / Entry models / Rejection / 2 loại entry
#  Tất cả gate bằng flag: tắt hết = quay về hành vi v2.x.
# ══════════════════════════════════════════════════════════════════

# ── MTF Storyline (bias đa khung) ──────────────────────────────────
USE_STORYLINE         = True
STORYLINE_TFS         = ['D1', 'H4']   # khung lấy bias (H1 = khung thực thi)
STORYLINE_PRIORITY    = ['D1', 'H4']   # thứ tự ưu tiên quyết hướng (Daily trước)
STORYLINE_SWING_LB    = 3              # lookback swing cho bias
STORYLINE_HARD_FILTER = True           # True = CHẶN lệnh ngược storyline (trừ setup mạnh dưới)
STORYLINE_BARS        = 300            # số nến tải cho mỗi khung bias

# ── Ngược bias: cho lệnh NGƯỢC storyline khi setup mạnh ─────────────
# Hard filter vẫn chặn ngược bias, TRỪ KHI hội đủ điều kiện mạnh:
COUNTER_BIAS_ALLOW             = True   # bật chế độ ngược-bias có điều kiện
COUNTER_BIAS_MIN_CONF          = 3      # confluence tối thiểu cho lệnh ngược
COUNTER_BIAS_REQUIRE_REJECTION = True   # bắt buộc có nến Rejection (CONFIRMED)
COUNTER_BIAS_REQUIRE_PREMIUM   = True   # bắt buộc level FRESH / QM / MISS
COUNTER_BIAS_REQUIRE_ROADBLOCK = False  # ưu tiên đúng roadblock (không bắt buộc)

# ── Roadblock ──────────────────────────────────────────────────────
USE_ROADBLOCK = True
ROADBLOCK_TOL = 5.0    # USD — coi là "đang ở roadblock"

# ── Entry models ───────────────────────────────────────────────────
USE_QM        = True
QM_TOL        = 3.0    # USD — giá hồi về quanh vai phải
USE_411       = False  # 411 nhiễu hơn, mặc định TẮT
SETUP411_TOL  = 3.0

# ── MISS (level rất khỏe) ──────────────────────────────────────────
USE_MISS       = True
MISS_LOOKAHEAD = 10    # số nến sau khi tạo level để xét MISS
MISS_TOL       = 2.0   # USD — wick không chạm lại trong khoảng này
MISS_MIN_MOVE  = 5.0   # USD — giá phải bỏ chạy tối thiểu

# ── Rejection candle (nến từ chối — CONFIRM) ───────────────────────
USE_REJECTION      = True
REJ_WICK_RATIO     = 0.5    # râu ≥ 50% range nến
REJ_BODY_MAX_RATIO = 0.5    # thân ≤ 50% range nến
REJ_TOL            = 2.0    # USD — râu phải chạm tới level

# ── Entry Mode: 2 loại entry ───────────────────────────────────────
# 'CONFIRMED' : chỉ vào khi có nến Rejection đóng (market) — an toàn
# 'LIMIT'     : đặt limit nghỉ tại level/apex, không chờ confirm — bắt râu
# 'BOTH'      : ưu tiên CONFIRMED nếu vừa có rejection; nếu không, đặt LIMIT
ENTRY_MODE         = 'BOTH'
LIMIT_APPROACH_TOL = 8.0    # USD — chỉ đặt limit khi giá đã tiến tới gần này
LIMIT_MIN_DISTANCE = 1.0    # USD — limit phải cách giá tối thiểu (đúng phía)
LIMIT_ZONE_OFFSET  = 0.8    # USD — limit lùi NHẸ vào trong level (đón râu quét → fill đẹp)
CONFIRM_MAX_CHASE  = 4.0    # USD — giá cách level > ngưỡng này thì KHÔNG vào market (ngừng đuổi)
PENDING_EXPIRY_SEC = 1800   # EA hủy pending limit sau N giây nếu chưa khớp

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE    = os.path.join(BASE_DIR, 'logs', 'msnr.log')

# Signal file phai nam trong Common\Files de EA (MQL5) co the doc duoc
# MQL5 FileOpen() chi cho phep doc/ghi trong terminal sandbox
# Common\Files la folder chia se giua tat ca MT5 terminals + Python
COMMON_FILES = r"C:\Users\durable1\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
SIGNAL_FILE  = os.path.join(COMMON_FILES, 'signal.json')

ALLOW_SWING_OVERNIGHT = True

TRENDLINE_TOUCH_TOLERANCE = 0.30
