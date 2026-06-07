# MSNR System - Trendline Engine (3-Point Rule)
import numpy as np
from dataclasses import dataclass
from typing import Optional
from msnr_detector import SnRLevel
from config import TRENDLINE_TOUCH_TOLERANCE


@dataclass
class Trendline:
    p1: SnRLevel
    p2: SnRLevel
    direction: str          # "UP" (nối V-V) hoặc "DOWN" (nối A-A)
    slope: float
    intercept: float
    valid: bool = True      # False nếu có nến đóng cửa xuyên qua giữa P1-P2
    p3_touched: bool = False
    p3_bar_index: Optional[int] = None
    p3_price: Optional[float] = None

    def price_at(self, bar_index: int) -> float:
        return self.slope * bar_index + self.intercept

    def __repr__(self):
        return (f"Trendline[{self.direction}] "
                f"P1={self.p1.price:.2f}@{self.p1.bar_index} "
                f"P2={self.p2.price:.2f}@{self.p2.bar_index} "
                f"valid={self.valid} p3={self.p3_touched}")


class TrendlineEngine:
    """
    Phát hiện và validate Trendline theo quy tắc MSNR 3-Point Rule.

    Quy tắc:
    - Nối ít nhất 2 đỉnh A (Down trendline / resistance)
      hoặc 2 đáy V (Up trendline / support)
    - Không có nến nào ĐÓNG CỬA xuyên qua trendline giữa P1 và P2
    - P3: wick chạm trendline, body đứng phía trong → Entry signal
    - Body đóng cửa xuyên qua P3 → Trendline INVALIDATED
    """

    def __init__(self, df, levels: list[SnRLevel]):
        self.df     = df.reset_index(drop=True)
        self.levels = levels

    def detect(self) -> list[Trendline]:
        trendlines = []

        a_levels = [l for l in self.levels if l.level_type == "A"]
        v_levels = [l for l in self.levels if l.level_type == "V"]

        trendlines += self._build_trendlines(a_levels, "DOWN")
        trendlines += self._build_trendlines(v_levels, "UP")

        return [t for t in trendlines if t.valid]

    # ─────────────────────────────────────────────────────────────────────────

    def _build_trendlines(self, levels: list[SnRLevel], direction: str) -> list[Trendline]:
        results = []
        levels_sorted = sorted(levels, key=lambda l: l.bar_index)

        for i in range(len(levels_sorted) - 1):
            p1 = levels_sorted[i]
            p2 = levels_sorted[i + 1]

            slope, intercept = self._line_params(p1, p2)
            tl = Trendline(p1=p1, p2=p2, direction=direction,
                           slope=slope, intercept=intercept)

            # Validate: không có nến đóng cửa xuyên qua giữa P1-P2
            tl.valid = self._validate_no_close_through(tl)
            if not tl.valid:
                continue

            # Tìm P3: wick chạm trendline sau P2
            self._find_p3(tl)

            results.append(tl)

        return results

    def _line_params(self, p1: SnRLevel, p2: SnRLevel):
        x1, y1 = p1.bar_index, p1.price
        x2, y2 = p2.bar_index, p2.price
        slope     = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
        intercept = y1 - slope * x1
        return slope, intercept

    def _validate_no_close_through(self, tl: Trendline) -> bool:
        """
        Kiểm tra: giữa P1 và P2, không nến nào ĐÓNG CỬA sai phía.
        DOWN trendline: không nến nào close > trendline price
        UP   trendline: không nến nào close < trendline price
        """
        df = self.df
        mask = (df.index > tl.p1.bar_index) & (df.index < tl.p2.bar_index)
        bars_between = df[mask]

        for idx, bar in bars_between.iterrows():
            tl_price = tl.price_at(idx)
            if tl.direction == "DOWN" and bar["close"] > tl_price:
                return False
            if tl.direction == "UP"   and bar["close"] < tl_price:
                return False
        return True

    def _find_p3(self, tl: Trendline):
        """
        Tìm P3: nến đầu tiên sau P2 mà:
        - Wick chạm trendline (trong tolerance)
        - Body đứng phía trong (chưa đóng cửa xuyên qua)
        """
        df    = self.df
        tol   = TRENDLINE_TOUCH_TOLERANCE
        after = df[df.index > tl.p2.bar_index]

        for idx, bar in after.iterrows():
            tl_price    = tl.price_at(idx)
            wick_low    = bar["low"]
            wick_high   = bar["high"]
            body_top    = max(bar["open"], bar["close"])
            body_bottom = min(bar["open"], bar["close"])

            wick_touched = (wick_low - tol <= tl_price <= wick_high + tol)

            if tl.direction == "DOWN":
                # Resistance trendline: wick chạm từ bên dưới, body < tl_price
                body_inside = body_top <= tl_price + tol
            else:
                # Support trendline: wick chạm từ bên trên, body > tl_price
                body_inside = body_bottom >= tl_price - tol

            if wick_touched and body_inside:
                tl.p3_touched    = True
                tl.p3_bar_index  = idx
                tl.p3_price      = tl_price
                break

            # Nếu body đóng cửa xuyên qua → invalidate, dừng tìm P3
            if tl.direction == "DOWN" and bar["close"] > tl_price + tol:
                tl.valid = False
                break
            if tl.direction == "UP"   and bar["close"] < tl_price - tol:
                tl.valid = False
                break

    def get_active_p3_signals(self, trendlines: list[Trendline]) -> list[Trendline]:
        """Trả về trendlines có P3 và còn valid — đây là entry signals."""
        return [t for t in trendlines if t.valid and t.p3_touched]
