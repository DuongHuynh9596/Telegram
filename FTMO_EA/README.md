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

---

# v2 — CRT + Quarterly Theory EA (`FTMO_Gold_CRT_QT.mq5`)

A smarter sibling of v1. Instead of **chasing** the breakout, it **fades the
liquidity sweep** — which is exactly what Candle Range Theory (CRT) and Daye's
Quarterly Theory predict happens to naive breakout traders.

## The model

**CRT (Candle Range Theory) — 3-candle AMD:**
- **C1 = previous H1 candle** → its high is **CRH**, its low is **CRL** (the range).
- **C2 = current H1 candle (manipulation)** → we watch **M5** for a wick that
  sweeps CRH or CRL and then **closes back inside** the range (a failed breakout).
- **Entry = fade the sweep** (Turtle Soup): sweep above CRH → **SHORT**,
  sweep below CRL → **LONG**. SL sits just beyond the sweep wick (tight → great R:R).
- **C3 = distribution** → target the opposite side of the range (CRH ↔ CRL).

**Quarterly Theory — time filter (daily cycle, EST):**

| Quarter | EST time | Session | Default |
|---------|----------|---------|---------|
| Q1 | 18:00–00:00 | Asia (accumulation) | off |
| **Q2** | **00:00–06:00** | London — **True Open** (manipulation) | **on** |
| **Q3** | **06:00–12:00** | NY AM (distribution) | **on** |
| Q4 | 12:00–18:00 | NY PM (continuation/reversal) | off |

- Sweeps are only hunted in the **enabled quarters** (default Q2 + Q3).
- **True Open bias:** the price at 00:00 EST is the day's True Open.
  Above it → longs only; below it → shorts only. (`InpUseTrueOpenBias`)

## ⏰ Server-time conversion (important)

Quarter times above are **New York (EST)**. The EA converts your broker's server
time to EST using **`InpESTOffsetHours`** = how many hours the server is *ahead* of
New York. FTMO (EET, GMT+2/+3) is **~7** hours ahead of EST, which is the default.
DST shifts both zones together, so 7 stays stable — but verify against your server
clock once.

## Key inputs (v2)

| Input | Default | Meaning |
|-------|---------|---------|
| `InpRangeTF` / `InpEntryTF` | H1 / M5 | CRT range TF and entry TF |
| `InpAllowQ1..Q4` | F/T/T/F | Which quarters may trade |
| `InpUseTrueOpenBias` | true | Long-above / short-below True Open |
| `InpESTOffsetHours` | 7 | Server hours ahead of EST |
| `InpSweepBufferPts` | 10 | Min pierce beyond CRH/CRL to count as a sweep |
| `InpSLBufferPoints` | 40 | SL distance beyond the sweep wick |
| `InpTPMode` | 0 | 0 = opposite range edge, 1 = equilibrium, 2 = R multiple |
| `InpRiskPercent` | 0.5 | Risk per trade |

The FTMO **daily-loss (4%)** and **max-DD (8%)** guards from v1 are identical here.
Note: the daily guard resets at **server midnight** (matching FTMO's daily reset),
while the True Open / quarter logic runs on **EST** — these are intentionally
separate clocks.

## Which one to use?

- **v1 (breakout)** — simpler, fewer moving parts, good first test.
- **v2 (CRT+QT)** — tighter stops, avoids stop-hunts, higher R:R, but needs the
  server-time offset set correctly. Recommended once you've validated the offset.

Backtest **both** on real Gold ticks and compare before going live.

---

## Disclaimer

For educational use. Trading leveraged products carries substantial risk. You are
responsible for complying with your prop firm's rules and for any losses. This EA
uses standard, rule-compliant order logic (no arbitrage, no grid/martingale, every
position has a Stop Loss).
