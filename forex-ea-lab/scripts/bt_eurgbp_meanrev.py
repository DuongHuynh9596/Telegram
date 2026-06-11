"""EURGBP H1 mean-reversion backtest (2012-2022), cost-aware.

Rules (chosen a priori, NOT optimized):
- Setup: previous bar closed BELOW lower Bollinger(20,2) and RSI(14) < 35
  (mirror for shorts above upper band, RSI > 65).
- Trigger: current bar closes back INSIDE the band.
- Regime filter: ADX(14) < 25 (no trend) ; trade only 07:00-20:00 server.
- Entry next bar open. SL = entry -/+ 1.5*ATR(14). Exit: close crosses
  middle band, or SL, or time-stop 36 bars.
- Costs: 1.5 pip spread + 0.2 pip slippage per round turn.
- PnL converted to USD at flat GBPUSD=1.25 (contract=125000).
"""
import numpy as np
import pandas as pd
from btcommon import simulate, metrics, yearly_table

SPREAD, SLIP = 0.00015, 0.00002
COST = SPREAD + SLIP
RSI_LO, RSI_HI, ADX_MAX = 35, 65, 25
ATR_MULT, TIME_STOP = 1.5, 36
H0, H1 = 7, 20


def wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def indicators(df):
    c, h, l = df.close, df.high, df.low
    df["ma"] = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    df["bb_lo"], df["bb_hi"] = df.ma - 2 * sd, df.ma + 2 * sd
    delta = c.diff()
    rs = wilder(delta.clip(lower=0), 14) / wilder(-delta.clip(upper=0), 14)
    df["rsi"] = 100 - 100 / (1 + rs)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = wilder(tr, 14)
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = df.atr
    pdi = 100 * wilder(pd.Series(plus, index=df.index), 14) / atr
    mdi = 100 * wilder(pd.Series(minus, index=df.index), 14) / atr
    df["adx"] = wilder(100 * (pdi - mdi).abs() / (pdi + mdi), 14)
    return df


def run(df, rsi_lo=RSI_LO, rsi_hi=RSI_HI, min_target_mult=0.0):
    o = df.open.to_numpy(); h = df.high.to_numpy(); l = df.low.to_numpy()
    c = df.close.to_numpy(); t = df.Date.to_numpy(); hr = df.Date.dt.hour.to_numpy()
    ma = df.ma.to_numpy(); blo = df.bb_lo.to_numpy(); bhi = df.bb_hi.to_numpy()
    rsi = df.rsi.to_numpy(); atr = df.atr.to_numpy(); adx = df.adx.to_numpy()
    trades, pos = [], 0
    i = 50
    while i < len(df) - 1:
        if pos == 0:
            sig = 0
            if (H0 <= hr[i] <= H1) and adx[i] < ADX_MAX and not np.isnan(ma[i]):
                if c[i - 1] < blo[i - 1] and rsi[i - 1] < rsi_lo and c[i] > blo[i]:
                    sig = 1
                elif c[i - 1] > bhi[i - 1] and rsi[i - 1] > rsi_hi and c[i] < bhi[i]:
                    sig = -1
            if sig and abs(ma[i] - c[i]) < min_target_mult * COST:
                sig = 0          # potential reward too small vs costs
            if sig:
                pos = sig
                entry = o[i + 1] + (COST if sig == 1 else 0.0)
                sl_d = ATR_MULT * atr[i]
                sl = entry - sig * sl_d
                t_in, bars_held = t[i + 1], 0
            i += 1
            continue
        # manage position on bar i
        bars_held += 1
        exit_p = None
        if pos == 1:
            if l[i] <= sl:
                exit_p = sl - SLIP
            elif c[i] >= ma[i]:
                exit_p = c[i]
        else:
            if h[i] + SPREAD >= sl:
                exit_p = sl + SLIP
            elif c[i] <= ma[i]:
                exit_p = c[i] + SPREAD
        if exit_p is None and bars_held >= TIME_STOP:
            exit_p = c[i] + (SPREAD if pos == -1 else 0.0)
        if exit_p is not None:
            trades.append((t_in, t[i], pos, entry, exit_p, sl_d))
            pos = 0
        i += 1
    return pd.DataFrame(trades, columns=["entry_time", "exit_time", "dir",
                                         "entry", "exit", "sl_dist"])


def main():
    df = pd.read_csv("data/EURGBPh1.csv.gz", parse_dates=["Date"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col] * 1e-5
    df = df.sort_values("Date").reset_index(drop=True)
    df = indicators(df)
    variants = [
        ("V0 base 35/65", dict()),
        ("V1 minTarget6x", dict(min_target_mult=6)),
        ("V2 rsi30/70", dict(rsi_lo=30, rsi_hi=70)),
        ("V3 both", dict(rsi_lo=30, rsi_hi=70, min_target_mult=6)),
    ]
    rows = []
    for label, kw in variants:
        tr = run(df, **kw)
        sim, ec = simulate(tr, contract=125_000)
        rows.append(metrics(sim, ec, label=label))
        if label == "V3 both":
            print(f"### {label} yearly"); print(yearly_table(sim).to_string()); print()
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
