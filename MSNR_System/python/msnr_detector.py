# MSNR System - Core Detector (A/V Levels + Gap SnR + Fresh/Unfresh)
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Literal
from config import PEAK_LOOKBACK, MIN_LEVEL_GAP


LevelType  = Literal["A", "V", "GAP_R", "GAP_S"]
LevelState = Literal["FRESH", "UNFRESH"]


@dataclass
class SnRLevel:
    price: float
    level_type: LevelType          # A=Resistance, V=Support, GAP_R/GAP_S=Gap
    bar_index: int
    state: LevelState = "FRESH"
    touch_count: int = 0
    flipped: bool = False          # True nếu đây là Flipped SnR (SBR/RBS)

    def __repr__(self):
        return f"[{self.level_type}|{self.state}] {self.price:.2f} (bar {self.bar_index})"


class MSNRDetector:
    """
    Phát hiện toàn bộ Key Levels theo phương pháp Malaysian SnR.
    Hoạt động trên CLOSE PRICE (Line Chart logic).
    """

    def __init__(self, df: pd.DataFrame, lookback: int = PEAK_LOOKBACK):
        """
        df cần có columns: open, high, low, close, time
        """
        self.df = df.reset_index(drop=True)
        self.lookback = lookback
        self.levels: list[SnRLevel] = []

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC
    # ─────────────────────────────────────────────────────────────────────────

    def detect_all(self) -> list[SnRLevel]:
        self.levels = []
        self._detect_a_v_levels()
        self._detect_gap_levels()
        self._merge_nearby_levels()
        self._update_fresh_unfresh()
        return self.levels

    def get_fresh_levels(self) -> list[SnRLevel]:
        return [l for l in self.levels if l.state == "FRESH"]

    def get_levels_near(self, price: float, tolerance: float = 1.0) -> list[SnRLevel]:
        return [l for l in self.levels if abs(l.price - price) <= tolerance]

    # ─────────────────────────────────────────────────────────────────────────
    # A / V LEVEL DETECTION (Local Max/Min trên Close Price)
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_a_v_levels(self):
        closes = self.df["close"].values
        lb = self.lookback

        for i in range(lb, len(closes) - lb):
            window_before = closes[i - lb: i]
            window_after  = closes[i + 1: i + lb + 1]

            # A-Level: đỉnh — close[i] cao nhất trong window
            if closes[i] > window_before.max() and closes[i] > window_after.max():
                self.levels.append(SnRLevel(
                    price=closes[i],
                    level_type="A",
                    bar_index=i,
                ))

            # V-Level: đáy — close[i] thấp nhất trong window
            elif closes[i] < window_before.min() and closes[i] < window_after.min():
                self.levels.append(SnRLevel(
                    price=closes[i],
                    level_type="V",
                    bar_index=i,
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # GAP SnR DETECTION (Close/Open gap giữa 2 nến cùng màu)
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_gap_levels(self):
        df = self.df
        for i in range(len(df) - 1):
            c1 = df.iloc[i]
            c2 = df.iloc[i + 1]

            c1_bull = c1["close"] > c1["open"]
            c2_bull = c2["close"] > c2["open"]

            # Chỉ xét khi 2 nến cùng màu (cùng chiều momentum)
            if c1_bull != c2_bull:
                continue

            gap_size = abs(c2["open"] - c1["close"])
            if gap_size < 0.05:   # bỏ qua gap quá nhỏ (noise)
                continue

            # Gap Resistance: giá nhảy lên (2 nến tăng), gap tạo kháng cự bên trên
            # Gap Support:    giá nhảy xuống (2 nến giảm), gap tạo hỗ trợ bên dưới
            if c1_bull:
                self.levels.append(SnRLevel(
                    price=c1["close"],
                    level_type="GAP_R",
                    bar_index=i,
                ))
            else:
                self.levels.append(SnRLevel(
                    price=c1["close"],
                    level_type="GAP_S",
                    bar_index=i,
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # MERGE NEARBY LEVELS (tránh cluster dày đặc)
    # ─────────────────────────────────────────────────────────────────────────

    def _merge_nearby_levels(self):
        if not self.levels:
            return

        self.levels.sort(key=lambda l: l.price)
        merged = [self.levels[0]]

        for lvl in self.levels[1:]:
            if abs(lvl.price - merged[-1].price) < MIN_LEVEL_GAP:
                # Giữ level gần hiện tại nhất (bar_index lớn hơn)
                if lvl.bar_index > merged[-1].bar_index:
                    merged[-1] = lvl
            else:
                merged.append(lvl)

        self.levels = merged

    # ─────────────────────────────────────────────────────────────────────────
    # FRESH / UNFRESH STATE UPDATE
    # Logic:
    #   FRESH  → wick chạm level            → UNFRESH
    #   UNFRESH → body close xuyên qua level → FRESH (flipped role)
    #   FRESH (sau flip) → wick chạm lại    → UNFRESH
    # ─────────────────────────────────────────────────────────────────────────

    def _update_fresh_unfresh(self):
        df = self.df

        for lvl in self.levels:
            # Chỉ xét các nến SAU khi level được tạo ra
            future_bars = df[df.index > lvl.bar_index]

            for _, bar in future_bars.iterrows():
                body_top    = max(bar["open"], bar["close"])
                body_bottom = min(bar["open"], bar["close"])
                wick_high   = bar["high"]
                wick_low    = bar["low"]

                price = lvl.price

                # Wick chạm level (nhưng body không xuyên qua)
                wick_touched = (wick_low <= price <= wick_high)
                body_closed_through = (body_bottom <= price <= body_top) or \
                                      (body_top < price and bar["close"] < price) or \
                                      (body_bottom > price and bar["close"] > price)

                if body_closed_through:
                    # Body đóng xuyên qua → FLIP → trở về FRESH với vai trò mới
                    lvl.state   = "FRESH"
                    lvl.flipped = True
                    # Đổi vai trò: A ↔ V, GAP_R ↔ GAP_S
                    lvl.level_type = {
                        "A": "V", "V": "A",
                        "GAP_R": "GAP_S", "GAP_S": "GAP_R"
                    }.get(lvl.level_type, lvl.level_type)

                elif wick_touched and lvl.state == "FRESH":
                    lvl.state = "UNFRESH"
                    lvl.touch_count += 1

                elif wick_touched and lvl.state == "UNFRESH":
                    lvl.touch_count += 1
