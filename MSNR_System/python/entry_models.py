# MSNR System - Entry Models (Quasimodo + 411 Setup)
#
# QM (Quasimodo / Over-Under): biến thể Vai-Đầu-Vai.
#   - Bullish QM (BUY):  L1 → H1 → L2(đáy mới thấp hơn = HEAD/apex) → phá H1 (BOS lên)
#                        → hồi về quanh L1 (vai phải) → vào BUY. SL dưới apex.
#   - Bearish QM (SELL): H1 → L1 → H2(đỉnh mới cao hơn = HEAD/apex) → phá L1 (BOS xuống)
#                        → hồi về quanh H1 (vai phải) → vào SELL. SL trên apex.
#   QM KHÔNG cần xét fresh/unfresh (theo MSNR).
#
# 411: cấu trúc 3 level so le R-S-R (đảo tại R thứ 3 → SELL) hoặc S-R-S (→ BUY).
from dataclasses import dataclass, field


@dataclass
class QMSetup:
    direction: str        # 'BUY' / 'SELL'
    entry: float          # giá vai phải ≈ level vai trái (điểm vào / limit)
    apex: float           # đỉnh/đáy HEAD — dùng đặt SL chuẩn MSNR
    head_idx: int

    def __repr__(self):
        return f"QM[{self.direction}] entry={self.entry:.2f} apex={self.apex:.2f}"


@dataclass
class Setup411:
    pattern: str          # 'RSR' (→SELL) / 'SRS' (→BUY)
    levels: list = field(default_factory=list)   # 3 SnRLevel so le

    @property
    def action(self):
        return "SELL" if self.pattern == "RSR" else "BUY"

    def matches(self, action):
        return self.action == action

    def __repr__(self):
        return f"411[{self.pattern}->{self.action}]"


def detect_qm(df, highs, lows, current_price, tol):
    """
    highs/lows: list (bar_index, price) swing thuần (từ detector.swings()).
    Trả về các QMSetup mà giá HIỆN TẠI đang hồi về quanh vai phải (trong tol).
    """
    closes = df["close"].values
    setups = []

    # ── Bullish QM (BUY) ────────────────────────────────────────────────
    for L1 in lows:
        # high đầu tiên sau L1
        hs = [h for h in highs if h[0] > L1[0]]
        if not hs:
            continue
        H1 = hs[0]
        # đáy mới THẤP HƠN L1 sau H1 = HEAD (apex)
        l2s = [l for l in lows if l[0] > H1[0] and l[1] < L1[1]]
        if not l2s:
            continue
        L2 = l2s[0]
        # BOS lên: có close sau HEAD vượt H1
        after = closes[L2[0] + 1:]
        if len(after) == 0 or after.max() <= H1[1]:
            continue
        # giá hiện tại hồi về quanh L1 (vai phải)
        if abs(current_price - L1[1]) <= tol:
            setups.append(QMSetup("BUY", round(L1[1], 2), round(L2[1], 2), L2[0]))

    # ── Bearish QM (SELL) ───────────────────────────────────────────────
    for H1 in highs:
        ls = [l for l in lows if l[0] > H1[0]]
        if not ls:
            continue
        L1 = ls[0]
        h2s = [h for h in highs if h[0] > L1[0] and h[1] > H1[1]]
        if not h2s:
            continue
        H2 = h2s[0]   # HEAD (apex)
        after = closes[H2[0] + 1:]
        if len(after) == 0 or after.min() >= L1[1]:
            continue
        if abs(current_price - H1[1]) <= tol:
            setups.append(QMSetup("SELL", round(H1[1], 2), round(H2[1], 2), H2[0]))

    # Gần giá nhất xếp trước
    setups.sort(key=lambda q: abs(q.entry - current_price))
    return setups


def detect_411(levels, current_price, tol):
    """
    Tìm 411 gần nhất: 3 level A/V so le cuối cùng, level thứ 3 nằm sát giá.
    AVA → RSR (đảo tại R3 = SELL) ; VAV → SRS (đảo tại S3 = BUY).
    """
    seq = [l for l in sorted(levels, key=lambda l: l.bar_index)
           if l.level_type in ("A", "V")]
    if len(seq) < 3:
        return None
    last3 = seq[-3:]
    types = "".join(l.level_type for l in last3)
    third = last3[-1]
    if abs(third.price - current_price) > tol:
        return None
    if types == "AVA":
        return Setup411("RSR", last3)
    if types == "VAV":
        return Setup411("SRS", last3)
    return None
