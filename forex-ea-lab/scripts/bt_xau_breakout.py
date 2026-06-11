"""XAUUSD M15 session-breakout backtest with realistic costs.

Server time = MT standard (GMT+2/+3 tracking US DST).
Three session configs (box hours -> trade window):
  LondonBO : box 01-08 (Asia)        -> trade 08-14
  NYBO     : box 10-15 (London)      -> trade 15-21
  AsiaBO   : box 18-23 (prev late NY)-> trade 01-08 (Asia)

Rules (identical for all configs, parameters chosen a priori, NOT optimized):
- Box = high/low of box hours. Skip day if box < MIN_BOX (costs would
  dominate) or box > MAX_BOX_PCT of price (news blowout).
- First M15 bar in the window crossing box edge + BUF enters with a stop
  order (OCO: opposite side cancelled). Max 1 trade/day.
- SL = opposite box edge. TP = 2R. Force-close at 23:00.
- Costs: spread $0.28 (user's broker, 28 points) + $0.07 slippage.
"""
import numpy as np
import pandas as pd
from btcommon import simulate, metrics, yearly_table

SPREAD, SLIP = 0.28, 0.07
COST = SPREAD + SLIP
MIN_BOX = 3.5          # $ — keeps round-turn cost < ~10% of 1R
MAX_BOX_PCT = 1.5      # % of price — skip blowout days
BUF = 0.10             # breakout buffer $
RR = 2.0               # take-profit in R multiples
EOD_HOUR = 23

CONFIGS = {
    "LondonBO(boxAsia)":  {"box": (1, 8),   "win": (8, 14),  "prev_day_box": False},
    "NYBO(boxLondon)":    {"box": (10, 15), "win": (15, 21), "prev_day_box": False},
    "AsiaBO(boxLateNY)":  {"box": (18, 23), "win": (1, 8),   "prev_day_box": True},
}


def load():
    df = pd.read_csv("data/XAU_15m_data.csv.gz", sep=";",
                     parse_dates=["Date"], date_format="%Y.%m.%d %H:%M")
    df = df.sort_values("Date").reset_index(drop=True)
    df["day"] = df["Date"].dt.normalize()
    df["hour"] = df["Date"].dt.hour
    return df


def daily_trend(df, period=50):
    """+1/-1 per day from prior day close vs SMA(period) of daily closes."""
    d1 = df.groupby("day")["Close"].last()
    sma = d1.rolling(period).mean()
    tr = np.where(d1 > sma, 1, -1)
    return pd.Series(tr, index=d1.index).shift(1)   # known at day open


def run_config(df, name, cfg, trend=None):
    b0, b1 = cfg["box"]
    w0, w1 = cfg["win"]
    box_df = df[(df.hour >= b0) & (df.hour < b1)]
    boxes = box_df.groupby("day").agg(hi=("High", "max"), lo=("Low", "min"),
                                      n=("Close", "size"))
    boxes = boxes[boxes.n >= (b1 - b0) * 4 * 0.7]
    if cfg["prev_day_box"]:
        # box from previous trading day applies to today's window
        boxes = boxes.shift(1).dropna()
        # shift(1) moves values one row down the day index; rows are trading
        # days only, so "previous row" = previous trading day
    trades = []
    win_df = df[(df.hour >= w0) & (df.hour <= EOD_HOUR)]
    for day, bars in win_df.groupby("day"):
        if day not in boxes.index:
            continue
        hi, lo = boxes.at[day, "hi"], boxes.at[day, "lo"]
        box = hi - lo
        if box < MIN_BOX or box > bars.Close.iloc[0] * MAX_BOX_PCT / 100:
            continue
        allow = 0 if trend is None else trend.get(day, 0)
        if trend is not None and allow not in (1, -1):
            continue
        arr = bars[["High", "Low", "Close", "hour"]].to_numpy()
        times = bars["Date"].to_numpy()
        pos = 0
        for i in range(len(arr)):
            h, l, c, hr = arr[i]
            if pos == 0:
                if hr >= w1:
                    break
                long_ok = trend is None or allow == 1
                short_ok = trend is None or allow == -1
                if long_ok and h >= hi + BUF:         # long stop fill (ask)
                    pos, entry = 1, hi + BUF + COST
                    sl, t_in = lo, times[i]
                    tp = entry + RR * (entry - sl)
                elif short_ok and l <= lo - BUF:      # short stop fill (bid)
                    pos, entry = -1, lo - BUF - SLIP
                    sl, t_in = hi, times[i]
                    tp = entry - RR * (sl - entry)
                else:
                    continue
            # manage open position (same-bar check is conservative: SL first)
            if pos == 1:
                if l <= sl:
                    trades.append((t_in, times[i], 1, entry, sl - SLIP, entry - sl)); pos = 2; break
                if h >= tp + SPREAD:
                    trades.append((t_in, times[i], 1, entry, tp, entry - sl)); pos = 2; break
            elif pos == -1:
                if h >= sl + SPREAD:
                    trades.append((t_in, times[i], -1, entry, sl + SPREAD + SLIP, sl - entry)); pos = 2; break
                if l <= tp:
                    trades.append((t_in, times[i], -1, entry, tp, sl - entry)); pos = 2; break
        if pos in (1, -1):                            # EOD close at last bar
            last_c, last_t = arr[-1][2], times[-1]
            exit_p = last_c if pos == 1 else last_c + SPREAD
            sl_d = (entry - sl) if pos == 1 else (sl - entry)
            trades.append((t_in, last_t, pos, entry, exit_p, sl_d))
    return pd.DataFrame(trades, columns=["entry_time", "exit_time", "dir",
                                         "entry", "exit", "sl_dist"])


def main():
    df = load()
    print(f"bars={len(df)}  {df.Date.min()} -> {df.Date.max()}\n")
    trend = daily_trend(df)
    summary = []
    for name, cfg in CONFIGS.items():
        for tf, tlab in [(None, ""), (trend, "+D1trend")]:
            tr = run_config(df, name, cfg, trend=tf)
            sim, ec = simulate(tr)
            summary.append(metrics(sim, ec, label=name + tlab))
            if tlab:
                print(f"### {name}{tlab}")
                print(yearly_table(sim).to_string(), "\n")
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
