//+------------------------------------------------------------------+
//|                                         MacroBacktestEA.mq5      |
//|             Backtest EA — Simulated XAUUSD Macro Correlation      |
//|                                                                   |
//|  Simulates Python macro logic using EMA20/EMA50 + RSI(14).       |
//|  Runs purely on indicator signals — no file I/O required.        |
//|  Designed for MT5 Strategy Tester (Visual mode supported).       |
//|                                                                   |
//|  Entry logic (evaluated on the CLOSED H1 bar):                   |
//|   BUY  : EMA20 > EMA50  AND  RSI < 45  AND  Close > EMA50       |
//|   SELL : EMA20 < EMA50  AND  RSI > 55  AND  Close < EMA50       |
//+------------------------------------------------------------------+
#property copyright   "MacroBacktestEA"
#property link        ""
#property version     "1.10"
#property description "Backtest EA: EMA20/EMA50 + RSI macro correlation rules"

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| Input parameters                                                  |
//+------------------------------------------------------------------+
input double InpLotSize      = 0.01;       // Lot Size
input int    InpSL_Points    = 1500;       // Stop Loss (points)
input int    InpTP_Points    = 3000;       // Take Profit (points)
input long   InpMagicNumber  = 20240102;   // Magic Number

//+------------------------------------------------------------------+
//| Constants                                                         |
//+------------------------------------------------------------------+
#define EA_TAG   "[MacroBacktestEA]"

// Macro threshold values — mirror the Python analyzer logic
#define RSI_BUY_MAX   45.0   // RSI must be below this for BUY
#define RSI_SELL_MIN  55.0   // RSI must be above this for SELL

//+------------------------------------------------------------------+
//| Global state                                                      |
//+------------------------------------------------------------------+
CTrade g_trade;

int      g_hEMA20      = INVALID_HANDLE;
int      g_hEMA50      = INVALID_HANDLE;
int      g_hRSI        = INVALID_HANDLE;
datetime g_lastBarTime = 0;

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=================================================");
   Print(EA_TAG, " v1.10 Initializing");
   Print(EA_TAG, " Symbol      : ", _Symbol);
   Print(EA_TAG, " LotSize     : ", InpLotSize);
   Print(EA_TAG, " SL_Points   : ", InpSL_Points);
   Print(EA_TAG, " TP_Points   : ", InpTP_Points);
   Print(EA_TAG, " MagicNumber : ", InpMagicNumber);
   Print(EA_TAG, " Logic TF    : H1");
   Print(EA_TAG, " BUY  cond   : EMA20>EMA50, RSI<",  RSI_BUY_MAX,  ", Close>EMA50");
   Print(EA_TAG, " SELL cond   : EMA20<EMA50, RSI>",  RSI_SELL_MIN, ", Close<EMA50");
   Print("=================================================");

   // Create indicator handles on H1
   g_hEMA20 = iMA (_Symbol, PERIOD_H1, 20, 0, MODE_EMA, PRICE_CLOSE);
   g_hEMA50 = iMA (_Symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   g_hRSI   = iRSI(_Symbol, PERIOD_H1, 14,    PRICE_CLOSE);

   if(g_hEMA20 == INVALID_HANDLE)
   { Print(EA_TAG, " ERROR: EMA20 handle creation failed!"); return INIT_FAILED; }
   if(g_hEMA50 == INVALID_HANDLE)
   { Print(EA_TAG, " ERROR: EMA50 handle creation failed!"); return INIT_FAILED; }
   if(g_hRSI == INVALID_HANDLE)
   { Print(EA_TAG, " ERROR: RSI handle creation failed!");   return INIT_FAILED; }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(30);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   g_trade.LogLevel(LOG_LEVEL_ERRORS);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_hEMA20 != INVALID_HANDLE) { IndicatorRelease(g_hEMA20); g_hEMA20 = INVALID_HANDLE; }
   if(g_hEMA50 != INVALID_HANDLE) { IndicatorRelease(g_hEMA50); g_hEMA50 = INVALID_HANDLE; }
   if(g_hRSI   != INVALID_HANDLE) { IndicatorRelease(g_hRSI);   g_hRSI   = INVALID_HANDLE; }
   Print(EA_TAG, " Stopped. Reason code: ", reason);
}

//+------------------------------------------------------------------+
//| Copy a single value from an indicator buffer                      |
//|  shift=1 → last completed (closed) bar                           |
//+------------------------------------------------------------------+
bool GetIndicatorValue(const int handle, const int bufferIdx,
                       const int shift, double &value)
{
   double buf[1];
   if(CopyBuffer(handle, bufferIdx, shift, 1, buf) != 1)
      return false;
   value = buf[0];
   return (value != EMPTY_VALUE);
}

//+------------------------------------------------------------------+
//| Count live positions for this EA on the current symbol           |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetTicket(i) == 0) continue;
      if(PositionGetString(POSITION_SYMBOL)  == _Symbol &&
         PositionGetInteger(POSITION_MAGIC)  == InpMagicNumber)
         count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Open a BUY market order                                           |
//+------------------------------------------------------------------+
void OpenBuy()
{
   double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   double sl = NormalizeDouble(ask - InpSL_Points * point, digits);
   double tp = NormalizeDouble(ask + InpTP_Points * point, digits);

   Print(EA_TAG, " >>> BUY  Ask=", DoubleToString(ask, digits),
         " SL=", DoubleToString(sl, digits),
         " TP=", DoubleToString(tp, digits));

   if(!g_trade.Buy(InpLotSize, _Symbol, ask, sl, tp, "MacroBacktest"))
      Print(EA_TAG, " BUY FAILED retcode=", g_trade.ResultRetcode(),
            " (", g_trade.ResultRetcodeDescription(), ")");
   else
      Print(EA_TAG, " BUY OK ticket=", g_trade.ResultOrder());
}

//+------------------------------------------------------------------+
//| Open a SELL market order                                          |
//+------------------------------------------------------------------+
void OpenSell()
{
   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double point  = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   double sl = NormalizeDouble(bid + InpSL_Points * point, digits);
   double tp = NormalizeDouble(bid - InpTP_Points * point, digits);

   Print(EA_TAG, " >>> SELL Bid=", DoubleToString(bid, digits),
         " SL=", DoubleToString(sl, digits),
         " TP=", DoubleToString(tp, digits));

   if(!g_trade.Sell(InpLotSize, _Symbol, bid, sl, tp, "MacroBacktest"))
      Print(EA_TAG, " SELL FAILED retcode=", g_trade.ResultRetcode(),
            " (", g_trade.ResultRetcodeDescription(), ")");
   else
      Print(EA_TAG, " SELL OK ticket=", g_trade.ResultOrder());
}

//+------------------------------------------------------------------+
//| Core macro signal logic — executed once per new H1 bar           |
//|                                                                   |
//|  All indicator values read from shift=1 (last CLOSED bar) to     |
//|  avoid look-ahead bias in the Strategy Tester.                   |
//+------------------------------------------------------------------+
void ProcessBarSignal()
{
   //--- Fetch indicator values on the closed bar (shift = 1)
   double ema20, ema50, rsi;

   if(!GetIndicatorValue(g_hEMA20, 0, 1, ema20))
   { Print(EA_TAG, " EMA20 data not ready — skipping."); return; }

   if(!GetIndicatorValue(g_hEMA50, 0, 1, ema50))
   { Print(EA_TAG, " EMA50 data not ready — skipping."); return; }

   if(!GetIndicatorValue(g_hRSI, 0, 1, rsi))
   { Print(EA_TAG, " RSI data not ready — skipping."); return; }

   //--- Fetch close of the same closed bar
   double closeBuf[1];
   if(CopyClose(_Symbol, PERIOD_H1, 1, 1, closeBuf) != 1)
   { Print(EA_TAG, " Close data not ready — skipping."); return; }
   double closePrice = closeBuf[0];

   Print(EA_TAG, " H1 bar [", TimeToString(g_lastBarTime), "]",
         "  EMA20=", DoubleToString(ema20, 2),
         "  EMA50=", DoubleToString(ema50, 2),
         "  RSI=",   DoubleToString(rsi,   2),
         "  Close=", DoubleToString(closePrice, 2));

   //--- Only one position at a time
   if(CountOpenPositions() > 0)
   {
      Print(EA_TAG, " Position already open — holding.");
      return;
   }

   //--- BUY condition
   //  Macro rationale (mirrors Python analyzer):
   //    EMA20 > EMA50  → medium-term uptrend confirmed
   //    RSI   < 45     → momentum recovering but not yet overbought
   //    Close > EMA50  → price is above the trend baseline
   bool buyCondition = (ema20 > ema50)
                    && (rsi   < RSI_BUY_MAX)
                    && (closePrice > ema50);

   //--- SELL condition
   //  Macro rationale:
   //    EMA20 < EMA50  → medium-term downtrend confirmed
   //    RSI   > 55     → momentum rolling over but not yet oversold
   //    Close < EMA50  → price is below the trend baseline
   bool sellCondition = (ema20 < ema50)
                     && (rsi   > RSI_SELL_MIN)
                     && (closePrice < ema50);

   if(buyCondition)
   {
      Print(EA_TAG, " BUY  conditions met: EMA20>EMA50, RSI<",
            RSI_BUY_MAX, ", Close>EMA50");
      OpenBuy();
   }
   else if(sellCondition)
   {
      Print(EA_TAG, " SELL conditions met: EMA20<EMA50, RSI>",
            RSI_SELL_MIN, ", Close<EMA50");
      OpenSell();
   }
   else
   {
      Print(EA_TAG, " No signal this bar — conditions not met.");
   }
}

//+------------------------------------------------------------------+
//| OnTick — detect new H1 bar, then run signal logic once           |
//+------------------------------------------------------------------+
void OnTick()
{
   // iTime returns 0 when data is not yet ready (e.g. tester warm-up)
   datetime currentBarTime = iTime(_Symbol, PERIOD_H1, 0);
   if(currentBarTime == 0 || currentBarTime == g_lastBarTime)
      return;

   g_lastBarTime = currentBarTime;
   ProcessBarSignal();
}
//+------------------------------------------------------------------+
