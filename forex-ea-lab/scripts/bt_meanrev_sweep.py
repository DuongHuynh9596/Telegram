"""Run the SAME a-priori mean-reversion rules (V0, untouched) across all
available H1 pairs. Full matrix reported — no post-hoc selection.

Spread assumptions (typical standard-account, per pair):
  EURUSD 1.0p, GBPUSD 1.5p, AUDUSD 1.2p, USDCAD 1.5p, USDCHF 1.5p,
  EURGBP 1.5p, EURCHF 2.0p, AUDJPY 1.8p (JPY pip = 0.01).
PnL converted to USD with flat quote-ccy rates (approximation).
"""
import pandas as pd
import bt_eurgbp_meanrev as mr
from btcommon import simulate, metrics

PAIRS = {
    # file, pip, spread_pips, contract incl. quote->USD flat conversion
    "EURUSD": ("EURUSDh1.csv.gz", 1e-4, 1.0, 100_000),
    "GBPUSD": ("GBPUSDh1.csv.gz", 1e-4, 1.5, 100_000),
    "AUDUSD": ("AUDUSDh1.csv.gz", 1e-4, 1.2, 100_000),
    "USDCAD": ("USDCADh1.csv.gz", 1e-4, 1.5, 75_000),    # CAD->USD ~0.75
    "USDCHF": ("USDCHFh1.csv.gz", 1e-4, 1.5, 110_000),   # CHF->USD ~1.10
    "EURGBP": ("EURGBPh1.csv.gz", 1e-4, 1.5, 125_000),   # GBP->USD ~1.25
    "EURCHF": ("EURCHFh1.csv.gz", 1e-4, 2.0, 110_000),
    "AUDJPY": ("AUDJPYh1.csv.gz", 1e-2, 1.8, 800),       # JPY->USD ~0.008, pip 0.01
}


def main():
    rows = []
    for pair, (fname, pip, sp_pips, contract) in PAIRS.items():
        df = pd.read_csv(f"data/{fname}", parse_dates=["Date"])
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] * pip / 10.0   # data stored as price/ (pip/10)
        df = df.sort_values("Date").reset_index(drop=True)
        mr.SPREAD = sp_pips * pip
        mr.SLIP = 0.2 * pip
        mr.COST = mr.SPREAD + mr.SLIP
        df = mr.indicators(df)
        tr = mr.run(df)
        sim, ec = simulate(tr, contract=contract)
        m = metrics(sim, ec, label=pair)
        m["period"] = f"{df.Date.min().year}-{df.Date.max().year}"
        rows.append(m)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
