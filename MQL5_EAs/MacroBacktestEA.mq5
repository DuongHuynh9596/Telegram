//+------------------------------------------------------------------+
//|                                           MacroBacktestEA.mq5    |
//|              Backtest EA - Simulated Macro Correlation Rules      |
//|                                                                    |
//|  Simulates XAUUSD macro logic using EMA20/EMA50 + RSI(14).       |
//|  Designed for MT5 Strategy Tester (Visual mode supported).        |
//|  No file I/O — runs purely on indicator signals.                  |
//+------------------------------------------------------------------+
#property copyright   "Macro Backtest EA"
#property link        ""
#property version     "1.00"
#property description "Backtest EA: EMA20/EMA50 + RSI macro correlation rules"
#property strict

#include <Trade\Trade.mqh>

//--- Input parameters
input double InpLotSize    = 0.01;     // Lot Size
input int    InpSL_Points  = 1500;     // Stop Loss in points
input int    InpTP_Points  = 3000;     // Take Profit in points
input long   InpMagicNumber = 20240102; // Magic Number

//--- Indicator handles
int g_hEMA20  = INVALID_HANDLE;
int g_hEMA50  = INVALID_HANDLE;
int g_hRSI    = INVALID_HANDLE;

//--- Trade object
CTrade g_trade;

//--- State tracking
datetime g_lastBarTime = 0;  // Time of last processed H1 bar

//+------------------------------------------------------------------+
//| EA Initialization                                                  |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=================================================");
   Print("[MacroBacktestEA] Initializing...");
   Print("[MacroBacktestEA] Symbol     : ", _Symbol);
   Print("[MacroBacktestEA] LotSize    : ", InpLotSize);
   Print("[MacroBacktestEA] SL_Points  : ", InpSL_Points);
   Print("[MacroBacktestEA] TP_Points  : ", InpTP_Points);
   Print("[MacroBacktestEA] Magic      : ", InpMagicNumber);
   Print("[MacroBacktestEA] Timeframe  : H1 bar logic");
   Print("=================================================");

   //--- Create indicator handles on H1 timeframe
   g_hEMA20 = iMA(_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   g_hEMA50 = iMA(_Symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   g_hRSI   = iRSI(_Symbol, PERIOD_H1, 14, PRICE_CLOSE);

   if(g_hEMA20 == INVALID_HANDLE)
   { Print("[MacroBacktestEA] ERROR: Failed to create EMA20 handle!"); return INIT_FAILED; }
   if(g_hEMA50 == INVALID_HANDLE)
   { Print("[MacroBacktestEA] ERROR: Failed to create EMA50 handle!"); return INIT_FAILED; }
   if(g_hRSI == INVALID_HANDLE)
   { Print("[MacroBacktestEA] ERROR: Failed to create RSI handle!");   return INIT_FAILED; }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(30);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   g_trade.LogLevel(LOG_LEVEL_ERRORS);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| EA De-initialization                                              |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_hEMA20 != INVALID_HANDLE) IndicatorRelease(g_hEMA20);
   if(g_hEMA50 != INVALID_HANDLE) IndicatorRelease(g_hEMA50);
   if(g_hRSI   != INVALID_HANDLE) IndicatorRelease(g_hRSI);
   Print("[MacroBacktestEA] Deinitializing. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Count open positions opened by this EA                           |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL)  == _Symbol &&
         PositionGetInteger(POSITION_MAGIC)  == InpMagicNumber)
         count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Fetch a single buffer value from an indicator handle             |
//|  Returns false if data is not yet ready                          |
//+------------------------------------------------------------------+
bool GetIndicatorValue(const int handle, const int bufferIdx,
                       const int shift, double &value)
{
   double buf[1];
   if(CopyBuffer(handle, bufferIdx, shift, 1, buf) != 1)
      return false;
   value = buf[0];
   return true;
}

//+------------------------------------------------------------------+
//| Open a BUY position                                               |
//+------------------------------------------------------------------+
void OpenBuy()
{
   double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   double sl = NormalizeDouble(ask - InpSL_Points * point, digits);
   double tp = NormalizeDouble(ask + InpTP_Points * point, digits);

   Print("[MacroBacktestEA] >>> BUY signal | Ask=", ask,
         " | SL=", sl, " | TP=", tp);

   if(!g_trade.Buy(InpLotSize, _Symbol, ask, sl, tp, "MacroBacktest"))
      Print("[MacroBacktestEA] BUY failed: ", g_trade.ResultRetcode(),
            " - ", g_trade.ResultRetcodeDescription());
   else
      Print("[MacroBacktestEA] BUY opened OK, ticket=", g_trade.ResultOrder());
}

//+------------------------------------------------------------------+
//| Open a SELL position                                              |
//+------------------------------------------------------------------+
void OpenSell()
{
   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   double sl = NormalizeDouble(bid + InpSL_Points * point, digits);
   double tp = NormalizeDouble(bid - InpTP_Points * point, digits);

   Print("[MacroBacktestEA] >>> SELL signal | Bid=", bid,
         " | SL=", sl, " | TP=", tp);

   if(!g_trade.Sell(InpLotSize, _Symbol, bid, sl, tp, "MacroBacktest"))
      Print("[MacroBacktestEA] SELL failed: ", g_trade.ResultRetcode(),
            " - ", g_trade.ResultRetcodeDescription());
   else
      Print("[MacroBacktestEA] SELL opened OK, ticket=", g_trade.ResultOrder());
}

//+------------------------------------------------------------------+
//| Main macro signal logic — called once per new H1 bar             |
//|                                                                    |
//|  XAUUSD Macro Correlation Rules:                                  |
//|  BUY  : EMA20 > EMA50 (uptrend)                                  |
//|          AND RSI(14) < 45 (recovering from oversold)             |
//|          AND Close > EMA50 (price above trend)                    |
//|                                                                    |
//|  SELL : EMA20 < EMA50 (downtrend)                                |
//|          AND RSI(14) > 55 (falling from overbought)              |
//|          AND Close < EMA50 (price below trend)                    |
//+------------------------------------------------------------------+
void ProcessBarSignal()
{
   //--- Retrieve indicator values on the CLOSED bar (shift=1)
   double ema20, ema50, rsi;

   if(!GetIndicatorValue(g_hEMA20, 0, 1, ema20))
   { Print("[MacroBacktestEA] EMA20 data not ready."); return; }

   if(!GetIndicatorValue(g_hEMA50, 0, 1, ema50))
   { Print("[MacroBacktestEA] EMA50 data not ready."); return; }

   if(!GetIndicatorValue(g_hRSI, 0, 1, rsi))
   { Print("[MacroBacktestEA] RSI data not ready."); return; }

   //--- Get close price of last completed bar (shift=1)
   double closePrev[1];
   if(CopyClose(_Symbol, PERIOD_H1, 1, 1, closePrev) != 1)
   { Print("[MacroBacktestEA] Close data not ready."); return; }
   double close = closePrev[0];

   Print("[MacroBacktestEA] Bar @ ", TimeToString(g_lastBarTime),
         " | EMA20=", DoubleToString(ema20, 2),
         " | EMA50=", DoubleToString(ema50, 2),
         " | RSI=",   DoubleToString(rsi,   2),
         " | Close=", DoubleToString(close, 2));

   //--- Only trade if no position is open
   if(CountOpenPositions() > 0)
   {
      Print("[MacroBacktestEA] Position already open — waiting for close.");
      return;
   }

   //--- BUY condition
   //    EMA20 > EMA50  (bullish crossover / uptrend)
   //    RSI < 45       (momentum recovering, not yet overbought)
   //    Close > EMA50  (price holding above mid-term trend)
   bool buyCondition  = (ema20 > ema50) && (rsi < 45.0) && (close > ema50);

   //--- SELL condition
   //    EMA20 < EMA50  (bearish crossover / downtrend)
   //    RSI > 55       (momentum falling, not yet oversold)
   //    Close < EMA50  (price holding below mid-term trend)
   bool sellCondition = (ema20 < ema50) && (rsi > 55.0) && (close < ema50);

   if(buyCondition)
   {
      Print("[MacroBacktestEA] BUY condition met: EMA20>EMA50, RSI<45, Close>EMA50");
      OpenBuy();
   }
   else if(sellCondition)
   {
      Print("[MacroBacktestEA] SELL condition met: EMA20<EMA50, RSI>55, Close<EMA50");
      OpenSell();
   }
   else
   {
      Print("[MacroBacktestEA] No signal this bar — conditions not met.");
   }
}

//+------------------------------------------------------------------+
//| EA Tick Handler                                                   |
//+------------------------------------------------------------------+
void OnTick()
{
   //--- Detect new H1 bar
   datetime currentBarTime = iTime(_Symbol, PERIOD_H1, 0);
   if(currentBarTime == 0)
      return; // data not ready

   if(currentBarTime == g_lastBarTime)
      return; // same bar, no action

   // New H1 bar detected
   g_lastBarTime = currentBarTime;

   ProcessBarSignal();
}
//+------------------------------------------------------------------+
