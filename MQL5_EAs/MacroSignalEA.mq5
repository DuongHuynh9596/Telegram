//+------------------------------------------------------------------+
//|                                             MacroSignalEA.mq5    |
//|                   Live Trading EA — Python Macro Signal Reader    |
//|                                                                   |
//|  Reads signal.json from MT5 Common Files folder every 30 sec.    |
//|  Executes BUY/SELL orders based on Python macro signal analyzer. |
//|  Writes current symbol to ea_symbol.txt for Python auto-detect.  |
//+------------------------------------------------------------------+
#property copyright   "MacroSignalEA"
#property link        ""
#property version     "1.10"
#property description "Live EA: reads Python macro signal from signal.json"

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| Input parameters                                                  |
//+------------------------------------------------------------------+
input double InpLotSize        = 0.01;      // Lot Size
input int    InpMinConfidence  = 60;        // Minimum Confidence (%)
input long   InpMagicNumber    = 20240101;  // Magic Number
input int    InpMaxPositions   = 1;         // Max open positions

//+------------------------------------------------------------------+
//| Constants                                                         |
//+------------------------------------------------------------------+
#define SIGNAL_FILE      "signal.json"
#define SYMBOL_FILE      "ea_symbol.txt"
#define READ_INTERVAL    30               // seconds between file polls
#define EA_TAG           "[MacroSignalEA]"

//+------------------------------------------------------------------+
//| Global state                                                      |
//+------------------------------------------------------------------+
CTrade   g_trade;
datetime g_lastSignalTime = 0;   // timestamp of last processed signal
datetime g_lastReadTime   = 0;   // wall-clock time of last file read

//+------------------------------------------------------------------+
//| Signal data container                                             |
//+------------------------------------------------------------------+
struct SignalData
{
   string   signal;      // "BUY" | "SELL" | "HOLD"
   int      confidence;  // 0-100
   double   entry;
   double   sl;
   double   tp;
   string   analysis;
   datetime timestamp;
   bool     valid;
};

//+------------------------------------------------------------------+
//| Trim leading and trailing whitespace (space / tab / CR / LF)     |
//+------------------------------------------------------------------+
string StrTrim(const string s)
{
   string r = s;
   int    len;

   // Leading whitespace
   while((len = StringLen(r)) > 0)
   {
      ushort c = StringGetCharacter(r, 0);
      if(c == ' ' || c == '\t' || c == '\r' || c == '\n')
         r = StringSubstr(r, 1);
      else
         break;
   }

   // Trailing whitespace
   while((len = StringLen(r)) > 0)
   {
      ushort c = StringGetCharacter(r, len - 1);
      if(c == ' ' || c == '\t' || c == '\r' || c == '\n')
         r = StringSubstr(r, 0, len - 1);
      else
         break;
   }

   return r;
}

//+------------------------------------------------------------------+
//| Extract value string for a given JSON key.                        |
//|  Handles both  "key": "string value"  and  "key": number/bool    |
//|  Correctly skips escaped quotes inside string values.             |
//+------------------------------------------------------------------+
string JsonGetValue(const string json, const string key)
{
   // Search for  "key"  in the JSON text
   string pattern = "\"" + key + "\"";
   int keyPos = StringFind(json, pattern);
   if(keyPos < 0)
      return "";

   // Find the colon that follows
   int colonPos = StringFind(json, ":", keyPos + StringLen(pattern));
   if(colonPos < 0)
      return "";

   int    cursor  = colonPos + 1;
   int    jsonLen = StringLen(json);

   // Skip whitespace after colon
   while(cursor < jsonLen)
   {
      ushort c = StringGetCharacter(json, cursor);
      if(c == ' ' || c == '\t' || c == '\r' || c == '\n')
         cursor++;
      else
         break;
   }
   if(cursor >= jsonLen)
      return "";

   ushort firstChar = StringGetCharacter(json, cursor);

   //--- Quoted string value
   if(firstChar == '"')
   {
      cursor++; // skip opening quote
      string value = "";
      while(cursor < jsonLen)
      {
         ushort ch = StringGetCharacter(json, cursor);
         if(ch == '\\')
         {
            // Escaped character — include the literal next char
            cursor++;
            if(cursor < jsonLen)
               value += StringSubstr(json, cursor, 1);
            cursor++;
            continue;
         }
         if(ch == '"')  // closing quote
            break;
         value += StringSubstr(json, cursor, 1);
         cursor++;
      }
      return value;
   }

   //--- Unquoted value: number, boolean, null
   string value = "";
   while(cursor < jsonLen)
   {
      ushort ch = StringGetCharacter(json, cursor);
      if(ch == ',' || ch == '}' || ch == ']' ||
         ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n')
         break;
      value += StringSubstr(json, cursor, 1);
      cursor++;
   }
   return StrTrim(value);
}

//+------------------------------------------------------------------+
//| Parse ISO-8601 timestamp  "YYYY-MM-DDTHH:MM:SS"  into datetime   |
//+------------------------------------------------------------------+
datetime ParseTimestamp(const string ts)
{
   // Minimum expected length: 19  ("2026-06-04T12:59:53")
   if(StringLen(ts) < 19)
      return 0;

   MqlDateTime mdt;
   mdt.year        = (int)StringToInteger(StringSubstr(ts,  0, 4));
   mdt.mon         = (int)StringToInteger(StringSubstr(ts,  5, 2));
   mdt.day         = (int)StringToInteger(StringSubstr(ts,  8, 2));
   mdt.hour        = (int)StringToInteger(StringSubstr(ts, 11, 2));
   mdt.min         = (int)StringToInteger(StringSubstr(ts, 14, 2));
   mdt.sec         = (int)StringToInteger(StringSubstr(ts, 17, 2));
   mdt.day_of_week = 0;
   mdt.day_of_year = 0;

   // Basic range validation
   if(mdt.year < 2000 || mdt.year > 2100)  return 0;
   if(mdt.mon  < 1    || mdt.mon  > 12)    return 0;
   if(mdt.day  < 1    || mdt.day  > 31)    return 0;
   if(mdt.hour > 23 || mdt.min > 59 || mdt.sec > 59) return 0;

   return StructToTime(mdt);
}

//+------------------------------------------------------------------+
//| Parse full signal.json text into a SignalData struct              |
//+------------------------------------------------------------------+
SignalData ParseSignalJson(const string json)
{
   SignalData sd;
   sd.valid      = false;
   sd.confidence = 0;
   sd.entry      = 0.0;
   sd.sl         = 0.0;
   sd.tp         = 0.0;
   sd.timestamp  = 0;
   sd.signal     = "";
   sd.analysis   = "";

   if(StringLen(json) < 10)
   {
      Print(EA_TAG, " JSON content too short to parse.");
      return sd;
   }

   // Extract all fields
   string sigStr    = StrTrim(JsonGetValue(json, "signal"));
   string confStr   = JsonGetValue(json, "confidence");
   string entryStr  = JsonGetValue(json, "entry");
   string slStr     = JsonGetValue(json, "sl");
   string tpStr     = JsonGetValue(json, "tp");
   string tsStr     = JsonGetValue(json, "timestamp");
   sd.analysis      = StrTrim(JsonGetValue(json, "analysis"));

   // Check required fields are non-empty
   if(StringLen(sigStr)   == 0 ||
      StringLen(confStr)  == 0 ||
      StringLen(entryStr) == 0 ||
      StringLen(slStr)    == 0 ||
      StringLen(tpStr)    == 0 ||
      StringLen(tsStr)    == 0)
   {
      Print(EA_TAG, " One or more required JSON fields missing.");
      Print(EA_TAG, " Raw JSON snippet: ", StringSubstr(json, 0, 200));
      return sd;
   }

   // Validate signal direction
   sigStr = StrTrim(sigStr);
   if(sigStr != "BUY" && sigStr != "SELL" && sigStr != "HOLD")
   {
      Print(EA_TAG, " Unknown signal value: '", sigStr, "'");
      return sd;
   }
   sd.signal = sigStr;

   // Convert numeric fields
   sd.confidence = (int)StringToInteger(confStr);
   sd.entry      = StringToDouble(entryStr);
   sd.sl         = StringToDouble(slStr);
   sd.tp         = StringToDouble(tpStr);

   // Parse timestamp
   sd.timestamp = ParseTimestamp(tsStr);
   if(sd.timestamp == 0)
   {
      Print(EA_TAG, " Failed to parse timestamp: '", tsStr, "'");
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
                         FILE_READ | FILE_TXT | FILE_COMMON |
                         FILE_SHARE_READ | FILE_SHARE_WRITE,
                         '\n');
   if(handle == INVALID_HANDLE)
   {
      int err = GetLastError();
      // ERR_FILE_CANNOT_OPEN (5004) is normal on startup — suppress it
      if(err != 5004)
         Print(EA_TAG, " Cannot open '", filename, "' — error: ", err);
      return false;
   }

   while(!FileIsEnding(handle))
      content += FileReadString(handle) + "\n";

   FileClose(handle);
   return true;
}

//+------------------------------------------------------------------+
//| Write a text file to MT5 Common Files folder (overwrite)         |
//+------------------------------------------------------------------+
bool WriteCommonFile(const string filename, const string content)
{
   int handle = FileOpen(filename,
                         FILE_WRITE | FILE_TXT | FILE_COMMON | FILE_SHARE_READ,
                         '\n');
   if(handle == INVALID_HANDLE)
   {
      Print(EA_TAG, " Cannot write '", filename, "' — error: ", GetLastError());
      return false;
   }
   FileWriteString(handle, content);
   FileClose(handle);
   return true;
}

//+------------------------------------------------------------------+
//| Count positions opened by this EA on the current symbol          |
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
//| Execute a BUY or SELL trade using values from the signal         |
//+------------------------------------------------------------------+
void ExecuteTrade(const SignalData &sd)
{
   int    digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double sl     = NormalizeDouble(sd.sl, digits);
   double tp     = NormalizeDouble(sd.tp, digits);

   if(sd.signal == "BUY")
   {
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      Print(EA_TAG, " Placing BUY  | Lot=", InpLotSize,
            " Entry≈", ask, " SL=", sl, " TP=", tp,
            " Confidence=", sd.confidence, "%");

      if(!g_trade.Buy(InpLotSize, _Symbol, ask, sl, tp, "MacroSignal"))
         Print(EA_TAG, " BUY FAILED  retcode=", g_trade.ResultRetcode(),
               " (", g_trade.ResultRetcodeDescription(), ")");
      else
         Print(EA_TAG, " BUY OK  ticket=", g_trade.ResultOrder());
   }
   else if(sd.signal == "SELL")
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      Print(EA_TAG, " Placing SELL | Lot=", InpLotSize,
            " Entry≈", bid, " SL=", sl, " TP=", tp,
            " Confidence=", sd.confidence, "%");

      if(!g_trade.Sell(InpLotSize, _Symbol, bid, sl, tp, "MacroSignal"))
         Print(EA_TAG, " SELL FAILED retcode=", g_trade.ResultRetcode(),
               " (", g_trade.ResultRetcodeDescription(), ")");
      else
         Print(EA_TAG, " SELL OK ticket=", g_trade.ResultOrder());
   }
}

//+------------------------------------------------------------------+
//| Write current symbol to ea_symbol.txt so Python can detect it   |
//+------------------------------------------------------------------+
void WriteSymbolFile()
{
   if(WriteCommonFile(SYMBOL_FILE, _Symbol))
      Print(EA_TAG, " Written ", SYMBOL_FILE, " -> ", _Symbol);
   else
      Print(EA_TAG, " WARNING: could not write ", SYMBOL_FILE);
}

//+------------------------------------------------------------------+
//| OnInit                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("=================================================");
   Print(EA_TAG, " v1.10 Initializing");
   Print(EA_TAG, " Symbol       : ", _Symbol);
   Print(EA_TAG, " LotSize      : ", InpLotSize);
   Print(EA_TAG, " MinConfidence: ", InpMinConfidence, "%");
   Print(EA_TAG, " MagicNumber  : ", InpMagicNumber);
   Print(EA_TAG, " MaxPositions : ", InpMaxPositions);
   Print(EA_TAG, " PollInterval : ", READ_INTERVAL, " sec");
   Print("=================================================");

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(30);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   g_trade.LogLevel(LOG_LEVEL_ERRORS);

   // Advertise current symbol to Python immediately
   WriteSymbolFile();

   // Force first read on next tick
   g_lastReadTime = 0;

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| OnDeinit                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print(EA_TAG, " Stopped. Reason code: ", reason);
}

//+------------------------------------------------------------------+
//| OnTick — main loop                                                |
//+------------------------------------------------------------------+
void OnTick()
{
   datetime now = TimeCurrent();

   // Throttle to READ_INTERVAL seconds
   if((int)(now - g_lastReadTime) < READ_INTERVAL)
      return;

   g_lastReadTime = now;

   //--- 1. Read signal.json
   string jsonContent;
   if(!ReadCommonFile(SIGNAL_FILE, jsonContent))
      return;

   //--- 2. Parse
   SignalData sd = ParseSignalJson(jsonContent);
   if(!sd.valid)
   {
      Print(EA_TAG, " Parse failed — skipping cycle.");
      return;
   }

   //--- 3. Skip if already processed this timestamp
   if(sd.timestamp == g_lastSignalTime)
      return;

   // Log the new signal
   Print("--------------------------------------------------");
   Print(EA_TAG, " New signal  @ ", TimeToString(sd.timestamp));
   Print(EA_TAG, " Direction   : ", sd.signal);
   Print(EA_TAG, " Confidence  : ", sd.confidence, "%");
   Print(EA_TAG, " Entry       : ", sd.entry);
   Print(EA_TAG, " SL          : ", sd.sl);
   Print(EA_TAG, " TP          : ", sd.tp);
   Print(EA_TAG, " Analysis    : ", sd.analysis);
   Print("--------------------------------------------------");

   // Mark as seen before any early return (prevents re-logging on next poll)
   g_lastSignalTime = sd.timestamp;

   //--- 4. HOLD — no trade
   if(sd.signal == "HOLD")
   {
      Print(EA_TAG, " Signal=HOLD → no action.");
      return;
   }

   //--- 5. Confidence gate
   if(sd.confidence < InpMinConfidence)
   {
      Print(EA_TAG, " Confidence ", sd.confidence,
            "% < minimum ", InpMinConfidence, "% → skipping.");
      return;
   }

   //--- 6. Position count gate
   int openCount = CountOpenPositions();
   if(openCount >= InpMaxPositions)
   {
      Print(EA_TAG, " Already ", openCount, " position(s) open, max=",
            InpMaxPositions, " → skipping.");
      return;
   }

   //--- 7. Basic price sanity (all prices must be positive)
   if(sd.entry <= 0.0 || sd.sl <= 0.0 || sd.tp <= 0.0)
   {
      Print(EA_TAG, " Price sanity check failed (entry/sl/tp must be > 0) → skipping.");
      return;
   }

   //--- 8. SL/TP direction sanity
   if(sd.signal == "BUY"  && sd.sl >= sd.entry)
   {
      Print(EA_TAG, " BUY sanity: SL(", sd.sl, ") >= Entry(", sd.entry, ") → skipping.");
      return;
   }
   if(sd.signal == "SELL" && sd.sl <= sd.entry)
   {
      Print(EA_TAG, " SELL sanity: SL(", sd.sl, ") <= Entry(", sd.entry, ") → skipping.");
      return;
   }

   //--- 9. Python handles all execution — EA is display/log only
   // ExecuteTrade(sd);
}

//+------------------------------------------------------------------+
//| OnTimer — kept as belt-and-suspenders fallback                   |
//+------------------------------------------------------------------+
void OnTimer()
{
   OnTick();
}
//+------------------------------------------------------------------+
