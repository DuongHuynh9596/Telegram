# MSNR System - Core Detector (A/V Levels + Gap SnR + Fresh/Unfresh + MISS)
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Literal, Optional
from config import (PEAK_LOOKBACK, MIN_LEVEL_GAP,
                    USE_MISS, MISS_LOOKAHEAD, MISS_TOL, MISS_MIN_MOVE)


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
    original_type: Optional[str] = None   # type lúc tạo (truy vết role-reversal)
    is_miss: bool = False          # MISS = giá bỏ chạy, wick sau KHÔNG chạm lại → rất khỏe

    @property
    def role_reversed(self) -> bool:
        """POI đổi vai: level đã bị body xuyên qua và đổi A↔V / GAP_R↔GAP_S."""
        return self.original_type is not None and self.level_type != self.original_type

    def __repr__(self):
        tag = []
        if self.is_miss:       tag.append("MISS")
        if self.role_reversed: tag.append("FLIP")
        suffix = (" " + "+".join(tag)) if tag else ""
        return f"[{self.level_type}|{self.state}] {self.price:.2f} (bar {self.bar_index}){suffix}"


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
        # Ghi lại type gốc TRƯỚC khi fresh/unfresh có thể flip → truy vết role-reversal
        for lvl in self.levels:
            lvl.original_type = lvl.level_type
        self._update_fresh_unfresh()
        if USE_MISS:
            self._detect_miss()
        return self.levels

    def swings(self) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """
        Trả về (swing_highs, swing_lows) thuần trên CLOSE price — KHÔNG bị
        mutate bởi fresh/unfresh flip. Dùng cho QM / 411 / storyline.
        Mỗi phần tử: (bar_index, price).
        """
        closes = self.df["close"].values
        lb = self.lookback
        highs, lows = [], []
        for i in range(lb, len(closes) - lb):
            seg = closes[i - lb: i + lb + 1]
            if closes[i] == seg.max():
                highs.append((i, float(closes[i])))
            elif closes[i] == seg.min():
                lows.append((i, float(closes[i])))
        return highs, lows

    def get_miss_levels(self) -> list[SnRLevel]:
        return [l for l in self.levels if l.is_miss]

    def get_reversed_levels(self) -> list[SnRLevel]:
        """POI đổi vai (SBR/RBS) — vẫn dùng được làm vùng quan tâm."""
        return [l for l in self.levels if l.role_reversed]

    def get_fresh_levels(self) -> list[SnRLevel]:
        return [l for l in self.levels if l.state == "FRESH"]

    def get_valid_levels(self, max_touches: int = 2) -> list[SnRLevel]:
        """FRESH + UNFRESH cham it (<= max_touches) — van la level giao dich duoc"""
        return [l for l in self.levels
                if l.state == "FRESH" or l.touch_count <= max_touches]

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

                # Wick chạm level
                wick_touched = (wick_low <= price <= wick_high)

                # Body đóng xuyên qua: level phải nằm GIỮA open và close.
                # Nến nằm hẳn 1 phía của level KHÔNG tính là xuyên qua
                # (bug cũ khiến mọi level flip liên tục và luôn FRESH)
                body_closed_through = (body_bottom <= price <= body_top)

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

    # ─────────────────────────────────────────────────────────────────────────
    # MISS DETECTION
    # MISS = sau khi SnR hình thành, giá đi ra xa và trong MISS_LOOKAHEAD nến
    # tiếp theo KHÔNG có wick nào chạm lại level (cách > MISS_TOL) → level rất khỏe.
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_miss(self):
        highs  = self.df["high"].values
        lows   = self.df["low"].values
        closes = self.df["close"].values
        n      = len(self.df)

        for lvl in self.levels:
            start = lvl.bar_index + 1
            end   = min(n, start + MISS_LOOKAHEAD)
            if start >= end:
                continue

            # Khoảng cách gần nhất mà 1 nến tiến tới level (0 nếu wick bao trùm level)
            def bar_dist(j):
                if lows[j] <= lvl.price <= highs[j]:
                    return 0.0
                return min(abs(lows[j] - lvl.price), abs(highs[j] - lvl.price))

            approach = min(bar_dist(j) for j in range(start, end))
            moved    = max(abs(closes[j] - lvl.price) for j in range(start, end))

            # Không nến nào chạm lại (approach > tol) VÀ giá thực sự bỏ chạy
            if approach > MISS_TOL and moved > MISS_MIN_MOVE:
                lvl.is_miss = True
