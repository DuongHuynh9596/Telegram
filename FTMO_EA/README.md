# FTMO Gold Session-Breakout EA (XAUUSD, MT5)

An Opening-Range **session breakout** Expert Advisor for **XAUUSD (Gold)**, built for
prop-firm challenges such as **FTMO 10k**. Its #1 priority is **not breaching the
drawdown limits** — profit comes second.

> ⚠️ **No EA guarantees a pass.** Forward-test on an **FTMO Free Trial / demo** for
> several weeks before risking a paid challenge. Past backtest results never
> guarantee live performance.

---

## How the strategy works

1. **Build the box** — during the "range window" (default `00:00–07:00` server time)
   the EA records the session high/low → this is the *opening range*.
2. **Arm breakout orders** — once the window ends, it places **two stop orders**:
   - `Buy Stop` just above the box high
   - `Sell Stop` just below the box low
3. **OCO** — when price breaks one side and fills, the opposite pending is cancelled.
4. **Hard SL/TP on every trade** — SL at the opposite box edge (or ATR), TP = `1.5R`.
5. **Manage** — breakeven at `0.8R`, then ATR trailing.
6. **Flatten** — pendings cancelled after the trade window; all positions force-closed
   before the `CloseAllHour` (no overnight risk).

---

## The FTMO guardrails (most important part)

FTMO 10k limits: **5% daily loss (-$500)** and **10% max loss (-$1000)**.

| Guard | Default | What it does |
|-------|---------|--------------|
| `InpDailyLossStopPct` | **4%** | If equity drops 4% vs the day's start equity → cancel pendings, close trades, **halt for the day**. Keeps you clear of the 5% daily breach. |
| `InpMaxDDStopPct` | **8%** | If equity drops 8% vs the starting balance → **halt the EA entirely** (manual reset). Keeps you clear of the 10% max breach. |
| `InpRiskPercent` | **0.5%** | Risk per trade. Lot is auto-sized from SL distance. |
| `InpMaxTradesPerDay` | **1** | One breakout shot per day by default. |

These are intentionally conservative. Passing slow but safe beats failing fast.

---

## Installation

1. Open **MetaEditor** (from MT5: `Tools → MetaQuotes Language Editor`, or F4).
2. Copy `FTMO_Gold_SessionBreakout.mq5` into
   `MQL5/Experts/` of your MT5 data folder
   (MT5: `File → Open Data Folder`).
3. Press **Compile** (F7). It should compile with 0 errors.
4. In MT5, drag the EA onto an **XAUUSD** chart (M15 recommended).
5. Enable **Algo Trading** (the toolbar button) and tick *Allow Algo Trading* in the
   EA dialog's *Common* tab.

---

## ⏰ IMPORTANT: set the hours to YOUR broker's server time

All hour inputs are in **broker server time**, *not* your local time. FTMO's MT5
server time is usually around **GMT+2/GMT+3 (EET)**. Check the clock in MT5's
*Market Watch* and adjust:

- `InpRangeStartHour` / `InpRangeEndHour` — when the box is built (Asian / pre-London).
- `InpTradeEndHour` — stop taking new breakouts (avoid late-day chop).
- `InpCloseAllHour` — force-flatten before rollover.

A common Gold setup: build the box during the Asian session, breakout into the
**London open**. Tune `InpRangeStartHour/EndHour` so the box ends right before
London opens on your server's clock.

---

## Tuning tips for Gold

- Gold is volatile → keep `InpRiskPercent` at **0.5%** (or lower) while testing.
- `InpMinRangePoints` / `InpMaxRangePoints` filter out dead or crazy sessions.
- Raise `InpMaxSpreadPoints` only if your broker's Gold spread is naturally wide.
- Backtest in the **Strategy Tester** with *Every tick based on real ticks* and
  real Gold history before going live.

---

## Disclaimer

For educational use. Trading leveraged products carries substantial risk. You are
responsible for complying with your prop firm's rules and for any losses. This EA
uses standard, rule-compliant order logic (no arbitrage, no grid/martingale, every
position has a Stop Loss).
