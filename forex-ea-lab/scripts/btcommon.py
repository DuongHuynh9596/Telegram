"""Shared backtest utilities: cost-aware trade simulation and reporting.

Conventions:
- All prices are bid. Buys fill at price+spread, sells at price.
- Each trade risks `risk_pct` of current equity; lot size derived from
  SL distance (continuous lots, no broker min-lot rounding).
- Equity is compounded trade by trade (no overlapping positions per system).
"""
import numpy as np
import pandas as pd


def simulate(trades, start_equity=20_000, risk_pct=1.0, contract=100):
    """trades: DataFrame with entry_time, exit_time, dir(+1/-1), entry, exit, sl_dist.
    Returns (trades_with_pnl, equity_curve_series)."""
    eq = start_equity
    rows, curve = [], []
    for t in trades.itertuples():
        risk_usd = eq * risk_pct / 100.0
        lots = risk_usd / (t.sl_dist * contract)
        pnl = (t.exit - t.entry) * t.dir * contract * lots
        eq += pnl
        rows.append({**t._asdict(), "lots": lots, "pnl": pnl, "equity": eq})
        curve.append((t.exit_time, eq))
        if eq <= 0:
            break
    out = pd.DataFrame(rows)
    ec = pd.Series([c[1] for c in curve], index=[c[0] for c in curve])
    return out, ec


def metrics(tr, ec, start_equity=20_000, label=""):
    if len(tr) == 0:
        return {"label": label, "trades": 0}
    wins = tr[tr.pnl > 0]
    gross_w = wins.pnl.sum()
    gross_l = -tr[tr.pnl <= 0].pnl.sum()
    peak = ec.cummax()
    dd = ((ec - peak) / peak).min() * 100
    years = (ec.index[-1] - ec.index[0]).days / 365.25
    cagr = ((ec.iloc[-1] / start_equity) ** (1 / max(years, 1e-9)) - 1) * 100
    return {
        "label": label,
        "trades": len(tr),
        "win_rate_%": round(100 * len(wins) / len(tr), 1),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else np.inf,
        "final_equity": round(ec.iloc[-1], 0),
        "CAGR_%": round(cagr, 1),
        "maxDD_%": round(dd, 1),
        "avg_pnl_per_trade": round(tr.pnl.mean(), 1),
    }


def yearly_table(tr):
    t = tr.copy()
    t["year"] = pd.to_datetime(t.exit_time).dt.year
    g = t.groupby("year").agg(trades=("pnl", "size"),
                              net_pnl=("pnl", "sum"),
                              win_rate=("pnl", lambda s: 100 * (s > 0).mean()))
    g["net_pnl"] = g.net_pnl.round(0)
    g["win_rate"] = g.win_rate.round(1)
    return g
