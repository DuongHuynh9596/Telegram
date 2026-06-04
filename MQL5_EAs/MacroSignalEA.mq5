//+------------------------------------------------------------------+
//|                                               MacroSignalEA.mq5  |
//|                    Live Trading EA - Python Macro Signal Reader   |
//|                                                                    |
//|  Reads signal.json from MT5 Common Files folder every 30 seconds. |
//|  Executes BUY/SELL orders based on Python macro signal analyzer.  |
//+------------------------------------------------------------------+
#property copyright   "Macro Signal EA"
#property link        ""
#property version     "1.00"
#property description "Live EA: reads Python macro signal from signal.json"
#property strict

#include <Trade\Trade.mqh>

//--- Input parameters
input double   InpLotSize       = 0.01;       // Lot Size
input int      InpMinConfidence = 60;         // Minimum Confidence (%)
input long     InpMagicNumber   = 20240101;   // Magic Number
input int      InpMaxPositions  = 1;          // Max open positions

//--- Global objects & state
CTrade         g_trade;
datetime       g_lastSignalTime = 0;          // Last processed signal timestamp
datetime       g_lastReadTime   = 0;          // Last file-read wall-clock time
const int      READ_INTERVAL_SEC = 30;        // Poll every 30 seconds

//--- Signal structure
struct SignalData
{
   string   signal;       // "BUY" | "SELL" | "HOLD"
   int      confidence;   // 0-100
   double   entry;
   double   sl;
   double   tp;
   string   analysis;
   datetime timestamp;
   bool     valid;        // parse succeeded
};

//+------------------------------------------------------------------+
//| Helper: trim leading/trailing whitespace from a string           |
//+------------------------------------------------------------------+
string StrTrim(const string s)
{
   string r = s;
   while(StringLen(r) > 0 && (StringGetCharacter(r, 0) == ' '  ||
                               StringGetCharacter(r, 0) == '\t' ||
                               StringGetCharacter(r, 0) == '\r' ||
                               StringGetCharacter(r, 0) == '\n'))
      r = StringSubstr(r, 1);

   while(StringLen(r) > 0 && (StringGetCharacter(r, StringLen(r)-1) == ' '  ||
                               StringGetCharacter(r, StringLen(r)-1) == '\t' ||
                               StringGetCharacter(r, StringLen(r)-1) == '\r' ||
                               StringGetCharacter(r, StringLen(r)-1) == '\n'))
      r = StringSubstr(r, 0, StringLen(r)-1);
   return r;
}

//+------------------------------------------------------------------+
//| Helper: extract raw value string for a given JSON key            |
//|  Handles both  "key": "value"  and  "key": number               |
//+------------------------------------------------------------------+
string JsonGetValue(const string json, const string key)
{
   // Build search pattern  "key":
   string pattern = "\"" + key + "\"";
   int keyPos = StringFind(json, pattern);
   if(keyPos < 0)
      return "";

   int colonPos = StringFind(json, ":", keyPos + StringLen(pattern));
   if(colonPos < 0)
      return "";

   // Skip whitespace after colon
   int cursor = colonPos + 1;
   int jsonLen = StringLen(json);
   while(cursor < jsonLen && (StringGetCharacter(json, cursor) == ' '  ||
                              StringGetCharacter(json, cursor) == '\t' ||
                              StringGetCharacter(json, cursor) == '\r' ||
                              StringGetCharacter(json, cursor) == '\n'))
      cursor++;

   if(cursor >= jsonLen)
      return "";

   ushort firstChar = StringGetCharacter(json, cursor);

   if(firstChar == '"')
   {
      // Quoted string value — find closing quote (skip escaped quotes)
      cursor++; // move past opening quote
      string value = "";
      while(cursor < jsonLen)
      {
         ushort ch = StringGetCharacter(json, cursor);
         if(ch == '\\')
         {
            // skip escaped char
            cursor++;
            if(cursor < jsonLen)
               value += StringSubstr(json, cursor, 1);
            cursor++;
            continue;
         }
         if(ch == '"')
            break;
         value += StringSubstr(json, cursor, 1);
         cursor++;
      }
      return value;
   }
   else
   {
      // Unquoted value (number, bool, null) — read until delimiter
      string value = "";
      while(cursor < jsonLen)
      {
         ushort ch = StringGetCharacter(json, cursor);
         if(ch == ',' || ch == '}' || ch == ']' ||
            ch == ' '  || ch == '\t' || ch == '\r' || ch == '\n')
            break;
         value += StringSubstr(json, cursor, 1);
         cursor++;
      }
      return StrTrim(value);
   }
}

//+------------------------------------------------------------------+
//| Parse "YYYY-MM-DDTHH:MM:SS" into datetime                        |
//+------------------------------------------------------------------+
datetime ParseTimestamp(const string ts)
{
   // Expected format: 2026-06-04T12:59:53
   if(StringLen(ts) < 19)
      return 0;

   int year   = (int)StringToInteger(StringSubstr(ts, 0,  4));
   int month  = (int)StringToInteger(StringSubstr(ts, 5,  2));
   int day    = (int)StringToInteger(StringSubstr(ts, 8,  2));
   int hour   = (int)StringToInteger(StringSubstr(ts, 11, 2));
   int minute = (int)StringToInteger(StringSubstr(ts, 14, 2));
   int second = (int)StringToInteger(StringSubstr(ts, 17, 2));

   MqlDateTime mdt;
   mdt.year   = year;
   mdt.mon    = month;
   mdt.day    = day;
   mdt.hour   = hour;
   mdt.min    = minute;
   mdt.sec    = second;
   mdt.day_of_week = 0;
   mdt.day_of_year = 0;

   return StructToTime(mdt);
}

//+------------------------------------------------------------------+
//| Parse full signal.json content into SignalData struct            |
//+------------------------------------------------------------------+
SignalData ParseSignalJson(const string json)
{
   SignalData sd;
   sd.valid = false;
   sd.confidence = 0;
   sd.entry = 0;
   sd.sl    = 0;
   sd.tp    = 0;
   sd.timestamp = 0;

   if(StringLen(json) < 10)
   {
      Print("[MacroSignalEA] JSON too short to parse.");
      return sd;
   }

   sd.signal    = StrTrim(JsonGetValue(json, "signal"));
   sd.analysis  = StrTrim(JsonGetValue(json, "analysis"));

   string confStr = JsonGetValue(json, "confidence");
   string entryStr = JsonGetValue(json, "entry");
   string slStr    = JsonGetValue(json, "sl");
   string tpStr    = JsonGetValue(json, "tp");
   string tsStr    = JsonGetValue(json, "timestamp");

   if(StringLen(confStr)  == 0 || StringLen(entryStr) == 0 ||
      StringLen(slStr)    == 0 || StringLen(tpStr)    == 0 ||
      StringLen(tsStr)    == 0 || StringLen(sd.signal) == 0)
   {
      Print("[MacroSignalEA] Failed to extract one or more JSON fields.");
      Print("[MacroSignalEA] Raw JSON: ", json);
      return sd;
   }

   sd.confidence = (int)StringToInteger(confStr);
   sd.entry      = StringToDouble(entryStr);
   sd.sl         = StringToDouble(slStr);
   sd.tp         = StringToDouble(tpStr);
   sd.timestamp  = ParseTimestamp(tsStr);

   if(sd.timestamp == 0)
   {
      Print("[MacroSignalEA] Failed to parse timestamp: ", tsStr);
      return sd;
   }

   // Validate signal direction
   if(sd.signal != "BUY" && sd.signal != "SELL" && sd.signal != "HOLD")
   {
      Print("[MacroSignalEA] Unknown signal value: ", sd.signal);
      return sd;
   }

   sd.valid = true;
   return sd;
}

//+------------------------------------------------------------------+
//| Read entire text file from MT5 Common Files folder               |
//+------------------------------------------------------------------+
bool ReadCommonFile(const string filename, string &content)
{
   content = "";
   int handle = FileOpen(filename,
                         FILE_READ | FILE_TXT | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE,
                         '\n');
   if(handle == INVALID_HANDLE)
   {
      int err = GetLastError();
      if(err != 5004) // 5004 = file not found — expected on startup
         Print("[MacroSignalEA] Cannot open '", filename, "', error: ", err);
      return false;
   }

   while(!FileIsEnding(handle))
      content += FileReadString(handle) + "\n";

   FileClose(handle);
   return true;
}

//+------------------------------------------------------------------+
//| Write a text file to MT5 Common Files folder                     |
//+------------------------------------------------------------------+
bool WriteCommonFile(const string filename, const string content)
{
   int handle = FileOpen(filename,
                         FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_SHARE_READ,
                         '\n');
   if(handle == INVALID_HANDLE)
   {
      Print("[MacroSignalEA] Cannot write '", filename, "', error: ", GetLastError());
      return false;
   }
   FileWriteString(handle, content);
   FileClose(handle);
   return true;
}

//+------------------------------------------------------------------+
//| Count positions opened by this EA (magic number)                 |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL)   == _Symbol &&
         PositionGetInteger(POSITION_MAGIC)   == InpMagicNumber)
         count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Execute a trade based on parsed signal                           |
//+------------------------------------------------------------------+
void ExecuteTrade(const SignalData &sd)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   if(sd.signal == "BUY")
   {
      double sl = NormalizeDouble(sd.sl,  digits);
      double tp = NormalizeDouble(sd.tp,  digits);
      Print("[MacroSignalEA] Placing BUY | Lot=", InpLotSize,
            " | SL=", sl, " | TP=", tp,
            " | Confidence=", sd.confidence, "%");
      if(!g_trade.Buy(InpLotSize, _Symbol, ask, sl, tp, "MacroSignal"))
         Print("[MacroSignalEA] BUY failed: ", g_trade.ResultRetcode(),
               " - ", g_trade.ResultRetcodeDescription());
      else
         Print("[MacroSignalEA] BUY opened OK, ticket=", g_trade.ResultOrder());
   }
   else if(sd.signal == "SELL")
   {
      double sl = NormalizeDouble(sd.sl,  digits);
      double tp = NormalizeDouble(sd.tp,  digits);
      Print("[MacroSignalEA] Placing SELL | Lot=", InpLotSize,
            " | SL=", sl, " | TP=", tp,
            " | Confidence=", sd.confidence, "%");
      if(!g_trade.Sell(InpLotSize, _Symbol, bid, sl, tp, "MacroSignal"))
         Print("[MacroSignalEA] SELL failed: ", g_trade.ResultRetcode(),
               " - ", g_trade.ResultRetcodeDescription());
      else
         Print("[MacroSignalEA] SELL opened OK, ticket=", g_trade.ResultOrder());
   }
}

//+------------------------------------------------------------------+
//| Write current symbol to ea_symbol.txt so Python can detect it   |
//+------------------------------------------------------------------+
void WriteSymbolFile()
{
   if(!WriteCommonFile("ea_symbol.txt", _Symbol))
      Print("[MacroSignalEA] Warning: could not write ea_symbol.txt");
   else
      Print("[MacroSignalEA] ea_symbol.txt updated: ", _Symbol);
}

//+------------------------------------------------------------------+
//| EA Initialization                                                 |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=================================================");
   Print("[MacroSignalEA] Initializing...");
   Print("[MacroSignalEA] Symbol       : ", _Symbol);
   Print("[MacroSignalEA] LotSize      : ", InpLotSize);
   Print("[MacroSignalEA] MinConfidence: ", InpMinConfidence, "%");
   Print("[MacroSignalEA] MagicNumber  : ", InpMagicNumber);
   Print("[MacroSignalEA] MaxPositions : ", InpMaxPositions);
   Print("[MacroSignalEA] Poll interval: ", READ_INTERVAL_SEC, " sec");
   Print("=================================================");

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(30);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   g_trade.LogLevel(LOG_LEVEL_ERRORS);

   // Write current symbol so Python can auto-detect
   WriteSymbolFile();

   // Trigger first read immediately
   g_lastReadTime = 0;

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| EA De-initialization                                              |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("[MacroSignalEA] Deinitializing. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| EA Tick Handler                                                   |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent();

   // Throttle: only read file every READ_INTERVAL_SEC seconds
   if((int)(now - g_lastReadTime) < READ_INTERVAL_SEC)
      return;

   g_lastReadTime = now;

   //--- Read signal.json from Common Files
   string jsonContent;
   if(!ReadCommonFile("signal.json", jsonContent))
      return; // file not ready yet

   //--- Parse JSON
   SignalData sd = ParseSignalJson(jsonContent);
   if(!sd.valid)
   {
      Print("[MacroSignalEA] Signal parse failed — skipping.");
      return;
   }

   //--- Skip if this is the same timestamp we already processed
   if(sd.timestamp == g_lastSignalTime)
   {
      // Uncomment below for verbose logging:
      // Print("[MacroSignalEA] Same timestamp (", TimeToString(sd.timestamp), "), skipping.");
      return;
   }

   Print("--------------------------------------------------");
   Print("[MacroSignalEA] New signal @ ", TimeToString(sd.timestamp));
   Print("[MacroSignalEA] Direction  : ", sd.signal);
   Print("[MacroSignalEA] Confidence : ", sd.confidence, "%");
   Print("[MacroSignalEA] Entry      : ", sd.entry);
   Print("[MacroSignalEA] SL         : ", sd.sl);
   Print("[MacroSignalEA] TP         : ", sd.tp);
   Print("[MacroSignalEA] Analysis   : ", sd.analysis);
   Print("--------------------------------------------------");

   // Mark timestamp as seen regardless of whether we trade
   g_lastSignalTime = sd.timestamp;

   //--- HOLD: do nothing
   if(sd.signal == "HOLD")
   {
      Print("[MacroSignalEA] Signal=HOLD, no action.");
      return;
   }

   //--- Confidence gate
   if(sd.confidence < InpMinConfidence)
   {
      Print("[MacroSignalEA] Confidence ", sd.confidence,
            "% < minimum ", InpMinConfidence, "%, skipping.");
      return;
   }

   //--- Position gate
   int openCount = CountOpenPositions();
   if(openCount >= InpMaxPositions)
   {
      Print("[MacroSignalEA] Already have ", openCount,
            " position(s), MaxPositions=", InpMaxPositions, ", skipping.");
      return;
   }

   //--- Basic price sanity check (entry, SL, TP must be positive)
   if(sd.entry <= 0 || sd.sl <= 0 || sd.tp <= 0)
   {
      Print("[MacroSignalEA] Invalid price values (entry/sl/tp <= 0), skipping.");
      return;
   }

   //--- Execute trade
   ExecuteTrade(sd);
}

//+------------------------------------------------------------------+
//| Timer handler (optional redundancy — not used by default)        |
//+------------------------------------------------------------------+
void OnTimer()
{
   OnTick();
}
//+------------------------------------------------------------------+
