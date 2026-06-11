//+------------------------------------------------------------------+
//| XAU_SessionBreakout.mq5                                          |
//| Session-box breakout EA for XAUUSD, M15 chart.                   |
//|                                                                  |
//| Default config = "AsiaBO + D1 trend": box from previous day      |
//| 18:00-23:00 server (late NY), breakout traded 01:00-08:00 (Asia),|
//| only in the direction of the D1 SMA(50) trend.                   |
//| Backtest 2004-2025 (M15, spread $0.28): PF 1.08, maxDD -33%,     |
//| positive 2022/23/24/25. Edge is THIN - forward-test on demo      |
//| before risking money. See forex-ea-lab/README.md for full data.  |
//+------------------------------------------------------------------+
#property copyright "forex-ea-lab"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//--- session / box inputs (server time, MT standard GMT+2/+3)
input int    BoxStartHour       = 18;    // box start hour
input int    BoxEndHour         = 23;    // box end hour (exclusive)
input bool   BoxFromPreviousDay = true;  // box belongs to previous trading day
input int    TradeStartHour     = 1;     // entry window start
input int    TradeEndHour       = 8;     // entry window end (no new entries after)
input int    EODCloseHour       = 23;    // force-close hour
//--- strategy inputs
input double RiskPercent        = 1.0;   // % equity risked per trade
input double RRMultiple         = 2.0;   // take-profit in R multiples
input double MinBoxUSD          = 3.5;   // skip if box smaller ($)
input double MaxBoxPercent      = 1.5;   // skip if box > this % of price
input double BreakoutBufferUSD  = 0.10;  // entry buffer beyond box edge ($)
input bool   UseTrendFilter     = true;  // only trade with D1 trend
input int    TrendSMAPeriod     = 50;    // D1 SMA period
//--- safety
input int    MaxSpreadPoints    = 40;    // skip placing orders if spread wider
input long   MagicNumber        = 36901;

CTrade   trade;
int      g_smaHandle = INVALID_HANDLE;
datetime g_lastBar   = 0;
datetime g_ordersDay = 0;   // day we already placed orders for

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);
   if(UseTrendFilter)
     {
      g_smaHandle = iMA(_Symbol, PERIOD_D1, TrendSMAPeriod, 0, MODE_SMA, PRICE_CLOSE);
      if(g_smaHandle == INVALID_HANDLE)
         return INIT_FAILED;
     }
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_smaHandle != INVALID_HANDLE)
      IndicatorRelease(g_smaHandle);
  }

//+------------------------------------------------------------------+
bool NewBar()
  {
   datetime t = iTime(_Symbol, PERIOD_M15, 0);
   if(t == g_lastBar)
      return false;
   g_lastBar = t;
   return true;
  }

bool MyPositionExists()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk > 0 && PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         return true;
     }
   return false;
  }

void DeleteMyPendings()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk > 0 && OrderGetString(ORDER_SYMBOL) == _Symbol &&
         OrderGetInteger(ORDER_MAGIC) == MagicNumber)
         trade.OrderDelete(tk);
     }
  }

void CloseMyPositions()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk > 0 && PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         trade.PositionClose(tk);
     }
  }

//--- box of the relevant session; returns false if not enough bars
bool GetBox(double &hi, double &lo)
  {
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);
   datetime dayStart = TimeCurrent() - (now.hour * 3600 + now.min * 60 + now.sec);

   MqlRates rates[];
   int copied = CopyRates(_Symbol, PERIOD_M15, 0, 1200, rates); // ~12 days
   if(copied <= 0)
      return false;

   hi = 0.0;
   lo = 0.0;
   datetime boxDay = 0;   // trading day the box belongs to
   int      nbars  = 0;
   // CopyRates returns oldest->newest; walk newest->oldest
   for(int i = copied - 1; i >= 0; i--)
     {
      datetime t = rates[i].time;
      if(BoxFromPreviousDay && t >= dayStart)
         continue;                         // only bars before today
      if(!BoxFromPreviousDay && t < dayStart)
         break;                            // same-day box: stop at yesterday
      MqlDateTime bt;
      TimeToStruct(t, bt);
      if(bt.hour < BoxStartHour || bt.hour >= BoxEndHour)
         continue;
      datetime d = t - (bt.hour * 3600 + bt.min * 60 + bt.sec);
      if(boxDay == 0)
         boxDay = d;                       // newest qualifying day
      if(d != boxDay)
         break;                            // older day reached - done
      if(nbars == 0) { hi = rates[i].high; lo = rates[i].low; }
      else           { hi = MathMax(hi, rates[i].high); lo = MathMin(lo, rates[i].low); }
      nbars++;
     }
   int expected = (BoxEndHour - BoxStartHour) * 4;
   return (nbars >= (int)(expected * 0.7));
  }

int TrendDirection()   // +1 long-only, -1 short-only, 0 both/unknown
  {
   if(!UseTrendFilter)
      return 0;
   double sma[1];
   if(CopyBuffer(g_smaHandle, 0, 1, 1, sma) != 1)
      return 99;       // data not ready - trade nothing
   double prevClose = iClose(_Symbol, PERIOD_D1, 1);
   if(prevClose <= 0)
      return 99;
   return (prevClose > sma[0]) ? 1 : -1;
  }

double LotsForRisk(double slDistance)
  {
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0 || slDistance <= 0)
      return 0.0;
   double riskUSD    = AccountInfoDouble(ACCOUNT_EQUITY) * RiskPercent / 100.0;
   double lossPerLot = slDistance / tickSize * tickVal;
   double lots       = riskUSD / lossPerLot;
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   lots = MathFloor(lots / step) * step;
   if(lots < vmin)
      return 0.0;    // refuse to oversize risk on tiny accounts
   return MathMin(lots, vmax);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // OCO emulation: position open -> remove sibling pending order
   if(MyPositionExists())
      DeleteMyPendings();

   if(!NewBar())
      return;

   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);

   // end of day: flatten everything
   if(now.hour >= EODCloseHour || now.hour < TradeStartHour)
     {
      DeleteMyPendings();
      if(now.hour >= EODCloseHour)
         CloseMyPositions();
      return;
     }

   // entry window over: stop hunting, keep managing open position
   if(now.hour >= TradeEndHour)
     {
      if(!MyPositionExists())
         DeleteMyPendings();
      return;
     }

   // place this day's OCO stop orders once
   datetime today = TimeCurrent() - (now.hour * 3600 + now.min * 60 + now.sec);
   if(g_ordersDay == today || MyPositionExists())
      return;

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > MaxSpreadPoints)
      return;            // retry next bar while window is open

   double hi, lo;
   if(!GetBox(hi, lo))
      return;
   double box = hi - lo;
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(box < MinBoxUSD || box > price * MaxBoxPercent / 100.0)
     {
      g_ordersDay = today;   // box invalid for the whole day
      return;
     }

   int dir = TrendDirection();
   if(dir == 99)
      return;

   double buyLevel  = hi + BreakoutBufferUSD;
   double sellLevel = lo - BreakoutBufferUSD;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   bool placed = false;
   if((dir == 0 || dir == 1) && ask < buyLevel)
     {
      double sl  = lo;
      double tp  = buyLevel + RRMultiple * (buyLevel - sl);
      double lots = LotsForRisk(buyLevel - sl);
      if(lots > 0 && trade.BuyStop(lots, NormalizeDouble(buyLevel, _Digits), _Symbol,
                                   NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits)))
         placed = true;
     }
   if((dir == 0 || dir == -1) && bid > sellLevel)
     {
      double sl  = hi;
      double tp  = sellLevel - RRMultiple * (sl - sellLevel);
      double lots = LotsForRisk(sl - sellLevel);
      if(lots > 0 && trade.SellStop(lots, NormalizeDouble(sellLevel, _Digits), _Symbol,
                                    NormalizeDouble(sl, _Digits), NormalizeDouble(tp, _Digits)))
         placed = true;
     }
   if(placed)
      g_ordersDay = today;
  }
//+------------------------------------------------------------------+
