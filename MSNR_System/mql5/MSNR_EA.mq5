//+------------------------------------------------------------------+
//|  MSNR_EA.mq5  v2.3                                               |
//|  - Draw SL/TP/Entry/Levels on chart                              |
//|  - ChartScreenShot -> copy to Common\Files -> Python sends TG    |
//+------------------------------------------------------------------+
#property copyright "MSNR System"
#property version   "2.30"
#property strict
#include <Trade\Trade.mqh>
#include <Trade\AccountInfo.mqh>

input string SignalFilePath   = "C:\\MSNR_System\\signals\\signal.json";
input double MaxDailyLossPct  = 4.5;
input double MaxTotalDDPct    = 9.0;
input int    CheckIntervalSec = 5;
input int    MinConfluence    = 1;
input bool   AllowMultiPos    = false;
input bool   DrawOnChart      = true;
input int    ScreenshotWidth  = 1280;
input int    ScreenshotHeight = 720;

CTrade       Trade;
CAccountInfo Account;
double       g_DayStartBal   = 0;
datetime     g_LastDay       = 0;
string       g_LastTS        = "";
int          g_TickCount     = 0;

//+------------------------------------------------------------------+
int OnInit()
{
    Trade.SetExpertMagicNumber(20260607);
    Trade.SetDeviationInPoints(50);
    g_DayStartBal = Account.Balance();
    g_LastDay     = TimeCurrent();
    Print("MSNR EA v2.3 | DrawChart=", DrawOnChart);
    EventSetTimer(1);
    return INIT_SUCCEEDED;
}
void OnDeinit(const int reason)
{
    EventKillTimer();
    DeleteMSNRObjects();
}

//+------------------------------------------------------------------+
void OnTimer()
{
    ResetDailyIfNew();
    if(!PropFirmGuard()) { CloseAll("PropFirm limit"); return; }
    ManageTrail();

    g_TickCount++;
    if(g_TickCount < CheckIntervalSec) return;
    g_TickCount = 0;

    string action="", timestamp="";
    double entry=0, sl=0, tp=0, lot=0, trail_trigger=23.0, trail_lock=18.0;
    int    conf=0;
    // Nearby levels (up to 6)
    double lv_prices[6]; string lv_types[6]; int lv_cnt=0;

    if(!ReadSignal(action, entry, sl, tp, lot, conf,
                   trail_trigger, trail_lock, timestamp,
                   lv_prices, lv_types, lv_cnt)) return;
    if(timestamp == g_LastTS || action=="NONE" || action=="") return;
    if(conf < MinConfluence) return;
    if(!AllowMultiPos && PositionsTotal() > 0) return;

    lot = NormLot(lot);
    bool ok = false;
    if(action == "BUY")  ok = Trade.Buy (lot, Symbol(), 0, sl, tp, "MSNR_BUY");
    if(action == "SELL") ok = Trade.Sell(lot, Symbol(), 0, sl, tp, "MSNR_SELL");

    if(ok)
    {
        g_LastTS = timestamp;
        Print("Order OK | ", action, " lot=", lot, " sl=", sl, " tp=", tp);

        if(DrawOnChart)
        {
            double exec_price = (action=="BUY")
                ? SymbolInfoDouble(Symbol(), SYMBOL_ASK)
                : SymbolInfoDouble(Symbol(), SYMBOL_BID);
            DrawSetup(action, exec_price, sl, tp, lv_prices, lv_types, lv_cnt);
            Sleep(500);   // chart render
            TakeAndCopyScreenshot();
        }
    }
    else
        Print("Order FAIL: ", Trade.ResultRetcode(), " ", Trade.ResultRetcodeDescription());
}
void OnTick() {}

//+------------------------------------------------------------------+
//| Draw all setup objects on chart                                   |
//+------------------------------------------------------------------+
void DrawSetup(string action, double exec_price, double sl, double tp,
               double &lv_prices[], string &lv_types[], int lv_cnt)
{
    DeleteMSNRObjects();

    color c_entry = clrDodgerBlue;
    color c_sl    = clrRed;
    color c_tp    = clrLimeGreen;
    color c_a     = clrTomato;
    color c_v     = clrMediumSeaGreen;
    color c_gap   = clrGold;

    // ── Entry line ─────────────────────────────────────────────────
    DrawHLine("MSNR_Entry", exec_price, c_entry, STYLE_SOLID, 2);
    DrawText("MSNR_Entry_Lbl", exec_price, "ENTRY " + DoubleToString(exec_price, 2),
             c_entry);

    // ── SL line ────────────────────────────────────────────────────
    DrawHLine("MSNR_SL", sl, c_sl, STYLE_DASH, 2);
    DrawText("MSNR_SL_Lbl", sl,
             "SL " + DoubleToString(sl, 2) + "  (-$18)", c_sl);

    // ── TP line ────────────────────────────────────────────────────
    DrawHLine("MSNR_TP", tp, c_tp, STYLE_DASH, 2);
    double rr = MathAbs(tp - exec_price) / 18.0;
    DrawText("MSNR_TP_Lbl", tp,
             "TP " + DoubleToString(tp, 2) +
             "  RR " + DoubleToString(rr, 1) + ":1", c_tp);

    // ── SL/TP zone rectangle ──────────────────────────────────────
    datetime t0 = iTime(Symbol(), PERIOD_CURRENT, 50);
    datetime t1 = iTime(Symbol(), PERIOD_CURRENT, 0) + PeriodSeconds(PERIOD_CURRENT)*10;
    // SL zone (danger)
    DrawRect("MSNR_SL_Zone", t0, exec_price, t1, sl,
             c_sl, 10);
    // TP zone (reward)
    DrawRect("MSNR_TP_Zone", t0, exec_price, t1, tp,
             c_tp, 10);

    // ── Nearby MSNR levels ─────────────────────────────────────────
    for(int i = 0; i < lv_cnt && i < 6; i++)
    {
        color lv_col = c_a;
        string lv_label = "A-Level";
        if(lv_types[i] == "V") { lv_col = c_v; lv_label = "V-Level"; }
        else if(lv_types[i] == "G") { lv_col = c_gap; lv_label = "Gap-SnR"; }

        string name     = "MSNR_LV_" + IntToString(i);
        string name_lbl = "MSNR_LV_L" + IntToString(i);
        DrawHLine(name, lv_prices[i], lv_col, STYLE_DOT, 1);
        DrawText(name_lbl, lv_prices[i],
                 lv_label + " " + DoubleToString(lv_prices[i], 2) + " (H1)",
                 lv_col);
    }

    ChartRedraw(0);
}

//+------------------------------------------------------------------+
void DrawHLine(string name, double price, color clr, ENUM_LINE_STYLE style, int width)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
    ObjectSetInteger(0, name, OBJPROP_COLOR,  clr);
    ObjectSetInteger(0, name, OBJPROP_STYLE,  style);
    ObjectSetInteger(0, name, OBJPROP_WIDTH,  width);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
    ObjectSetInteger(0, name, OBJPROP_HIDDEN, false);
}

void DrawText(string name, double price, string text, color clr)
{
    ObjectDelete(0, name);
    datetime t = iTime(Symbol(), PERIOD_CURRENT, 0) + PeriodSeconds(PERIOD_CURRENT)*2;
    ObjectCreate(0, name, OBJ_TEXT, 0, t, price);
    ObjectSetString(0, name, OBJPROP_TEXT, text);
    ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
    ObjectSetString(0, name, OBJPROP_FONT, "Arial Bold");
}

void DrawRect(string name, datetime t1, double p1, datetime t2, double p2,
              color clr, int alpha)
{
    ObjectDelete(0, name);
    ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
    ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
    ObjectSetInteger(0, name, OBJPROP_BACK,      true);
    ObjectSetInteger(0, name, OBJPROP_FILL,      true);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

void DeleteMSNRObjects()
{
    int total = ObjectsTotal(0);
    for(int i = total - 1; i >= 0; i--)
    {
        string name = ObjectName(0, i);
        if(StringFind(name, "MSNR_") == 0)
            ObjectDelete(0, name);
    }
}

//+------------------------------------------------------------------+
//| Screenshot + copy to Common Files                                 |
//| Python reads: C:\Users\durable1\AppData\Roaming\MetaQuotes\      |
//|               Terminal\Common\Files\msnr_chart.png               |
//+------------------------------------------------------------------+
void TakeAndCopyScreenshot()
{
    string fname = "msnr_chart.png";

    // Save to terminal sandbox
    if(!ChartScreenShot(0, fname, ScreenshotWidth, ScreenshotHeight, ALIGN_LEFT))
    {
        Print("ChartScreenShot failed: ", GetLastError());
        return;
    }
    Sleep(300);

    // Copy to Common\Files (Python reads from there)
    if(FileCopy(fname, 0, fname, FILE_COMMON))
        Print("Screenshot -> Common\\Files\\", fname);
    else
        Print("FileCopy to Common failed: ", GetLastError(),
              " (screenshot still in terminal sandbox)");
}

//+------------------------------------------------------------------+
bool ReadSignal(string &action, double &entry, double &sl, double &tp,
                double &lot, int &conf,
                double &trail_trigger, double &trail_lock, string &timestamp,
                double &lv_prices[], string &lv_types[], int &lv_cnt)
{
    int h = FileOpen(SignalFilePath,
                     FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ, '\n', CP_ACP);
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

    // Parse nearby levels: lv0_t, lv0_p, lv1_t, lv1_p, ...
    lv_cnt = (int)JSONDbl(content, "lv_cnt");
    if(lv_cnt > 6) lv_cnt = 6;
    for(int i = 0; i < lv_cnt; i++)
    {
        lv_types[i]  = JSONStr(content, "lv" + IntToString(i) + "_t");
        lv_prices[i] = JSONDbl(content, "lv" + IntToString(i) + "_p");
    }

    return (action != "" && action != "NONE");
}

//+------------------------------------------------------------------+
string JSONStr(const string &j, const string &k)
{
    string s = "\"" + k + "\": \"";
    int p = StringFind(j, s); if(p < 0) return "";
    p += StringLen(s);
    int e = StringFind(j, "\"", p); if(e < 0) return "";
    return StringSubstr(j, p, e - p);
}
double JSONDbl(const string &j, const string &k)
{
    string s = "\"" + k + "\": ";
    int p = StringFind(j, s); if(p < 0) return 0;
    p += StringLen(s);
    int e = p;
    while(e < StringLen(j)){ ushort c=StringGetCharacter(j,e);
        if(c==','||c=='\n'||c=='}')break; e++; }
    return StringToDouble(StringSubstr(j, p, e-p));
}

//+------------------------------------------------------------------+
void ManageTrail()
{
    for(int i = PositionsTotal()-1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(!PositionSelectByTicket(ticket)) continue;
        if(PositionGetInteger(POSITION_MAGIC) != 20260607) continue;

        double entry_px  = PositionGetDouble(POSITION_PRICE_OPEN);
        double cur_sl    = PositionGetDouble(POSITION_SL);
        double cur_tp    = PositionGetDouble(POSITION_TP);
        double cur_price = PositionGetDouble(POSITION_PRICE_CURRENT);
        long   pos_type  = PositionGetInteger(POSITION_TYPE);
        double trail_trigger = 23.0, trail_lock = 18.0;

        if(pos_type == POSITION_TYPE_BUY)
        {
            double profit = cur_price - entry_px;
            double target_sl = NormalizeDouble(entry_px + trail_lock, _Digits);
            if(profit >= trail_trigger && cur_sl < target_sl)
            {
                if(Trade.PositionModify(ticket, target_sl, cur_tp))
                {
                    Print("Trail 1R | BUY #", ticket, " SL->", target_sl);
                    // Update SL line on chart
                    if(DrawOnChart)
                    {
                        DrawHLine("MSNR_SL", target_sl, clrOrange, STYLE_DASH, 2);
                        DrawText("MSNR_SL_Lbl", target_sl,
                                 "SL (LOCKED 1R) " + DoubleToString(target_sl,2), clrOrange);
                        ChartRedraw(0);
                    }
                }
            }
        }
        else if(pos_type == POSITION_TYPE_SELL)
        {
            double profit = entry_px - cur_price;
            double target_sl = NormalizeDouble(entry_px - trail_lock, _Digits);
            if(profit >= trail_trigger && cur_sl > target_sl)
            {
                if(Trade.PositionModify(ticket, target_sl, cur_tp))
                {
                    Print("Trail 1R | SELL #", ticket, " SL->", target_sl);
                    if(DrawOnChart)
                    {
                        DrawHLine("MSNR_SL", target_sl, clrOrange, STYLE_DASH, 2);
                        DrawText("MSNR_SL_Lbl", target_sl,
                                 "SL (LOCKED 1R) " + DoubleToString(target_sl,2), clrOrange);
                        ChartRedraw(0);
                    }
                }
            }
        }
    }
}

bool PropFirmGuard()
{
    double eq=Account.Equity(), loss=g_DayStartBal-eq;
    if(g_DayStartBal>0 && (loss/g_DayStartBal)*100>=MaxDailyLossPct)
    { Print("DAILY LOSS LIMIT"); return false; }
    if(g_DayStartBal>0 && ((g_DayStartBal-eq)/g_DayStartBal)*100>=MaxTotalDDPct)
    { Print("MAX DD HIT"); return false; }
    return true;
}
void ResetDailyIfNew()
{
    MqlDateTime n,l;
    TimeToStruct(TimeCurrent(),n); TimeToStruct(g_LastDay,l);
    if(n.day!=l.day){ g_DayStartBal=Account.Balance(); g_LastDay=TimeCurrent();
                      Print("Daily reset | Base:",g_DayStartBal); }
}
void CloseAll(const string reason)
{
    for(int i=PositionsTotal()-1;i>=0;i--)
    { ulong t=PositionGetTicket(i);
      if(PositionSelectByTicket(t)) Trade.PositionClose(t); }
}
double NormLot(double lot)
{
    double mn=SymbolInfoDouble(Symbol(),SYMBOL_VOLUME_MIN);
    double mx=SymbolInfoDouble(Symbol(),SYMBOL_VOLUME_MAX);
    double st=SymbolInfoDouble(Symbol(),SYMBOL_VOLUME_STEP);
    lot=MathMax(MathMin(lot,mx),mn);
    return NormalizeDouble(MathRound(lot/st)*st,2);
}
