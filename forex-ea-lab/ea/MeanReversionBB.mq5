//+------------------------------------------------------------------+
//| MeanReversionBB.mq5                                              |
//| Bollinger-band mean-reversion EA, H1 chart (FX range pairs).     |
//|                                                                  |
//| *** READ BEFORE USING ***                                        |
//| Backtested 2012-2022 across 8 pairs with realistic costs:        |
//| 6/8 pairs LOST money (EURGBP PF 0.78, EURCHF 0.59...);           |
//| only USDCHF showed PF 1.14 - possibly selection luck.            |
//| This EA is provided as a clean, risk-capped reference            |
//| implementation for FORWARD TESTING ON DEMO ONLY.                 |
//| Full results: forex-ea-lab/README.md                             |
//+------------------------------------------------------------------+
#property copyright "forex-ea-lab"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>

//--- signal inputs
input int    BBPeriod        = 20;
input double BBDeviation     = 2.0;
input int    RSIPeriod       = 14;
input double RSIBuyBelow     = 35.0;  // setup: RSI below this for longs
input double RSISellAbove    = 65.0;  // setup: RSI above this for shorts
input int    ADXPeriod       = 14;
input double ADXMax          = 25.0;  // regime filter: skip trends
input int    ATRPeriod       = 14;
input double ATRMultSL       = 1.5;   // stop-loss distance in ATR
input int    TimeStopBars    = 36;    // close after N bars regardless
input int    StartHour       = 7;     // entry window (server time)
input int    EndHour         = 20;
//--- risk / safety
input double RiskPercent     = 1.0;   // % equity risked per trade
input int    MaxSpreadPoints = 25;
input long   MagicNumber     = 36902;

CTrade   trade;
int      hBB = INVALID_HANDLE, hRSI = INVALID_HANDLE;
int      hADX = INVALID_HANDLE, hATR = INVALID_HANDLE;
datetime g_lastBar = 0;
datetime g_entryBarTime = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(MagicNumber);
   hBB  = iBands(_Symbol, _Period, BBPeriod, 0, BBDeviation, PRICE_CLOSE);
   hRSI = iRSI(_Symbol, _Period, RSIPeriod, PRICE_CLOSE);
   hADX = iADX(_Symbol, _Period, ADXPeriod);
   hATR = iATR(_Symbol, _Period, ATRPeriod);
   if(hBB == INVALID_HANDLE || hRSI == INVALID_HANDLE ||
      hADX == INVALID_HANDLE || hATR == INVALID_HANDLE)
      return INIT_FAILED;
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   IndicatorRelease(hBB); IndicatorRelease(hRSI);
   IndicatorRelease(hADX); IndicatorRelease(hATR);
  }

bool NewBar()
  {
   datetime t = iTime(_Symbol, _Period, 0);
   if(t == g_lastBar)
      return false;
   g_lastBar = t;
   return true;
  }

bool SelectMyPosition()
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
      return 0.0;
   return MathMin(lots, vmax);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   if(!NewBar())
      return;

   // indicator values on the two most recent CLOSED bars (index 1, 2)
   double up[3], mid[3], lo[3], rsi[3], adx[2], atr[2];
   if(CopyBuffer(hBB, 1, 0, 3, up)  != 3) return;
   if(CopyBuffer(hBB, 0, 0, 3, mid) != 3) return;
   if(CopyBuffer(hBB, 2, 0, 3, lo)  != 3) return;
   if(CopyBuffer(hRSI, 0, 0, 3, rsi) != 3) return;
   if(CopyBuffer(hADX, 0, 0, 2, adx) != 2) return;
   if(CopyBuffer(hATR, 0, 0, 2, atr) != 2) return;
   // arrays are oldest->newest: [2]=current forming, [1]=last closed, [0]=before
   double c1 = iClose(_Symbol, _Period, 1);
   double c2 = iClose(_Symbol, _Period, 2);

   //--- manage open position -------------------------------------------------
   if(SelectMyPosition())
     {
      long   type   = PositionGetInteger(POSITION_TYPE);
      int    barsHeld = Bars(_Symbol, _Period, g_entryBarTime, TimeCurrent()) - 1;
      bool   exitNow = false;
      if(type == POSITION_TYPE_BUY  && c1 >= mid[1]) exitNow = true;
      if(type == POSITION_TYPE_SELL && c1 <= mid[1]) exitNow = true;
      if(barsHeld >= TimeStopBars) exitNow = true;
      if(exitNow)
         trade.PositionClose(_Symbol);
      return;
     }

   //--- look for a new signal ------------------------------------------------
   MqlDateTime now;
   TimeToStruct(TimeCurrent(), now);
   if(now.hour < StartHour || now.hour > EndHour)
      return;
   if(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > MaxSpreadPoints)
      return;
   if(adx[0] > ADXMax)        // adx[0] here = bar index 1 (last closed)
      return;

   // setup on bar2 (beyond band + RSI extreme), trigger on bar1 (back inside)
   int sig = 0;
   if(c2 < lo[0] && rsi[0] < RSIBuyBelow && c1 > lo[1])
      sig = 1;
   else if(c2 > up[0] && rsi[0] > RSISellAbove && c1 < up[1])
      sig = -1;
   if(sig == 0)
      return;

   double slDist = ATRMultSL * atr[0];
   double lots = LotsForRisk(slDist);
   if(lots <= 0)
      return;

   if(sig == 1)
     {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      if(trade.Buy(lots, _Symbol, 0.0, NormalizeDouble(ask - slDist, _Digits), 0.0))
         g_entryBarTime = iTime(_Symbol, _Period, 0);
     }
   else
     {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(trade.Sell(lots, _Symbol, 0.0, NormalizeDouble(bid + slDist, _Digits), 0.0))
         g_entryBarTime = iTime(_Symbol, _Period, 0);
     }
  }
//+------------------------------------------------------------------+
