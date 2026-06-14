//+------------------------------------------------------------------+
//|                                FTMO_Gold_SessionBreakout.mq5     |
//|   Opening-Range Session Breakout EA for XAUUSD (Gold)            |
//|   Designed for prop-firm challenges (FTMO 10k and similar).      |
//|                                                                  |
//|   Philosophy: survive first, profit second.                     |
//|   - Hard daily-loss guard  (blocks the 5% daily-DD breach)       |
//|   - Hard max-drawdown guard (blocks the 10% overall breach)      |
//|   - Risk-based position sizing, every trade has a Stop Loss      |
//|                                                                  |
//|   NOTE: No EA guarantees a pass. Forward-test on an FTMO demo    |
//|   for several weeks before risking a paid challenge.            |
//+------------------------------------------------------------------+
#property copyright "FTMO Gold Session Breakout"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>
#include <Trade/SymbolInfo.mqh>

//==================================================================
// Inputs
//==================================================================
input group "=== Risk Management (FTMO core) ==="
input double InpRiskPercent      = 0.5;    // Risk per trade (% of balance)
input double InpDailyLossStopPct = 4.0;    // Stop trading for the day at this daily loss % (FTMO daily limit ~5%)
input double InpMaxDDStopPct     = 8.0;    // Stop EA entirely at this overall drawdown % (FTMO max ~10%)
input double InpMaxSpreadPoints  = 50;     // Skip entries if spread (points) above this

input group "=== Session / Opening Range (broker server time) ==="
input int    InpRangeStartHour   = 0;      // Range build START hour
input int    InpRangeStartMin     = 0;     // Range build START minute
input int    InpRangeEndHour     = 7;      // Range build END hour (box is locked at this time)
input int    InpRangeEndMin       = 0;     // Range build END minute
input int    InpTradeEndHour     = 16;     // No new entries / cancel pendings after this hour
input int    InpCloseAllHour     = 22;     // Force-close everything at this hour (avoid overnight)

input group "=== Breakout / Orders ==="
input double InpBufferPoints     = 30;     // Buffer beyond box edge for the stop entry (points)
input double InpMinRangePoints   = 150;    // Ignore session if box smaller than this (points)
input double InpMaxRangePoints   = 6000;   // Ignore session if box larger than this (points)
input double InpSLBufferPoints   = 50;     // Extra SL distance beyond opposite box edge (points)
input double InpTP_R             = 1.5;    // Take Profit as multiple of risk (R)
input bool   InpUseATRStop       = false;  // Use ATR for SL instead of box edge
input int    InpATRPeriod        = 14;     // ATR period (if ATR stop enabled)
input double InpATRMultSL        = 2.0;    // ATR multiplier for SL (if enabled)

input group "=== Trade Management ==="
input bool   InpUseBreakeven     = true;   // Move SL to breakeven
input double InpBE_TriggerR      = 0.8;    // Trigger breakeven at this R profit
input double InpBE_LockPoints    = 20;     // Lock-in points above entry when BE triggers
input bool   InpUseTrailing      = true;   // Trail stop after breakeven
input double InpTrailATRMult     = 2.0;    // Trailing distance = ATR * this

input group "=== General ==="
input long   InpMagic            = 88010;  // Magic number
input int    InpMaxTradesPerDay  = 1;      // Max NEW trades per day (1 = one shot per session)
input string InpComment          = "GoldSB";

//==================================================================
// Globals
//==================================================================
CTrade        trade;
CSymbolInfo   sym;

double  g_boxHigh      = 0.0;
double  g_boxLow       = 0.0;
bool    g_boxReady     = false;     // box locked for today
bool    g_ordersPlaced = false;     // pendings placed for today
int     g_tradesToday  = 0;
datetime g_dayStart    = 0;         // start-of-day (server) for the current trading day
double  g_dayStartEquity = 0.0;     // equity captured at day start
double  g_peakEquity   = 0.0;       // running peak equity (for overall DD)
double  g_initBalance  = 0.0;       // balance when EA first attached
bool    g_haltDay      = false;     // daily loss limit hit -> halt for today
bool    g_haltAll      = false;     // overall DD limit hit -> halt permanently
int     g_atrHandle    = INVALID_HANDLE;

//==================================================================
// Helpers
//==================================================================
double Point2Price(double points) { return points * _Point; }

datetime DayStart(datetime t)
{
   MqlDateTime dt; TimeToStruct(t, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}

datetime TodayAt(int hour, int minute)
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   dt.hour = hour; dt.min = minute; dt.sec = 0;
   return StructToTime(dt);
}

bool InRangeWindow(datetime now)
{
   datetime s = TodayAt(InpRangeStartHour, InpRangeStartMin);
   datetime e = TodayAt(InpRangeEndHour,   InpRangeEndMin);
   return (now >= s && now < e);
}

bool RangeWindowEnded(datetime now)
{
   return now >= TodayAt(InpRangeEndHour, InpRangeEndMin);
}

bool TradeWindowOpen(datetime now)
{
   datetime e = TodayAt(InpRangeEndHour, InpRangeEndMin);
   datetime te = TodayAt(InpTradeEndHour, 0);
   return (now >= e && now < te);
}

double CurrentSpreadPoints()
{
   return (SymbolInfoInteger(_Symbol, SYMBOL_SPREAD));
}

//==================================================================
// Position / order utilities (filtered by symbol + magic)
//==================================================================
int CountOpenPositions()
{
   int c = 0;
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
         c++;
   }
   return c;
}

int CountPendingOrders()
{
   int c = 0;
   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      ulong tk = OrderGetTicket(i);
      if(tk == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol &&
         OrderGetInteger(ORDER_MAGIC) == InpMagic)
         c++;
   }
   return c;
}

void CancelAllPendings()
{
   for(int i = OrdersTotal()-1; i >= 0; i--)
   {
      ulong tk = OrderGetTicket(i);
      if(tk == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) == _Symbol &&
         OrderGetInteger(ORDER_MAGIC) == InpMagic)
         trade.OrderDelete(tk);
   }
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
// Lot sizing by risk % and SL distance (in price)
//==================================================================
double CalcLot(double slDistancePrice)
{
   if(slDistancePrice <= 0) return 0.0;

   double balance   = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPercent / 100.0;

   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0 || tickSize <= 0) return 0.0;

   double valuePerLotForSL = (slDistancePrice / tickSize) * tickValue;
   if(valuePerLotForSL <= 0) return 0.0;

   double lot = riskMoney / valuePerLotForSL;

   // normalize to broker constraints
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   lot = MathFloor(lot / lotStep) * lotStep;
   if(lot < minLot) lot = minLot;     // never below min; risk slightly higher but SL still hard-caps loss
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
// Daily / overall risk guards
//==================================================================
void UpdateDayState()
{
   datetime ds = DayStart(TimeCurrent());
   if(ds != g_dayStart)
   {
      // New trading day -> reset daily counters
      g_dayStart         = ds;
      g_dayStartEquity   = AccountInfoDouble(ACCOUNT_EQUITY);
      g_tradesToday      = 0;
      g_boxReady         = false;
      g_ordersPlaced     = false;
      g_haltDay          = false;
      g_boxHigh          = 0.0;
      g_boxLow           = 0.0;
      PrintFormat("[%s] New day. StartEquity=%.2f", InpComment, g_dayStartEquity);
   }
}

void CheckGuards()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);

   // running peak for overall DD
   if(equity > g_peakEquity) g_peakEquity = equity;

   // --- Daily loss guard (vs equity at day start) ---
   if(!g_haltDay && g_dayStartEquity > 0)
   {
      double dayLossPct = (g_dayStartEquity - equity) / g_dayStartEquity * 100.0;
      if(dayLossPct >= InpDailyLossStopPct)
      {
         g_haltDay = true;
         CancelAllPendings();
         CloseAllPositions();
         PrintFormat("[%s] DAILY LOSS GUARD hit (%.2f%%). Halting for today.",
                     InpComment, dayLossPct);
      }
   }

   // --- Overall max-DD guard (vs initial balance baseline) ---
   if(!g_haltAll && g_initBalance > 0)
   {
      double ddPct = (g_initBalance - equity) / g_initBalance * 100.0;
      if(ddPct >= InpMaxDDStopPct)
      {
         g_haltAll = true;
         CancelAllPendings();
         CloseAllPositions();
         PrintFormat("[%s] MAX DD GUARD hit (%.2f%%). Halting EA permanently. Manual reset required.",
                     InpComment, ddPct);
      }
   }
}

//==================================================================
// Build the opening-range box
//==================================================================
void BuildBox()
{
   datetime now = TimeCurrent();

   // While inside the range window, expand the box from M1 highs/lows
   if(InRangeWindow(now))
   {
      double hi = iHigh(_Symbol, PERIOD_M1, 0);
      double lo = iLow(_Symbol, PERIOD_M1, 0);
      if(g_boxHigh == 0.0 || hi > g_boxHigh) g_boxHigh = hi;
      if(g_boxLow  == 0.0 || lo < g_boxLow ) g_boxLow  = lo;
      return;
   }

   // When range window has just ended, lock the box
   if(RangeWindowEnded(now) && !g_boxReady && g_boxHigh > 0 && g_boxLow > 0)
   {
      double rangePts = (g_boxHigh - g_boxLow) / _Point;
      if(rangePts < InpMinRangePoints || rangePts > InpMaxRangePoints)
      {
         PrintFormat("[%s] Box rejected (range=%.0f pts, allowed %.0f-%.0f). No trade today.",
                     InpComment, rangePts, InpMinRangePoints, InpMaxRangePoints);
         g_boxReady     = true;   // marked ready but we won't place orders (range invalid)
         g_ordersPlaced = true;   // block placement
         return;
      }
      g_boxReady = true;
      PrintFormat("[%s] Box locked. High=%.2f Low=%.2f Range=%.0f pts",
                  InpComment, g_boxHigh, g_boxLow, rangePts);
   }
}

//==================================================================
// Place OCO breakout stop orders at both edges of the box
//==================================================================
void PlaceBreakoutOrders()
{
   if(!g_boxReady || g_ordersPlaced) return;
   if(g_haltDay || g_haltAll)        return;
   if(g_tradesToday >= InpMaxTradesPerDay) return;
   if(!TradeWindowOpen(TimeCurrent()))     return;
   if(CurrentSpreadPoints() > InpMaxSpreadPoints)
   {
      PrintFormat("[%s] Spread too high (%.0f pts). Waiting.",
                  InpComment, CurrentSpreadPoints());
      return;
   }

   double buffer = Point2Price(InpBufferPoints);
   double slBuf  = Point2Price(InpSLBufferPoints);

   double buyEntry  = NormalizeDouble(g_boxHigh + buffer, _Digits);
   double sellEntry = NormalizeDouble(g_boxLow  - buffer, _Digits);

   double buySL, sellSL;
   if(InpUseATRStop)
   {
      double atr = GetATR();
      if(atr <= 0) { Print("[",InpComment,"] ATR unavailable, fallback to box SL."); ApplyBoxStops(buySL, sellSL, slBuf); }
      else { buySL = buyEntry - atr*InpATRMultSL; sellSL = sellEntry + atr*InpATRMultSL; }
   }
   else
   {
      buySL  = NormalizeDouble(g_boxLow  - slBuf, _Digits);   // buy stop -> SL below box
      sellSL = NormalizeDouble(g_boxHigh + slBuf, _Digits);   // sell stop -> SL above box
   }

   double buySLDist  = MathAbs(buyEntry  - buySL);
   double sellSLDist = MathAbs(sellEntry - sellSL);

   double buyTP  = NormalizeDouble(buyEntry  + buySLDist  * InpTP_R, _Digits);
   double sellTP = NormalizeDouble(sellEntry - sellSLDist * InpTP_R, _Digits);

   double buyLot  = CalcLot(buySLDist);
   double sellLot = CalcLot(sellSLDist);
   if(buyLot <= 0 || sellLot <= 0)
   {
      Print("[",InpComment,"] Lot calc failed, skipping.");
      return;
   }

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // Only place a stop order if entry is correctly beyond current price
   datetime expiry = TodayAt(InpTradeEndHour, 0);
   trade.SetExpertMagicNumber(InpMagic);

   bool okBuy = false, okSell = false;
   if(buyEntry > ask)
      okBuy = trade.BuyStop(buyLot, buyEntry, _Symbol, buySL, buyTP,
                            ORDER_TIME_SPECIFIED, expiry, InpComment);
   if(sellEntry < bid)
      okSell = trade.SellStop(sellLot, sellEntry, _Symbol, sellSL, sellTP,
                              ORDER_TIME_SPECIFIED, expiry, InpComment);

   if(okBuy || okSell)
   {
      g_ordersPlaced = true;
      PrintFormat("[%s] Breakout orders placed. BuyStop@%.2f SL%.2f TP%.2f lot%.2f | SellStop@%.2f SL%.2f TP%.2f lot%.2f",
                  InpComment, buyEntry, buySL, buyTP, buyLot,
                  sellEntry, sellSL, sellTP, sellLot);
   }
}

// Box-edge SL fallback (used when ATR is requested but unavailable)
void ApplyBoxStops(double &buySL, double &sellSL, double slBuf)
{
   buySL  = NormalizeDouble(g_boxLow  - slBuf, _Digits);
   sellSL = NormalizeDouble(g_boxHigh + slBuf, _Digits);
}

//==================================================================
// OCO: when one side fills, cancel the other pending
//==================================================================
void EnforceOCO()
{
   if(CountOpenPositions() > 0 && CountPendingOrders() > 0)
   {
      CancelAllPendings();
      PrintFormat("[%s] Position opened -> OCO cancelled remaining pending.", InpComment);
   }
}

//==================================================================
// Breakeven + ATR trailing for open positions
//==================================================================
void ManageOpenPositions()
{
   for(int i = PositionsTotal()-1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      long   type   = PositionGetInteger(POSITION_TYPE);
      double open   = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl     = PositionGetDouble(POSITION_SL);
      double tp     = PositionGetDouble(POSITION_TP);
      double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);

      // R distance = |open - original SL|. Approximate using current SL if BE not yet moved.
      double riskDist = MathAbs(open - sl);
      if(riskDist <= 0) continue;

      double newSL = sl;

      if(type == POSITION_TYPE_BUY)
      {
         double profit = bid - open;
         // breakeven
         if(InpUseBreakeven && profit >= riskDist * InpBE_TriggerR)
         {
            double be = open + Point2Price(InpBE_LockPoints);
            if(be > newSL) newSL = be;
         }
         // trailing
         if(InpUseTrailing)
         {
            double atr = GetATR();
            if(atr > 0)
            {
               double trail = bid - atr * InpTrailATRMult;
               if(trail > newSL) newSL = trail;
            }
         }
         if(newSL > sl + _Point)
            trade.PositionModify(tk, NormalizeDouble(newSL, _Digits), tp);
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double profit = open - ask;
         if(InpUseBreakeven && profit >= riskDist * InpBE_TriggerR)
         {
            double be = open - Point2Price(InpBE_LockPoints);
            if(be < newSL || newSL == 0) newSL = be;
         }
         if(InpUseTrailing)
         {
            double atr = GetATR();
            if(atr > 0)
            {
               double trail = ask + atr * InpTrailATRMult;
               if(trail < newSL || newSL == 0) newSL = trail;
            }
         }
         if(newSL < sl - _Point || (sl == 0 && newSL > 0))
            trade.PositionModify(tk, NormalizeDouble(newSL, _Digits), tp);
      }
   }
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
   g_dayStart       = DayStart(TimeCurrent());

   if(InpUseATRStop || InpUseTrailing)
   {
      g_atrHandle = iATR(_Symbol, PERIOD_M15, InpATRPeriod);
      if(g_atrHandle == INVALID_HANDLE)
         Print("[",InpComment,"] WARNING: ATR handle failed.");
   }

   PrintFormat("[%s] Init OK. Symbol=%s InitBalance=%.2f Risk=%.2f%%",
               InpComment, _Symbol, g_initBalance, InpRiskPercent);

   if(StringFind(_Symbol, "XAU") < 0)
      Print("[",InpComment,"] NOTE: this EA is tuned for XAUUSD (Gold). Current symbol: ", _Symbol);

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

   UpdateDayState();
   CheckGuards();

   if(g_haltAll) return;

   datetime now = TimeCurrent();

   // Force-close everything after the close-all hour (avoid overnight/weekend risk)
   if(now >= TodayAt(InpCloseAllHour, 0))
   {
      if(CountPendingOrders() > 0) CancelAllPendings();
      if(CountOpenPositions() > 0) CloseAllPositions();
      return;
   }

   BuildBox();

   if(!g_haltDay)
      PlaceBreakoutOrders();

   EnforceOCO();
   ManageOpenPositions();

   // Cancel pendings once trade window closes
   if(now >= TodayAt(InpTradeEndHour, 0) && CountPendingOrders() > 0)
      CancelAllPendings();
}

//==================================================================
// Count a new trade when a position opens (transaction hook)
//==================================================================
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult  &result)
{
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      if(HistoryDealSelect(trans.deal))
      {
         long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
         long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
         string dsym = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
         if(entry == DEAL_ENTRY_IN && magic == InpMagic && dsym == _Symbol)
            g_tradesToday++;
      }
   }
}
//+------------------------------------------------------------------+
