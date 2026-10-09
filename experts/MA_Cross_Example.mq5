//+------------------------------------------------------------------+
//|                                          MA_Cross_Example.mq5    |
//|  Minimal example EA used to show the universal workflow:         |
//|  python -m ubt port --mq5 experts/MA_Cross_Example.mq5 ...       |
//+------------------------------------------------------------------+
#property version "1.00"
#include <Trade\Trade.mqh>

input int            InpFastPeriod  = 12;        // Fast MA period
input int            InpSlowPeriod  = 48;        // Slow MA period
input ENUM_MA_METHOD InpMethod      = MODE_EMA;  // MA method
input double         InpLots        = 0.01;      // Lots
input int            InpStopLoss    = 40000;     // Stop loss (points, 0 = none)
input int            InpTakeProfit  = 80000;     // Take profit (points, 0 = none)
input bool           InpReverse     = true;      // Close and reverse on opposite cross
input long           InpMagic       = 1001;      // Magic number

CTrade   trade;
int      hFast   = INVALID_HANDLE;
int      hSlow   = INVALID_HANDLE;
datetime lastBar = 0;

int OnInit()
{
   if(InpFastPeriod >= InpSlowPeriod) return INIT_PARAMETERS_INCORRECT;
   hFast = iMA(_Symbol, _Period, InpFastPeriod, 0, InpMethod, PRICE_CLOSE);
   hSlow = iMA(_Symbol, _Period, InpSlowPeriod, 0, InpMethod, PRICE_CLOSE);
   if(hFast == INVALID_HANDLE || hSlow == INVALID_HANDLE) return INIT_FAILED;
   trade.SetExpertMagicNumber(InpMagic);
   return INIT_SUCCEEDED;
}

// true when this EA has a position; its direction is returned in 'type'
bool HasPosition(long &type)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol || PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      type = PositionGetInteger(POSITION_TYPE);
      return true;
   }
   return false;
}

void OnTick()
{
   datetime bar = iTime(_Symbol, _Period, 0);
   if(bar == lastBar) return;
   lastBar = bar;

   double f[], s[];
   ArraySetAsSeries(f, true);
   ArraySetAsSeries(s, true);
   if(CopyBuffer(hFast, 0, 1, 2, f) < 2 || CopyBuffer(hSlow, 0, 1, 2, s) < 2) return;
   bool crossUp = f[1] <= s[1] && f[0] > s[0];
   bool crossDn = f[1] >= s[1] && f[0] < s[0];

   long type = -1;
   bool has = HasPosition(type);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(crossUp)
   {
      if(has && type == POSITION_TYPE_SELL && InpReverse) { trade.PositionClose(_Symbol); has = false; }
      if(!has)
         trade.Buy(InpLots, _Symbol, ask,
                   InpStopLoss > 0 ? ask - InpStopLoss * _Point : 0,
                   InpTakeProfit > 0 ? ask + InpTakeProfit * _Point : 0, "MA up");
   }
   else if(crossDn)
   {
      if(has && type == POSITION_TYPE_BUY && InpReverse) { trade.PositionClose(_Symbol); has = false; }
      if(!has)
         trade.Sell(InpLots, _Symbol, bid,
                    InpStopLoss > 0 ? bid + InpStopLoss * _Point : 0,
                    InpTakeProfit > 0 ? bid - InpTakeProfit * _Point : 0, "MA down");
   }
}

double OnTester()
{
   double pf = TesterStatistics(STAT_PROFIT_FACTOR);
   double dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   return pf / MathMax(dd, 1.0);
}
