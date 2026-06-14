//+------------------------------------------------------------------+
//|                                   FTMO_CRT_QT_Visual.mq5          |
//|   Companion indicator for the CRT + Quarterly Theory EA.         |
//|   Draws on the chart:                                            |
//|     - The current C1 range (CRH / CRL) as a box + lines          |
//|     - The daily True Open line (00:00 EST)                       |
//|     - Vertical separators for the four daily quarters (Q1..Q4)   |
//|       with Q2/Q3 (the trading window) highlighted                |
//|                                                                  |
//|   Pure visual aid — places no trades. Match InpESTOffsetHours    |
//|   to the same value you use in the EA.                           |
//+------------------------------------------------------------------+
#property copyright "FTMO CRT + QT Visual"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_plots 0

input group "=== Match these to the EA ==="
input int    InpESTOffsetHours = 7;            // Server hours AHEAD of New York (EST)
input ENUM_TIMEFRAMES InpRangeTF = PERIOD_H1;  // C1 range timeframe

input group "=== Display ==="
input int    InpDaysToDraw     = 5;            // How many recent days of quarter lines to draw
input bool   InpShowRange      = true;         // Draw CRH/CRL box of the current range
input bool   InpShowTrueOpen   = true;         // Draw the daily True Open line
input bool   InpShowQuarters   = true;         // Draw Q1..Q4 vertical separators

input color  InpCRHColor       = clrTomato;    // CRH line
input color  InpCRLColor       = clrDodgerBlue;// CRL line
input color  InpBoxColor       = clrGray;      // Range box fill
input color  InpTrueOpenColor  = clrGold;      // True Open line
input color  InpQTradeColor    = clrLime;      // Q2/Q3 separators (trading window)
input color  InpQOtherColor    = clrDimGray;   // Q1/Q4 separators

const string PFX = "CRTQT_";   // object name prefix

//------------------------------------------------------------------
datetime ServerToEST(datetime t) { return t - (datetime)(InpESTOffsetHours*3600); }
datetime ESTToServer(datetime t) { return t + (datetime)(InpESTOffsetHours*3600); }

void DelOwn()
{
   int total = ObjectsTotal(0, -1, -1);
   for(int i = total-1; i >= 0; i--)
   {
      string nm = ObjectName(0, i, -1, -1);
      if(StringFind(nm, PFX) == 0) ObjectDelete(0, nm);
   }
}

void HLine(string id, datetime t1, datetime t2, double price, color col, int style, int width, string text)
{
   string nm = PFX + id;
   if(ObjectFind(0, nm) < 0)
      ObjectCreate(0, nm, OBJ_TREND, 0, t1, price, t2, price);
   else { ObjectMove(0, nm, 0, t1, price); ObjectMove(0, nm, 1, t2, price); }
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, style);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, width);
   ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nm, OBJPROP_BACK, false);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   if(text != "")
   {
      string ln = PFX + id + "_lbl";
      if(ObjectFind(0, ln) < 0) ObjectCreate(0, ln, OBJ_TEXT, 0, t2, price);
      else ObjectMove(0, ln, 0, t2, price);
      ObjectSetString(0, ln, OBJPROP_TEXT, text);
      ObjectSetInteger(0, ln, OBJPROP_COLOR, col);
      ObjectSetInteger(0, ln, OBJPROP_ANCHOR, ANCHOR_LEFT);
      ObjectSetInteger(0, ln, OBJPROP_SELECTABLE, false);
   }
}

void Box(string id, datetime t1, datetime t2, double p1, double p2, color col)
{
   string nm = PFX + id;
   if(ObjectFind(0, nm) < 0)
      ObjectCreate(0, nm, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   else { ObjectMove(0, nm, 0, t1, p1); ObjectMove(0, nm, 1, t2, p2); }
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetInteger(0, nm, OBJPROP_BACK, true);
   ObjectSetInteger(0, nm, OBJPROP_FILL, true);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
}

void VLine(string id, datetime t, color col, string text)
{
   string nm = PFX + id;
   if(ObjectFind(0, nm) < 0) ObjectCreate(0, nm, OBJ_VLINE, 0, t, 0);
   else ObjectMove(0, nm, 0, t, 0);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, col);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, nm, OBJPROP_BACK, true);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   ObjectSetString (0, nm, OBJPROP_TEXT, text);
}

//------------------------------------------------------------------
void DrawRange()
{
   if(!InpShowRange) return;
   double crh = iHigh(_Symbol, InpRangeTF, 1);
   double crl = iLow (_Symbol, InpRangeTF, 1);
   if(crh <= 0 || crl <= 0) return;
   datetime t1 = iTime(_Symbol, InpRangeTF, 1);
   datetime t2 = iTime(_Symbol, InpRangeTF, 0) + PeriodSeconds(InpRangeTF);

   Box("rangebox", t1, t2, crh, crl, InpBoxColor);
   HLine("CRH", t1, t2, crh, InpCRHColor, STYLE_SOLID, 2, "CRH "+DoubleToString(crh,_Digits));
   HLine("CRL", t1, t2, crl, InpCRLColor, STYLE_SOLID, 2, "CRL "+DoubleToString(crl,_Digits));
}

void DrawQuartersAndTrueOpen()
{
   datetime now = TimeCurrent();
   for(int d = 0; d < InpDaysToDraw; d++)
   {
      // EST midnight (start of Q2 / True Open) for day "d" back
      datetime estNow = ServerToEST(now) - (datetime)(d*86400);
      MqlDateTime e; TimeToStruct(estNow, e);
      e.hour = 0; e.min = 0; e.sec = 0;
      datetime estMidnight = StructToTime(e);   // 00:00 EST = start of Q2

      // Quarter boundaries in EST -> server
      datetime q2 = ESTToServer(estMidnight);                       // 00:00 EST
      datetime q3 = ESTToServer(estMidnight + 6*3600);              // 06:00 EST
      datetime q4 = ESTToServer(estMidnight + 12*3600);             // 12:00 EST
      datetime q1 = ESTToServer(estMidnight - 6*3600);              // 18:00 EST prev (start of Q1)

      string sfx = IntegerToString(d);
      if(InpShowQuarters)
      {
         VLine("Q1_"+sfx, q1, InpQOtherColor, "Q1");
         VLine("Q2_"+sfx, q2, InpQTradeColor, "Q2 (TrueOpen/London)");
         VLine("Q3_"+sfx, q3, InpQTradeColor, "Q3 (NY AM)");
         VLine("Q4_"+sfx, q4, InpQOtherColor, "Q4");
      }

      // True Open = price at 00:00 EST (= server time q2). Take the open of the bar there.
      if(InpShowTrueOpen)
      {
         int bar = iBarShift(_Symbol, PERIOD_M5, q2, false);
         if(bar >= 0)
         {
            double openPx = iOpen(_Symbol, PERIOD_M5, bar);
            datetime tEnd = q2 + 86400;
            HLine("TO_"+sfx, q2, tEnd, openPx, InpTrueOpenColor, STYLE_DASH, 1,
                  (d==0 ? "True Open" : ""));
         }
      }
   }
}

//------------------------------------------------------------------
int OnInit()
{
   IndicatorSetString(INDICATOR_SHORTNAME, "CRT+QT Visual");
   if(StringFind(_Symbol, "XAU") < 0)
      Print("[CRTQT Visual] NOTE: designed for XAUUSD. Current: ", _Symbol);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { DelOwn(); }

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[], const double &close[],
                const long &tick_volume[], const long &volume[], const int &spread[])
{
   DrawRange();
   DrawQuartersAndTrueOpen();
   ChartRedraw(0);
   return rates_total;
}
//+------------------------------------------------------------------+
