//+------------------------------------------------------------------+
//|                                      FTMO_Gold_CRT_QT.mq5         |
//|   CRT (Candle Range Theory) + Quarterly Theory EA for XAUUSD     |
//|   v2 of the FTMO Gold suite. Fades liquidity sweeps instead of   |
//|   chasing breakouts.                                             |
//|                                                                  |
//|   MODEL:                                                         |
//|     - C1 range = previous H1 candle  -> CRH / CRL                |
//|     - C2 manipulation = current H1 candle: watch M5 for a sweep  |
//|       of CRH/CRL that CLOSES BACK INSIDE the range               |
//|     - Entry = fade the sweep (Turtle Soup), SL beyond the wick   |
//|     - C3 distribution = target the opposite side of the range    |
//|                                                                  |
//|   TIMING (Quarterly Theory, daily cycle, EST):                   |
//|     Q1 18:00-00:00 | Q2 00:00-06:00 | Q3 06:00-12:00 | Q4 12:00-18:00
//|     True Day Open = 00:00 EST (start of Q2)                      |
//|     Default: only hunt sweeps in Q2 + Q3 (London + NY AM).       |
//|     Bias: price above True Open -> longs only; below -> shorts.  |
//|                                                                  |
//|   Keeps the FTMO guardrails from v1 (daily + max DD).            |
//|   NOTE: no EA guarantees a pass. Demo-test for weeks first.      |
//+------------------------------------------------------------------+
#property copyright "FTMO Gold CRT + Quarterly Theory"
#property version   "2.00"
#property strict

#include <Trade/Trade.mqh>
#include <Trade/SymbolInfo.mqh>

//==================================================================
// Inputs
//==================================================================
input group "=== Risk Management (FTMO core) ==="
input double InpRiskPercent      = 0.5;    // Risk per trade (% of balance)
input double InpDailyLossStopPct = 4.0;    // Halt for the day at this daily loss % (FTMO daily ~5%)
input double InpMaxDDStopPct     = 8.0;    // Halt EA at this overall drawdown % (FTMO max ~10%)
input double InpMaxSpreadPoints  = 50;     // Skip entries if spread (points) above this
input int    InpMaxTradesPerDay  = 3;      // Max NEW trades per EST day

input group "=== Quarterly Theory timing ==="
input int    InpESTOffsetHours   = 7;      // Hours broker SERVER time is AHEAD of New York (EST). FTMO ~7.
input bool   InpAllowQ1          = false;  // Q1 18:00-00:00 EST (Asia)
input bool   InpAllowQ2          = true;   // Q2 00:00-06:00 EST (London)  <- True Open
input bool   InpAllowQ3          = true;   // Q3 06:00-12:00 EST (NY AM)
input bool   InpAllowQ4          = false;  // Q4 12:00-18:00 EST (NY PM)
input bool   InpUseTrueOpenBias  = true;   // Only long above / short below the daily True Open
input bool   InpSkipFriday       = true;   // No new trades on Friday (weekly Q4 buffer)

input group "=== CRT structure ==="
input ENUM_TIMEFRAMES InpRangeTF = PERIOD_H1;  // C1 range timeframe (CRH/CRL)
input ENUM_TIMEFRAMES InpEntryTF = PERIOD_M5;  // Entry / sweep-detection timeframe
input double InpMinRangePoints   = 200;    // Ignore C1 if range smaller than this (points)
input double InpMaxRangePoints   = 8000;   // Ignore C1 if range larger than this (points)
input double InpSweepBufferPts   = 10;     // Min points the wick must pierce CRH/CRL to count as a sweep
input double InpSLBufferPoints   = 40;     // SL distance beyond the sweep wick (points)

input group "=== Targets ==="
// 0 = opposite side of range (CRH<->CRL) ; 1 = equilibrium (50%) ; 2 = fixed R multiple
input int    InpTPMode           = 0;      // TP mode
input double InpTP_R             = 2.0;    // R multiple (used when InpTPMode=2)

input group "=== Trade Management ==="
input bool   InpUseStepTrail     = true;   // Stepped R-based profit ladder (recommended)
// Each step: when profit reaches TrigR (in R), move SL to LockR (in R, beyond entry).
input double InpStep1TrigR       = 1.0;    // Step 1 trigger (R)
input double InpStep1LockR       = 0.1;    // Step 1 lock  (R)  -> breakeven + small profit
input double InpStep2TrigR       = 1.5;    // Step 2 trigger (R)
input double InpStep2LockR       = 0.7;    // Step 2 lock  (R)
input double InpStep3TrigR       = 2.0;    // Step 3 trigger (R)
input double InpStep3LockR       = 1.3;    // Step 3 lock  (R)
input bool   InpUseTrailing      = true;   // ATR trailing after the last step
input int    InpATRPeriod        = 14;     // ATR period
input double InpTrailATRMult     = 2.0;    // Trailing distance = ATR * this
input double InpTrailStartR      = 2.0;    // Only start ATR trailing past this R
input int    InpCloseAllHourEST  = 16;     // Force-flatten at this EST hour (end of Q4 buffer)

input group "=== SMT Divergence filter (XAU vs DXY) ==="
input bool   InpUseSMT            = true;     // Require SMT divergence to confirm the sweep
input string InpSMTSymbol         = "USDX";   // Correlated symbol (DXY/USDX, or e.g. EURUSD)
input bool   InpSMTInverse        = true;     // true = inversely correlated (DXY/USDX); false = positive (EURUSD)
input int    InpSMTLookback       = 10;       // Bars (entry TF) to find the prior reference extreme
input bool   InpSMTBlockIfNoData  = false;    // If SMT symbol data missing: true=block trade, false=skip filter

input group "=== General ==="
input long   InpMagic            = 88020;  // Magic number
input string InpComment          = "GoldCRTQT";

//==================================================================
// Globals
//==================================================================
CTrade        trade;
CSymbolInfo   sym;

double   g_CRH = 0.0, g_CRL = 0.0;     // current C1 range
bool     g_rangeValid = false;
datetime g_c2BarTime  = 0;             // time of the current C2 (range-TF) candle
bool     g_tradedThisC2 = false;       // already took a trade on this C2 candle

datetime g_lastEntryBar = 0;           // last processed entry-TF bar

// Open-position tracking (one trade at a time) for the stepped trailing ladder
ulong    g_posTicket = 0;              // ticket currently being managed
double   g_origRisk  = 0.0;            // original SL distance (1R) of that position
double   g_origEntry = 0.0;            // original entry price of that position

// Quarterly Theory day tracking (EST)
int      g_estDay = -1;                // day-of-year in EST, to detect new EST day
double   g_trueOpen = 0.0;             // daily True Open price (00:00 EST)
bool     g_trueOpenSet = false;
int      g_tradesToday = 0;

// FTMO guard day tracking (server midnight = FTMO daily reset)
datetime g_guardDayStart = 0;
double   g_dayStartEquity = 0.0;
double   g_peakEquity = 0.0;
double   g_initBalance = 0.0;
bool     g_haltDay = false;
bool     g_haltAll = false;

int      g_atrHandle = INVALID_HANDLE;

//==================================================================
// Time helpers (Quarterly Theory in EST)
//==================================================================
double Pts(double points) { return points * _Point; }

datetime ServerToEST(datetime serverTime)
{
   return serverTime - (datetime)(InpESTOffsetHours * 3600);
}

// Returns 1..4 for the daily quarter of an EST time
int DailyQuarterEST(datetime estTime)
{
   MqlDateTime dt; TimeToStruct(estTime, dt);
   int h = dt.hour;
   if(h >= 18 || h < 0)  return 1;          // 18:00-24:00
   if(h >= 0  && h < 6)  return 2;          // 00:00-06:00
   if(h >= 6  && h < 12) return 3;          // 06:00-12:00
   return 4;                                 // 12:00-18:00
}

bool QuarterAllowed(int q)
{
   if(q == 1) return InpAllowQ1;
   if(q == 2) return InpAllowQ2;
   if(q == 3) return InpAllowQ3;
   if(q == 4) return InpAllowQ4;
   return false;
}

datetime DayStartServer(datetime t)
{
   MqlDateTime dt; TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}

//==================================================================
// Position / order utilities (symbol + magic)
//==================================================================
int CountOpenPositions()
{
   int c = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic) c++;
   }
   return c;
}

void CloseAllPositions()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
         trade.PositionClose(tk);
   }
}

//==================================================================
// Risk-based lot sizing
//==================================================================
double CalcLot(double slDistancePrice)
{
   if(slDistancePrice <= 0) return 0.0;
   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPercent / 100.0;
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0 || tickSize <= 0) return 0.0;

   double valuePerLot = (slDistancePrice / tickSize) * tickValue;
   if(valuePerLot <= 0) return 0.0;

   double lot = riskMoney / valuePerLot;
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   lot = MathFloor(lot / lotStep) * lotStep;
   if(lot < minLot) lot = minLot;
   if(lot > maxLot) lot = maxLot;
   return NormalizeDouble(lot, 2);
}

double GetATR()
{
   if(g_atrHandle == INVALID_HANDLE) return 0.0;
   double buf[];
   if(CopyBuffer(g_atrHandle, 0, 0, 1, buf) <= 0) return 0.0;
   return buf[0];
}

//==================================================================
// Daily state + FTMO guards
//==================================================================
void UpdateGuardDay()
{
   datetime ds = DayStartServer(TimeCurrent());
   if(ds != g_guardDayStart)
   {
      g_guardDayStart  = ds;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      g_haltDay        = false;
      PrintFormat("[%s] FTMO daily reset. StartEquity=%.2f", InpComment, g_dayStartEquity);
   }
}

void UpdateESTDay()
{
   datetime est = ServerToEST(TimeCurrent());
   MqlDateTime dt; TimeToStruct(est, dt);
   if(dt.day_of_year != g_estDay)
   {
      g_estDay       = dt.day_of_year;
      g_trueOpenSet  = false;     // will be captured at first tick of EST Q2
      g_tradesToday  = 0;
   }
   // Capture True Open at/after 00:00 EST (start of Q2) once per EST day
   if(!g_trueOpenSet && dt.hour >= 0)
   {
      g_trueOpen    = (SymbolInfoDouble(_Symbol, SYMBOL_BID) +
                       SymbolInfoDouble(_Symbol, SYMBOL_ASK)) / 2.0;
      g_trueOpenSet = true;
      PrintFormat("[%s] True Day Open captured: %.2f (EST day %d)",
                  InpComment, g_trueOpen, g_estDay);
   }
}

void CheckGuards()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > g_peakEquity) g_peakEquity = equity;

   if(!g_haltDay && g_dayStartEquity > 0)
   {
      double dayLossPct = (g_dayStartEquity - equity) / g_dayStartEquity * 100.0;
      if(dayLossPct >= InpDailyLossStopPct)
      {
         g_haltDay = true;
         CloseAllPositions();
         PrintFormat("[%s] DAILY LOSS GUARD hit (%.2f%%). Halt for today.", InpComment, dayLossPct);
      }
   }
   if(!g_haltAll && g_initBalance > 0)
   {
      double ddPct = (g_initBalance - equity) / g_initBalance * 100.0;
      if(ddPct >= InpMaxDDStopPct)
      {
         g_haltAll = true;
         CloseAllPositions();
         PrintFormat("[%s] MAX DD GUARD hit (%.2f%%). Halt EA. Manual reset required.", InpComment, ddPct);
      }
   }
}

//==================================================================
// CRT: refresh the C1 range when a new C2 (range-TF) candle starts
//==================================================================
void RefreshRange()
{
   datetime curBar = iTime(_Symbol, InpRangeTF, 0);
   if(curBar == 0) return;
   if(curBar == g_c2BarTime) return;   // still same C2 candle

   // New range-TF candle -> previous candle (index 1) becomes C1
   g_c2BarTime     = curBar;
   g_tradedThisC2  = false;

   double crh = iHigh(_Symbol, InpRangeTF, 1);
   double crl = iLow (_Symbol, InpRangeTF, 1);
   if(crh <= 0 || crl <= 0 || crh <= crl) { g_rangeValid = false; return; }

   double rangePts = (crh - crl) / _Point;
   if(rangePts < InpMinRangePoints || rangePts > InpMaxRangePoints)
   {
      g_rangeValid = false;
      return;
   }
   g_CRH = crh; g_CRL = crl; g_rangeValid = true;
   PrintFormat("[%s] New C1 range. CRH=%.2f CRL=%.2f (%.0f pts)",
               InpComment, g_CRH, g_CRL, rangePts);
}

//==================================================================
// Compute TP for a fade trade
//==================================================================
double ComputeTP(bool isLong, double entry, double slDist)
{
   double eq = (g_CRH + g_CRL) / 2.0;     // equilibrium
   if(InpTPMode == 1) return NormalizeDouble(eq, _Digits);
   if(InpTPMode == 2)
      return NormalizeDouble(isLong ? entry + slDist*InpTP_R
                                    : entry - slDist*InpTP_R, _Digits);
   // default: opposite side of the range
   return NormalizeDouble(isLong ? g_CRH : g_CRL, _Digits);
}

//==================================================================
// SMT divergence filter (XAU vs a correlated symbol, e.g. DXY/USDX)
//
// Idea: when XAU sweeps liquidity (makes a fresh local extreme), a truly
// correlated instrument should confirm by making its own matching extreme.
// If it FAILS to (divergence), the sweep is likely manipulation -> confirm fade.
//
// isLong = true  : XAU swept a LOW (new local low). Confirm if the correlated
//                  symbol does NOT make the matching extreme.
//   - inverse corr (DXY): DXY should make a HIGHER HIGH -> divergence if it does NOT.
//   - positive corr (EURUSD): should make a LOWER LOW -> divergence if it does NOT.
// Returns true = SMT confirms the entry.
//==================================================================
bool CheckSMT(bool isLong)
{
   if(!InpUseSMT) return true;

   string s = InpSMTSymbol;
   if(!SymbolSelect(s, true)) return !InpSMTBlockIfNoData;

   int L = InpSMTLookback;
   if(L < 2) L = 2;

   // need bars 1..L+1 available on both symbols
   if(Bars(s, InpEntryTF) < L + 2 || Bars(_Symbol, InpEntryTF) < L + 2)
      return !InpSMTBlockIfNoData;

   // XAU current extreme (last closed bar) and prior reference extreme (bars 2..L+1)
   double xauNowLow  = iLow (_Symbol, InpEntryTF, 1);
   double xauNowHigh = iHigh(_Symbol, InpEntryTF, 1);

   // correlated symbol values (index-aligned; standard SMT approximation)
   double cNowHigh = iHigh(s, InpEntryTF, 1);
   double cNowLow  = iLow (s, InpEntryTF, 1);
   if(cNowHigh <= 0 || cNowLow <= 0) return !InpSMTBlockIfNoData;

   double cPrevHigh = -DBL_MAX, cPrevLow = DBL_MAX;
   double xPrevLow  = DBL_MAX,  xPrevHigh = -DBL_MAX;
   for(int i = 2; i <= L + 1; i++)
   {
      double ch = iHigh(s, InpEntryTF, i);
      double cl = iLow (s, InpEntryTF, i);
      if(ch > cPrevHigh) cPrevHigh = ch;
      if(cl < cPrevLow ) cPrevLow  = cl;

      double xl = iLow (_Symbol, InpEntryTF, i);
      double xh = iHigh(_Symbol, InpEntryTF, i);
      if(xl < xPrevLow ) xPrevLow  = xl;
      if(xh > xPrevHigh) xPrevHigh = xh;
   }

   if(isLong)
   {
      // XAU must have actually made a fresh local low for the comparison to be valid
      if(xauNowLow >= xPrevLow) return false;
      if(InpSMTInverse)
         return (cNowHigh < cPrevHigh);   // DXY failed to make a higher high -> bullish SMT
      else
         return (cNowLow  > cPrevLow);    // EURUSD failed to make a lower low -> bullish SMT
   }
   else
   {
      if(xauNowHigh <= xPrevHigh) return false;
      if(InpSMTInverse)
         return (cNowLow  > cPrevLow);    // DXY failed to make a lower low -> bearish SMT
      else
         return (cNowHigh < cPrevHigh);   // EURUSD failed to make a higher high -> bearish SMT
   }
}

//==================================================================
// CRT sweep detection on a CLOSED entry-TF candle -> fade entry
//==================================================================
void HuntSweep()
{
   if(!g_rangeValid || g_haltDay || g_haltAll) return;
   if(g_tradedThisC2)                          return;
   if(CountOpenPositions() > 0)                return;
   if(g_tradesToday >= InpMaxTradesPerDay)      return;

   // process only once per closed entry-TF bar
   datetime entryBar = iTime(_Symbol, InpEntryTF, 0);
   if(entryBar == g_lastEntryBar) return;
   g_lastEntryBar = entryBar;

   // timing filter (Quarterly Theory)
   datetime est = ServerToEST(TimeCurrent());
   int q = DailyQuarterEST(est);
   if(!QuarterAllowed(q)) return;

   if(InpSkipFriday)
   {
      MqlDateTime dt; TimeToStruct(est, dt);
      if(dt.day_of_week == 5) return;   // Friday
   }

   if(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPoints) return;

   // last CLOSED entry-TF candle = index 1
   double h = iHigh (_Symbol, InpEntryTF, 1);
   double l = iLow  (_Symbol, InpEntryTF, 1);
   double c = iClose(_Symbol, InpEntryTF, 1);
   double sweepBuf = Pts(InpSweepBufferPts);
   double slBuf    = Pts(InpSLBufferPoints);

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // --- Bearish manipulation: swept CRH, closed back inside -> SHORT ---
   bool bearSweep = (h > g_CRH + sweepBuf) && (c < g_CRH);
   // --- Bullish manipulation: swept CRL, closed back inside -> LONG ---
   bool bullSweep = (l < g_CRL - sweepBuf) && (c > g_CRL);

   if(bearSweep)
   {
      if(InpUseTrueOpenBias && g_trueOpenSet && bid > g_trueOpen) return; // bias = short only below TO
      if(!CheckSMT(false)) { PrintFormat("[%s] SHORT sweep rejected: no SMT divergence.", InpComment); return; }
      double entry = bid;
      double sl    = NormalizeDouble(h + slBuf, _Digits);
      double slDist= MathAbs(sl - entry);
      if(slDist <= 0) return;
      double tp    = ComputeTP(false, entry, slDist);
      double lot   = CalcLot(slDist);
      if(lot <= 0) return;
      trade.SetExpertMagicNumber(InpMagic);
      if(trade.Sell(lot, _Symbol, entry, sl, tp, InpComment))
      {
         g_tradedThisC2 = true;
         PrintFormat("[%s] SHORT fade (Q%d). Swept CRH %.2f | entry~%.2f SL %.2f TP %.2f lot %.2f",
                     InpComment, q, g_CRH, entry, sl, tp, lot);
      }
   }
   else if(bullSweep)
   {
      if(InpUseTrueOpenBias && g_trueOpenSet && bid < g_trueOpen) return; // bias = long only above TO
      if(!CheckSMT(true)) { PrintFormat("[%s] LONG sweep rejected: no SMT divergence.", InpComment); return; }
      double entry = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double sl    = NormalizeDouble(l - slBuf, _Digits);
      double slDist= MathAbs(entry - sl);
      if(slDist <= 0) return;
      double tp    = ComputeTP(true, entry, slDist);
      double lot   = CalcLot(slDist);
      if(lot <= 0) return;
      trade.SetExpertMagicNumber(InpMagic);
      if(trade.Buy(lot, _Symbol, entry, sl, tp, InpComment))
      {
         g_tradedThisC2 = true;
         PrintFormat("[%s] LONG fade (Q%d). Swept CRL %.2f | entry~%.2f SL %.2f TP %.2f lot %.2f",
                     InpComment, q, g_CRL, entry, sl, tp, lot);
      }
   }
}

//==================================================================
// Stepped R-based trailing ladder (+ optional ATR trail past last step)
//
// Profit is measured in R = multiples of the ORIGINAL SL distance of THIS
// position (captured when the position first appears). Each step moves the SL
// to (entry +/- LockR * 1R) once profit reaches TrigR. SL only ever moves
// forward. After the last step, an ATR trail lets winners run.
//==================================================================
// Returns the highest lock (in R) earned for a given profit (in R), or
// -DBL_MAX if no step reached yet.
double LadderLockR(double profitR)
{
   double lock = -DBL_MAX;
   if(profitR >= InpStep1TrigR) lock = InpStep1LockR;
   if(profitR >= InpStep2TrigR) lock = InpStep2LockR;
   if(profitR >= InpStep3TrigR) lock = InpStep3LockR;
   return lock;
}

void ManageOpenPositions()
{
   bool found = false;

   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      found = true;
      long   type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

      // Capture the ORIGINAL 1R when we first see this position
      if(tk != g_posTicket)
      {
         g_posTicket = tk;
         g_origEntry = open;
         g_origRisk  = MathAbs(open - sl);   // SL is still the original here
      }
      double R = g_origRisk;
      if(R <= 0) continue;

      double newSL = sl;

      if(type == POSITION_TYPE_BUY)
      {
         double profitR = (bid - open) / R;

         if(InpUseStepTrail)
         {
            double lockR = LadderLockR(profitR);
            if(lockR > -DBL_MAX)
            {
               double cand = open + lockR * R;
               if(cand > newSL) newSL = cand;
            }
         }
         if(InpUseTrailing && profitR >= InpTrailStartR)
         {
            double atr = GetATR();
            if(atr > 0) { double tr = bid - atr*InpTrailATRMult; if(tr > newSL) newSL = tr; }
         }
         if(newSL > sl + _Point)
            trade.PositionModify(tk, NormalizeDouble(newSL,_Digits), tp);
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double profitR = (open - ask) / R;

         if(InpUseStepTrail)
         {
            double lockR = LadderLockR(profitR);
            if(lockR > -DBL_MAX)
            {
               double cand = open - lockR * R;
               if(cand < newSL || newSL == 0) newSL = cand;
            }
         }
         if(InpUseTrailing && profitR >= InpTrailStartR)
         {
            double atr = GetATR();
            if(atr > 0) { double tr = ask + atr*InpTrailATRMult; if(tr < newSL || newSL==0) newSL = tr; }
         }
         if(newSL < sl - _Point || (sl == 0 && newSL > 0))
            trade.PositionModify(tk, NormalizeDouble(newSL,_Digits), tp);
      }
   }

   if(!found) { g_posTicket = 0; g_origRisk = 0; g_origEntry = 0; }
}

//==================================================================
// Lifecycle
//==================================================================
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   trade.SetTypeFillingBySymbol(_Symbol);

   g_initBalance    = AccountInfoDouble(ACCOUNT_BALANCE);
   g_peakEquity     = AccountInfoDouble(ACCOUNT_EQUITY);
   g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_guardDayStart  = DayStartServer(TimeCurrent());

   g_atrHandle = iATR(_Symbol, InpEntryTF, InpATRPeriod);
   if(g_atrHandle == INVALID_HANDLE) Print("[",InpComment,"] WARNING: ATR handle failed.");

   if(InpUseSMT)
   {
      if(SymbolSelect(InpSMTSymbol, true))
         PrintFormat("[%s] SMT filter ON. Symbol=%s inverse=%s",
                     InpComment, InpSMTSymbol, (InpSMTInverse?"yes":"no"));
      else
         PrintFormat("[%s] WARNING: SMT symbol '%s' not found. Check the exact name in Market Watch (DXY/USDX/USDOLLAR...).",
                     InpComment, InpSMTSymbol);
   }

   if(StringFind(_Symbol, "XAU") < 0)
      Print("[",InpComment,"] NOTE: tuned for XAUUSD (Gold). Current symbol: ", _Symbol);

   PrintFormat("[%s] Init OK. InitBalance=%.2f Risk=%.2f%% ESTOffset=%dh RangeTF=%d EntryTF=%d",
               InpComment, g_initBalance, InpRiskPercent, InpESTOffsetHours, InpRangeTF, InpEntryTF);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(g_atrHandle != INVALID_HANDLE) IndicatorRelease(g_atrHandle);
}

void OnTick()
{
   if(!sym.Name(_Symbol)) return;
   sym.RefreshRates();

   UpdateGuardDay();
   UpdateESTDay();
   CheckGuards();
   if(g_haltAll) return;

   // Force-flatten at end-of-day EST
   datetime est = ServerToEST(TimeCurrent());
   MqlDateTime edt; TimeToStruct(est, edt);
   if(edt.hour >= InpCloseAllHourEST && CountOpenPositions() > 0)
   {
      CloseAllPositions();
      return;
   }

   RefreshRange();
   if(!g_haltDay) HuntSweep();
   ManageOpenPositions();
}

//==================================================================
// Count new entries per EST day
//==================================================================
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult  &result)
{
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD && HistoryDealSelect(trans.deal))
   {
      if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) == DEAL_ENTRY_IN &&
         HistoryDealGetInteger(trans.deal, DEAL_MAGIC) == InpMagic &&
         HistoryDealGetString (trans.deal, DEAL_SYMBOL) == _Symbol)
         g_tradesToday++;
   }
}
//+------------------------------------------------------------------+
