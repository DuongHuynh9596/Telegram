# MSNR System - Multi-Timeframe Storyline (bias đa khung + Roadblock)
#
# Storyline = hướng đi của giá từ SnR này sang SnR khác trên khung LỚN.
# Daily quan trọng nhất → rồi Weekly/H4. Không giao dịch ngược storyline.
# Roadblock = SnR ở khung THẤP HƠN 1 BẬC so với khung storyline — nơi pullback
# dễ xảy ra trước khi giá đi tiếp theo hướng storyline.
from dataclasses import dataclass, field
from msnr_detector import MSNRDetector
from config import (STORYLINE_SWING_LB, ROADBLOCK_TOL, STORYLINE_PRIORITY)

# Thứ tự khung từ lớn → nhỏ (để suy ra roadblock = bậc kế dưới)
_TF_ORDER = ["MN1", "W1", "D1", "H4", "H1", "M30", "M15", "M5", "M1"]


def _lower_tf(tf):
    if tf not in _TF_ORDER:
        return None
    i = _TF_ORDER.index(tf)
    return _TF_ORDER[i + 1] if i + 1 < len(_TF_ORDER) else None


@dataclass
class TFContext:
    tf: str
    bias: str                      # 'UP' / 'DOWN' / 'NEUTRAL'
    bos: object                    # Break-of-structure gần nhất: 'UP'/'DOWN'/None
    swing_highs: list = field(default_factory=list)
    swing_lows: list  = field(default_factory=list)
    levels: list      = field(default_factory=list)


@dataclass
class Storyline:
    contexts: dict                 # tf -> TFContext
    direction: str                 # hướng storyline tổng hợp
    origin_tf: object              # khung neo storyline (Daily ưu tiên), hoặc None
    roadblocks: list = field(default_factory=list)   # SnRLevel ở khung roadblock

    def bias_of(self, tf):
        c = self.contexts.get(tf)
        return c.bias if c else "NEUTRAL"

    def allows(self, action):
        """True nếu action thuận hướng storyline (hoặc storyline NEUTRAL)."""
        if self.direction == "NEUTRAL":
            return True
        want = "UP" if action == "BUY" else "DOWN"
        return self.direction == want

    def at_roadblock(self, price, tol=ROADBLOCK_TOL):
        return any(abs(rb.price - price) <= tol for rb in self.roadblocks)

    def summary(self):
        parts = [f"{tf}={c.bias}" for tf, c in self.contexts.items()]
        return (f"dir={self.direction} origin={self.origin_tf or '-'} "
                f"[{', '.join(parts)}] roadblocks={len(self.roadblocks)}")


def _swings(closes, lb):
    highs, lows = [], []
    for i in range(lb, len(closes) - lb):
        seg = closes[i - lb: i + lb + 1]
        if closes[i] == seg.max():
            highs.append((i, float(closes[i])))
        elif closes[i] == seg.min():
            lows.append((i, float(closes[i])))
    return highs, lows


def _bias_from_swings(highs, lows, last_close):
    """
    Bias theo cấu trúc swing:
      HH + HL → UP ; LH + LL → DOWN ; còn lại NEUTRAL.
    BOS (break of structure): close vượt swing high/low gần nhất → override NEUTRAL.
    """
    bias, bos = "NEUTRAL", None

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1][1] > highs[-2][1]
        hl = lows[-1][1]  > lows[-2][1]
        lh = highs[-1][1] < highs[-2][1]
        ll = lows[-1][1]  < lows[-2][1]
        if hh and hl:
            bias = "UP"
        elif lh and ll:
            bias = "DOWN"

    if highs and last_close > highs[-1][1]:
        bos = "UP"
    elif lows and last_close < lows[-1][1]:
        bos = "DOWN"

    if bias == "NEUTRAL" and bos:
        bias = bos
    return bias, bos


def _filter_roadblocks(levels, direction, price):
    """
    Roadblock = SnR theo hướng pullback, đứng giữa giá và đích storyline:
      - storyline UP   → roadblock là Support (V / GAP_S) NẰM DƯỚI giá
      - storyline DOWN → roadblock là Resistance (A / GAP_R) NẰM TRÊN giá
    Chỉ lấy level còn hiệu lực (FRESH hoặc chạm ít).
    """
    out = []
    for l in levels:
        if l.state == "UNFRESH" and l.touch_count > 2:
            continue
        if direction == "UP" and l.level_type in ("V", "GAP_S") and l.price < price:
            out.append(l)
        elif direction == "DOWN" and l.level_type in ("A", "GAP_R") and l.price > price:
            out.append(l)
    out.sort(key=lambda l: abs(l.price - price))   # gần giá nhất xếp trước
    return out


def build_storyline(tf_data, current_price):
    """
    tf_data: {'D1': df, 'H4': df, 'H1': df, ...} — mỗi df có cột open/high/low/close.
    Trả về Storyline với bias từng khung + hướng tổng hợp + roadblocks.
    """
    contexts = {}

    for tf, df in tf_data.items():
        if df is None or len(df) < (2 * STORYLINE_SWING_LB + 5):
            continue
        closes = df["close"].values
        highs, lows = _swings(closes, STORYLINE_SWING_LB)
        bias, bos = _bias_from_swings(highs, lows, closes[-1])

        det = MSNRDetector(df)
        det.detect_all()

        contexts[tf] = TFContext(tf=tf, bias=bias, bos=bos,
                                 swing_highs=highs, swing_lows=lows,
                                 levels=det.levels)

    # Hướng tổng hợp: theo thứ tự ưu tiên (mặc định D1 → H4), khung đầu tiên
    # KHÔNG neutral sẽ quyết định storyline + làm khung neo (origin).
    direction, origin = "NEUTRAL", None
    for tf in STORYLINE_PRIORITY:
        c = contexts.get(tf)
        if c and c.bias != "NEUTRAL":
            direction, origin = c.bias, tf
            break

    # Roadblock = SnR ở khung kế dưới của origin
    roadblocks = []
    if origin:
        c = contexts.get(_lower_tf(origin))
        if c:
            roadblocks = _filter_roadblocks(c.levels, direction, current_price)

    return Storyline(contexts=contexts, direction=direction,
                     origin_tf=origin, roadblocks=roadblocks)
