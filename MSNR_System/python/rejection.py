# MSNR System - Rejection Candle Detector (nến từ chối tại level)
#
# Rejection = cây nến có RÂU dài đâm vào level (quét thanh khoản) rồi THÂN đóng
# bật ra → xác nhận "tay to" từ chối giá ở đó. Đây là tín hiệu CONFIRM.
#   - BULL rejection (tại Support → BUY):  low đâm xuống level, close đóng lại TRÊN level,
#                                          râu dưới dài.
#   - BEAR rejection (tại Resistance → SELL): high đâm lên level, close đóng lại DƯỚI level,
#                                             râu trên dài.
# Xét trên cây nến ĐÃ ĐÓNG gần nhất (index -2; -1 là nến đang hình thành).
from dataclasses import dataclass
from config import REJ_WICK_RATIO, REJ_BODY_MAX_RATIO, REJ_TOL


@dataclass
class Rejection:
    direction: str        # 'BUY' (bull rejection) / 'SELL' (bear rejection)
    bar_index: int
    wick_ratio: float
    level_price: float

    def __repr__(self):
        return (f"Rejection[{self.direction}] @level {self.level_price:.2f} "
                f"wick={self.wick_ratio:.0%}")


def _closed_bar(df):
    """Cây nến đã đóng gần nhất (bỏ nến đang hình thành ở cuối)."""
    if len(df) < 2:
        return None, None
    return df.iloc[-2], len(df) - 2


def detect_rejection(df, level_price, action,
                     wick_ratio=REJ_WICK_RATIO,
                     body_max=REJ_BODY_MAX_RATIO,
                     tol=REJ_TOL):
    """
    Trả về Rejection nếu cây nến đã đóng gần nhất từ chối `level_price` theo
    đúng `action` ('BUY'/'SELL'); ngược lại None.
    """
    bar, idx = _closed_bar(df)
    if bar is None:
        return None

    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    rng  = h - l
    if rng <= 0:
        return None
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if action == "BUY":
        # Râu dưới đâm vào/xuyên level, thân đóng lại TRÊN level
        wick_touched = (l <= level_price + tol)
        closed_above = (c > level_price)
        long_wick    = (lower_wick >= wick_ratio * rng)
        small_body   = (body <= body_max * rng)
        if wick_touched and closed_above and long_wick and small_body:
            return Rejection("BUY", idx, lower_wick / rng, level_price)

    elif action == "SELL":
        # Râu trên đâm vào/xuyên level, thân đóng lại DƯỚI level
        wick_touched = (h >= level_price - tol)
        closed_below = (c < level_price)
        long_wick    = (upper_wick >= wick_ratio * rng)
        small_body   = (body <= body_max * rng)
        if wick_touched and closed_below and long_wick and small_body:
            return Rejection("SELL", idx, upper_wick / rng, level_price)

    return None
