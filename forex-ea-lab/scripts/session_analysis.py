"""Session behavior analysis for XAUUSD M15 data.

Server time is MT-standard GMT+2/+3 (tracks US DST): gold opens Mon 01:00,
closes Fri ~23:45. Sessions in server time:
  Asia   01:00-10:00, London 10:00-18:00, NewYork 15:00-23:00

For each session-day we measure:
  range       = max(high)-min(low)            (volatility)
  net         = |close_last - open_first|      (directional move)
  efficiency  = net / range                    (1.0 = pure trend, ~0 = chop)
Yearly medians answer: which session moves most, and which session TRENDS most.
"""
import pandas as pd
import numpy as np

SESSIONS = {"Asia": (1, 10), "London": (10, 18), "NewYork": (15, 23)}

def load():
    df = pd.read_csv("data/XAU_15m_data.csv.gz", sep=";",
                     parse_dates=["Date"], date_format="%Y.%m.%d %H:%M")
    return df.sort_values("Date").reset_index(drop=True)

def main():
    df = load()
    df["day"] = df["Date"].dt.date
    df["hour"] = df["Date"].dt.hour
    df["year"] = df["Date"].dt.year

    rows = []
    for name, (h0, h1) in SESSIONS.items():
        s = df[(df["hour"] >= h0) & (df["hour"] < h1)]
        g = s.groupby("day").agg(o=("Open", "first"), c=("Close", "last"),
                                 hi=("High", "max"), lo=("Low", "min"),
                                 year=("year", "first"), n=("Close", "size"))
        g = g[g["n"] >= (h1 - h0) * 4 * 0.7]          # skip truncated days
        g["range"] = g["hi"] - g["lo"]
        g["net"] = (g["c"] - g["o"]).abs()
        g["eff"] = g["net"] / g["range"].replace(0, np.nan)
        y = g.groupby("year").agg(range_med=("range", "median"),
                                  net_med=("net", "median"),
                                  eff_med=("eff", "median"))
        y["session"] = name
        rows.append(y.reset_index())

    out = pd.concat(rows)
    for metric, title in [("range_med", "Median session RANGE ($)"),
                          ("net_med", "Median session NET directional move ($)"),
                          ("eff_med", "Median EFFICIENCY net/range (trendiness)")]:
        piv = out.pivot(index="year", columns="session", values=metric).round(2)
        piv["strongest"] = piv[["Asia", "London", "NewYork"]].idxmax(axis=1)
        print(f"\n=== {title} ===")
        print(piv.to_string())

if __name__ == "__main__":
    main()
