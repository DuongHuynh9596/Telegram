# Backtest & Chart-Visual Guide

Everything you need to (1) see the EA's logic on the chart and (2) backtest it
properly in MT5. The Strategy Tester must run **on your own MT5** — it can't be
run from outside MetaTrader.

---

## A. Install the files

MT5 → **File → Open Data Folder**, then:

| File | Goes into |
|------|-----------|
| `FTMO_Gold_CRT_QT.mq5` (and `FTMO_Gold_SessionBreakout.mq5`) | `MQL5/Experts/` |
| `FTMO_CRT_QT_Visual.mq5` | `MQL5/Indicators/` |
| `FTMO_Gold_CRT_QT.set` | `MQL5/Presets/` (or load it from anywhere) |

Open **MetaEditor (F4)** → open each `.mq5` → **Compile (F7)**. Expect 0 errors.

---

## B. See it on the chart (visual indicator)

1. Open an **XAUUSD** chart, timeframe **M5**.
2. Drag **`FTMO_CRT_QT_Visual`** onto the chart.
3. Set `InpESTOffsetHours` to the **same value** you'll use in the EA (FTMO ≈ 7).

You'll see:
- **Red CRH / Blue CRL** box = the current H1 range (C1).
- **Gold dashed line** = the daily **True Open** (00:00 EST).
- **Green dotted verticals** = start of **Q2 / Q3** (the trading window).
- **Gray dotted verticals** = Q1 / Q4 (off by default).

A valid signal looks like: price wicks **out of the box** (sweeps CRH or CRL) and
the M5 candle **closes back inside** — during a green (Q2/Q3) zone, on the correct
side of the gold True Open line.

### ⏱️ Verify the time offset (do this once)
Look at MT5 **Market Watch** clock = server time. The green "Q2" vertical should
line up with the **London open / midnight New York**. If it's shifted, adjust
`InpESTOffsetHours` by the difference (and use the same number in the EA).

---

## C. Backtest in the Strategy Tester

1. **View → Strategy Tester** (Ctrl+R).
2. **Expert:** `FTMO_Gold_CRT_QT`
3. **Symbol:** XAUUSD · **Timeframe:** M5
4. **Modeling:** **Every tick based on real ticks** (most accurate for Gold).
5. **Date range:** at least 6–12 months; include both trending and ranging periods.
6. **Deposit:** 10000, **Leverage:** as per FTMO (e.g. 1:100).
7. **Inputs tab → Load →** `FTMO_Gold_CRT_QT.set`.
8. **Start.**

### What to look at in the report
- **Balance/Equity curve** — should be steady, not a cliff.
- **Max equity drawdown %** — must stay **well under 10%** (ideally < 6–7%).
- **Worst single day** — should never approach **5%** (the daily guard targets 4%).
- **Profit factor** > 1.3, and a sane **win rate** for the R:R you set.
- **# trades** — too few = not enough data; widen the date range.

> First-time check: run a **short range (1 month)** with the *Visual* logic in mind
> and watch the **Journal/Experts** log — it prints every CRH/CRL refresh, True Open
> capture, and entry with its quarter. That confirms the timing is correct before
> you trust a long backtest.

---

## D. Tuning order (don't over-optimize)

Change **one thing at a time**, re-run, compare:
1. `InpESTOffsetHours` — get this exactly right first (everything depends on it).
2. `InpAllowQ2 / InpAllowQ3` — try Q3-only vs Q2+Q3 for Gold.
3. `InpSLBufferPoints` / `InpSweepBufferPts` — tighter = better R:R but more stop-outs.
4. `InpTPMode` — 0 (opposite edge) vs 1 (equilibrium) vs 2 (fixed R).
5. `InpRiskPercent` — keep ≤ 0.5% until the edge is proven.

⚠️ Avoid curve-fitting: if a setting only works on one date range, it's noise.
Validate on a **separate out-of-sample** period, then **forward-test on an FTMO
demo** for several weeks before risking a paid challenge.
