//+------------------------------------------------------------------+
//|  MSNR_EA.mq5  v2.1                                               |
//|  Trail to 1R: when profit >= $23, move SL to entry +/- $18       |
//+------------------------------------------------------------------+
#property copyright "MSNR System"
#property version   "2.10"
#property strict
#include <Trade\Trade.mqh>
#include <Trade\AccountInfo.mqh>

input string SignalFilePath   = "C:\\MSNR_System\\signals\\signal.json";
input double MaxDailyLossPct  = 4.5;
input double MaxTotalDDPct    = 9.0;
input int    CheckIntervalSec = 5;
input int    MinConfluence    = 1;
input bool   AllowMultiPos    = false;

CTrade       Trade;
CAccountInfo Account;
double       g_DayStartBal = 0;
datetime     g_LastDay     = 0;
string       g_LastTS      = "";
int          g_TickCount   = 0;

//+------------------------------------------------------------------+
int OnInit()
{
    Trade.SetExpertMagicNumber(20260607);
    Trade.SetDeviationInPoints(50);
    g_DayStartBal = Account.Balance();
    g_LastDay     = TimeCurrent();
    Print("MSNR EA v2.1 | Trail-to-1R logic | Balance: ", g_DayStartBal);
    EventSetTimer(1);
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
void OnTimer()
{
    ResetDailyIfNew();
    if(!PropFirmGuard()) { CloseAll("PropFirm limit"); return; }

    // Trail management — chay moi giay
    ManageTrail();

    g_TickCount++;
    if(g_TickCount < CheckIntervalSec) return;
    g_TickCount = 0;

    // Doc va xu ly signal
    string action = "", timestamp = "";
    double entry = 0, sl = 0, tp = 0, lot = 0;
    double trail_trigger = 23.0, trail_lock = 18.0;
    int    conf = 0;

    if(!ReadSignal(action, entry, sl, tp, lot, conf,
                   trail_trigger, trail_lock, timestamp)) return;
    if(timestamp == g_LastTS || action == "NONE" || action == "") return;
    if(conf < MinConfluence) return;
    if(!AllowMultiPos && PositionsTotal() > 0) return;

    lot = NormLot(lot);
    bool ok = false;
    if(action == "BUY")  ok = Trade.Buy (lot, Symbol(), 0, sl, tp, "MSNR_BUY");
    if(action == "SELL") ok = Trade.Sell(lot, Symbol(), 0, sl, tp, "MSNR_SELL");

    if(ok)
    {
        g_LastTS = timestamp;
        Print("Order OK | ", action, " lot=", lot,
              " sl=", sl, " tp=", tp,
              " trail_trigger=$", trail_trigger,
              " trail_lock=$", trail_lock);
    }
    else
        Print("Order FAIL: ", Trade.ResultRetcode(), " ",
              Trade.ResultRetcodeDescription());
}

void OnTick() { /* intentional empty — logic in OnTimer */ }

//+------------------------------------------------------------------+
//| Trail to 1R Management                                           |
//| BUY : when (bid - entry) >= trail_trigger → move SL = entry + lock|
//| SELL: when (entry - bid) >= trail_trigger → move SL = entry - lock|
//+------------------------------------------------------------------+
void ManageTrail()
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(!PositionSelectByTicket(ticket))       continue;
        if(PositionGetInteger(POSITION_MAGIC) != 20260607) continue;

        double entry_px  = PositionGetDouble(POSITION_PRICE_OPEN);
        double cur_sl    = PositionGetDouble(POSITION_SL);
        double cur_tp    = PositionGetDouble(POSITION_TP);
        double cur_price = PositionGetDouble(POSITION_PRICE_CURRENT);
        long   pos_type  = PositionGetInteger(POSITION_TYPE);

        // Default values — EA uses these if signal not re-read
        double trail_trigger = 23.0;
        double trail_lock    = 18.0;

        if(pos_type == POSITION_TYPE_BUY)
        {
            double profit_pts = cur_price - entry_px;
            // Target SL = entry + trail_lock (lock 1R)
            double target_sl = NormalizeDouble(entry_px + trail_lock, _Digits);
            // Activate only once: when profit >= trigger AND current SL < target
            if(profit_pts >= trail_trigger && cur_sl < target_sl)
            {
                if(Trade.PositionModify(ticket, target_sl, cur_tp))
                    Print("Trail 1R | BUY #", ticket,
                          " profit=+", DoubleToString(profit_pts, 2),
                          " SL: ", DoubleToString(cur_sl, 2),
                          " -> ", DoubleToString(target_sl, 2));
            }
        }
        else if(pos_type == POSITION_TYPE_SELL)
        {
            double profit_pts = entry_px - cur_price;
            // Target SL = entry - trail_lock (lock 1R)
            double target_sl = NormalizeDouble(entry_px - trail_lock, _Digits);
            // Activate only once: when profit >= trigger AND current SL > target
            if(profit_pts >= trail_trigger && cur_sl > target_sl)
            {
                if(Trade.PositionModify(ticket, target_sl, cur_tp))
                    Print("Trail 1R | SELL #", ticket,
                          " profit=+", DoubleToString(profit_pts, 2),
                          " SL: ", DoubleToString(cur_sl, 2),
                          " -> ", DoubleToString(target_sl, 2));
            }
        }
    }
}

//+------------------------------------------------------------------+
bool ReadSignal(string &action, double &entry, double &sl, double &tp,
                double &lot, int &conf,
                double &trail_trigger, double &trail_lock,
                string &timestamp)
{
    int h = FileOpen(SignalFilePath,
                     FILE_READ | FILE_TXT | FILE_ANSI | FILE_SHARE_READ,
                     '\n', CP_ACP);
    if(h == INVALID_HANDLE) return false;
    string content = "";
    while(!FileIsEnding(h)) content += FileReadString(h);
    FileClose(h);

    action        = JSONStr(content, "action");
    entry         = JSONDbl(content, "entry");
    sl            = JSONDbl(content, "sl");
    tp            = JSONDbl(content, "tp");
    lot           = JSONDbl(content, "lot");
    conf          = (int)JSONDbl(content, "confluence");
    trail_trigger = JSONDbl(content, "trail_trigger");
    trail_lock    = JSONDbl(content, "trail_lock_usd");
    timestamp     = JSONStr(content, "timestamp");

    if(trail_trigger <= 0) trail_trigger = 23.0;
    if(trail_lock    <= 0) trail_lock    = 18.0;

    return (action != "" && action != "NONE");
}

//+------------------------------------------------------------------+
string JSONStr(const string &j, const string &k)
{
    string s = "\"" + k + "\": \"";
    int p = StringFind(j, s);
    if(p < 0) return "";
    p += StringLen(s);
    int e = StringFind(j, "\"", p);
    if(e < 0) return "";
    return StringSubstr(j, p, e - p);
}

double JSONDbl(const string &j, const string &k)
{
    string s = "\"" + k + "\": ";
    int p = StringFind(j, s);
    if(p < 0) return 0;
    p += StringLen(s);
    int e = p;
    while(e < StringLen(j))
    {
        ushort c = StringGetCharacter(j, e);
        if(c == ',' || c == '\n' || c == '}') break;
        e++;
    }
    return StringToDouble(StringSubstr(j, p, e - p));
}

//+------------------------------------------------------------------+
bool PropFirmGuard()
{
    double eq   = Account.Equity();
    double loss = g_DayStartBal - eq;
    if(g_DayStartBal > 0 && (loss / g_DayStartBal) * 100 >= MaxDailyLossPct)
    { Print("DAILY LOSS LIMIT HIT"); return false; }
    if(g_DayStartBal > 0 && ((g_DayStartBal - eq) / g_DayStartBal) * 100 >= MaxTotalDDPct)
    { Print("MAX DD HIT"); return false; }
    return true;
}

void ResetDailyIfNew()
{
    MqlDateTime n, l;
    TimeToStruct(TimeCurrent(), n);
    TimeToStruct(g_LastDay, l);
    if(n.day != l.day)
    {
        g_DayStartBal = Account.Balance();
        g_LastDay     = TimeCurrent();
        Print("Daily reset | Base: ", g_DayStartBal);
    }
}

void CloseAll(const string reason)
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong t = PositionGetTicket(i);
        if(PositionSelectByTicket(t))
            Trade.PositionClose(t);
        Print("Closed #", t, " | ", reason);
    }
}

double NormLot(double lot)
{
    double mn = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MIN);
    double mx = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_MAX);
    double st = SymbolInfoDouble(Symbol(), SYMBOL_VOLUME_STEP);
    lot = MathMax(MathMin(lot, mx), mn);
    return NormalizeDouble(MathRound(lot / st) * st, 2);
}
