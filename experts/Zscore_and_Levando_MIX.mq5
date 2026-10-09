//+------------------------------------------------------------------+
//|                                    Zscore and Levando MIX.mq5    |
//|                                                                  |
//|   TWO INDEPENDENT ENGINES IN ONE EXPERT ADVISOR                  |
//|                                                                  |
//|   ENGINE A : Grid Z-Score Mean Reversion v3.2                    |
//|              default  BTCUSD  M5                                 |
//|   ENGINE B : LeVanDo Cascade Multi-TF Same-Risk v4.10            |
//|              default  BTCUSD  M30 / H1 / H2 / H4                 |
//|                                                                  |
//|   Each engine has its OWN asset, timeframe(s), magic number,     |
//|   positions, orders and internal state. Neither engine reads or  |
//|   touches anything that belongs to the other one.                |
//|                                                                  |
//|   DXB TRADING / @TheMoneyMakerIND                                |
//+------------------------------------------------------------------+
#property copyright   "DXB TRADING / @TheMoneyMakerIND"
#property link        "https://t.me/TheMoneyMakerIND"
#property version     "1.10"
#property description "Zscore and Levando MIX"
#property description "Grid Z-Score MR v3.2  +  LeVanDo Cascade Multi-TF v4.10"
#property description "Grid: volatility based gapping + martingale position cap (OUT / HOLD)"
#property description "Two independent engines in one EA."
#property description "Each engine has its own asset, timeframe(s), magic and state."
#property description "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
#property description "Attach to ANY chart — engines use their own inputs"
#property description "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

//+------------------------------------------------------------------+
//| ENUMS (ENGINE A)                                                 |
//+------------------------------------------------------------------+
enum ENUM_GZ_LOT_MODE
{
   GZ_LOT_FIXED    = 0, // Fixed Lot
   GZ_LOT_RISK_PCT = 1  // Risk % of Equity (incl. unrealized PnL)
};

enum ENUM_GZ_TRAIL_SPEED
{
   GZ_TRAIL_SLOWEST = 0, // Slowest (very wide, very patient)
   GZ_TRAIL_SLOWER  = 1, // Slower (wide, patient)
   GZ_TRAIL_SLOW    = 2, // Slow (comfortable room)
   GZ_TRAIL_FAST    = 3, // Fast (tight, reactive)
   GZ_TRAIL_FASTER  = 4, // Faster (very tight)
   GZ_TRAIL_FASTEST = 5  // Fastest (hell-fast, nearest tick possible)
};

enum ENUM_GZ_GAP_MODE
{
   GZ_GAP_FIXED_PCT  = 0, // Fixed % of price (original)
   GZ_GAP_VOLATILITY = 1  // Volatility based (ATR)
};

enum ENUM_GZ_CAP_ACTION
{
   GZ_CAP_OUT  = 0, // OUT  - close the whole basket
   GZ_CAP_HOLD = 1  // HOLD - keep positions, stop adding
};

//+------------------------------------------------------------------+
//| INPUTS — ENGINE A : GRID Z-SCORE  (defaults = "btcusd m5 grid")   |
//+------------------------------------------------------------------+
input group "══════ [A] GRID Z-SCORE — ASSET & TIMEFRAME ══════"
input bool                InpGZ_Enable         = true;          // [A] Enable Grid Z-Score engine
input string              InpGZ_Symbol         = "BTCUSD";      // [A] Asset name (blank = chart symbol)
input ENUM_TIMEFRAMES     InpGZ_Timeframe      = PERIOD_M5;     // [A] Timeframe

input group "══════ [A] GRID Z-SCORE — MEAN REVERSION ══════"
input int                 InpGZ_ZscorePeriod   = 14;            // [A] Z-Score Lookback Period
input double              InpGZ_ZscoreBuyTh    = -0.3;          // [A] Z-Score Buy Threshold (aggressive)
input double              InpGZ_ZscoreSellTh   = 0.3;           // [A] Z-Score Sell Threshold (aggressive)

input group "══════ [A] GRID Z-SCORE — GRID SETTINGS ══════"
input double              InpGZ_GridThreshold  = 0.04;          // [A] Grid Threshold % of price (minimum step in volatility mode)
input int                 InpGZ_GridChainSize  = 7;             // [A] Grid Chain Size (before gap reset)
input double              InpGZ_GapResetPct    = 0.1;           // [A] Gap % to allow next chain (minimum gap in volatility mode)
input bool                InpGZ_AllowBothSides = false;         // [A] Allow Buy & Sell grids simultaneously

input group "══════ [A] GRID Z-SCORE — VOLATILITY BASED GAPPING ══════"
input ENUM_GZ_GAP_MODE    InpGZ_GapMode        = GZ_GAP_VOLATILITY; // [A] Gapping mode
input int                 InpGZ_VolATRPeriod   = 14;            // [A] ATR period (on the engine timeframe)
input double              InpGZ_VolStepMult    = 1.0;           // [A] Grid step  = ATR x this
input double              InpGZ_VolGapMult     = 2.5;           // [A] Chain gap  = ATR x this

input group "══════ [A] GRID Z-SCORE — MARTINGALE POSITION CAP ══════"
input int                 InpGZ_MaxPositions   = 7;             // [A] Max open positions per side (0 = no cap)
input ENUM_GZ_CAP_ACTION  InpGZ_CapAction      = GZ_CAP_OUT;    // [A] At the cap, when the next level is hit

input group "══════ [A] GRID Z-SCORE — LOT SIZING ══════"
input ENUM_GZ_LOT_MODE    InpGZ_LotMode        = GZ_LOT_FIXED;  // [A] Lot Mode
input double              InpGZ_FixedLot       = 0.01;          // [A] Base Lot (Fixed mode)
input double              InpGZ_RiskPct        = 0.1;           // [A] Risk % of Equity (Risk mode)
input double              InpGZ_MartingaleMult = 2.0;           // [A] Martingale Multiplier

input group "══════ [A] GRID Z-SCORE — AI SL TRAILING ══════"
input ENUM_GZ_TRAIL_SPEED InpGZ_TrailFirst     = GZ_TRAIL_SLOW; // [A] 1st Trade Trail Speed
input ENUM_GZ_TRAIL_SPEED InpGZ_TrailGrid      = GZ_TRAIL_FAST; // [A] Grid (2+ trades) Trail Speed

input group "══════ [A] GRID Z-SCORE — GENERAL ══════"
input int                 InpGZ_Magic          = 774400;        // [A] Magic Number
input int                 InpGZ_Slippage       = 30;            // [A] Max Slippage (points)
input string              InpGZ_Comment        = "GridZScore";  // [A] Order Comment
input bool                InpGZ_ShowOnChart    = true;          // [A] Show dashboard (top-left)

//+------------------------------------------------------------------+
//| INPUTS — ENGINE B : LEVANDO CASCADE  (defaults = "m30 btc")       |
//+------------------------------------------------------------------+
input group "══════ [B] LEVANDO — ASSET & TIMEFRAMES ══════"
input bool     InpLV_Enable                = true;              // [B] Enable LeVanDo engine
input string   InpLV_Symbol                = "BTCUSD";          // [B] Asset name (blank = chart symbol)
input string   InpLV_Timeframes            = "30,60,120,240";   // [B] Timeframes in minutes (30=M30, 60=H1, 120=H2, 240=H4)

input group "══════ [B] LEVANDO — GENERAL ══════"
input int      InpLV_MagicNumber           = 202412;            // [B] Magic Number
input string   InpLV_Comment               = "LEVANDO";         // [B] Order Comment

input group "══════ [B] LEVANDO — RISK & LOT ANCHOR (SAME RISK) ══════"
input double   InpLV_RiskPercent           = 1.0;               // [B] % of equity risked on the FIRST (anchor) trade

input group "══════ [B] LEVANDO — CASCADE ATR ══════"
input int      InpLV_ATRPeriod             = 14;                // [B] ATR Period
input bool     InpLV_UseStaticATR          = true;              // [B] true = freeze entry ATR; false = live ATR of firing TF

input group "══════ [B] LEVANDO — CASCADE & RECOVERY ══════"
input double   InpLV_RecoveryGapPct        = 0.0;               // [B] 0 = recovery OFF. >0 = gap % of init-SL to average in
input bool     InpLV_EnableTrail           = false;             // [B] Enable trailing stop
input bool     InpLV_OverwriteSLTP         = true;              // [B] Overwrite SL/TP on adopted trades

input group "══════ [B] LEVANDO — BREAKEVEN ══════"
input bool     InpLV_EnableFirstBE         = false;             // [B] Breakeven on first trade
input bool     InpLV_EnableEveryCascadeBE  = false;             // [B] Breakeven on every cascade level
input double   InpLV_BEThresholdPct        = 40.0;              // [B] Breakeven threshold %

input group "══════ [B] LEVANDO — SAFETY & TECHNICAL ══════"
input int      InpLV_MaxRetry              = 20;                // [B] Max retries
input int      InpLV_RetryDelayMs          = 50;                // [B] Retry delay (ms)
input bool     InpLV_ShowOnChart           = true;              // [B] Show dashboard (bottom-left)
input string   InpLV_FileName              = "LVD_RiskAnchor";  // [B] Anchor persistence file
input bool     InpLV_ResetAnchor           = false;             // [B] Wipe stored anchor on next init


// ╔═══════════════════════════════════════════════════════════════════╗
// ║                       SHARED HELPERS                              ║
// ╚═══════════════════════════════════════════════════════════════════╝

string TFToText(ENUM_TIMEFRAMES tf)
{
   string s = EnumToString(tf);
   StringReplace(s, "PERIOD_", "");
   return s;
}

void MixFail(string msg)
{
   Print("Zscore and Levando MIX ERROR: ", msg);
   Alert("Zscore and Levando MIX ERROR: ", msg);
}

// Resolve the asset an engine trades.
//   blank            -> chart symbol
//   exact name found -> that symbol (added to Market Watch)
//   not found, but the chart symbol contains the name (broker prefix/suffix,
//   e.g. input "BTCUSD" on a "BTCUSDm" chart) -> chart symbol
//   otherwise        -> fail, so the engine can never trade the wrong asset
bool ResolveSymbol(string requested, string tag, string &resolved)
{
   string s = requested;
   StringTrimLeft(s);
   StringTrimRight(s);

   if(StringLen(s) == 0) { resolved = _Symbol; return true; }
   if(SymbolSelect(s, true)) { resolved = s; return true; }

   string chartUp = _Symbol;
   string reqUp   = s;
   StringToUpper(chartUp);
   StringToUpper(reqUp);
   if(StringFind(chartUp, reqUp) >= 0)
   {
      resolved = _Symbol;
      Print("[", tag, "] asset '", s, "' not found at this broker — using chart symbol '", _Symbol, "'");
      return true;
   }

   MixFail("[" + tag + "] asset '" + s + "' does not exist at this broker. " +
             "Type the exact name from Market Watch, or leave it blank to use the chart symbol.");
   return false;
}

// True when a new quote arrived for 'sym' since the last call (used only for
// an engine whose asset is NOT the chart symbol, so it still runs tick-by-tick).
bool IsNewQuote(const string sym, long &lastMsc, double &lastBid, double &lastAsk)
{
   MqlTick t;
   if(!SymbolInfoTick(sym, t)) return false;
   if(t.time_msc == lastMsc && t.bid == lastBid && t.ask == lastAsk) return false;
   lastMsc = t.time_msc;
   lastBid = t.bid;
   lastAsk = t.ask;
   return true;
}

// Which engine is driven by the chart's OnTick and which by the timer.
bool   g_gzOnTimer = false;
bool   g_lvOnTimer = false;
long   g_gzQuoteMsc = 0;  double g_gzQuoteBid = 0, g_gzQuoteAsk = 0;
long   g_lvQuoteMsc = 0;  double g_lvQuoteBid = 0, g_lvQuoteAsk = 0;


// ╔═══════════════════════════════════════════════════════════════════╗
// ║                                                                   ║
// ║        ENGINE A — GRID Z-SCORE MEAN REVERSION v3.2                ║
// ║        Real SL Trailing | 6 AI Trail Modes                        ║
// ║        Guaranteed profit exit — SL never below BE                 ║
// ║                                                                   ║
// ╚═══════════════════════════════════════════════════════════════════╝

struct GZ_TrailConfig
{
   double triggerSpreads;
   double trailDistSpreads;
   double ratchetFraction;
   double minLockSpreads;
};

// Engine A context
string          g_gzSymbol        = "";
ENUM_TIMEFRAMES g_gzTF            = PERIOD_M5;
double          g_gzPoint         = 0;
int             g_gzDigits        = 0;

int      g_gzHandleMA      = INVALID_HANDLE;
int      g_gzHandleStd     = INVALID_HANDLE;
datetime g_gzLastBarTime   = 0;
int      g_gzTickCounter   = 0;
double   g_gzLastZ         = 0;
bool     g_gzHaveZ         = false;

// Trailing state per side
double   g_gzBuyPeakPrice    = 0;
double   g_gzSellPeakPrice   = DBL_MAX;
bool     g_gzBuyTrailActive  = false;
bool     g_gzSellTrailActive = false;
double   g_gzBuyTrailSL      = 0;
double   g_gzSellTrailSL     = 0;
double   g_gzBuyBE           = 0;
double   g_gzSellBE          = 0;

// Grid chain tracking
int      g_gzBuyChainCount   = 0;
int      g_gzSellChainCount  = 0;
bool     g_gzBuyInGap        = false;
bool     g_gzSellInGap       = false;
double   g_gzBuyGapAnchor    = 0;
double   g_gzSellGapAnchor   = 0;
int      g_gzBuyTotalOrders  = 0;
int      g_gzSellTotalOrders = 0;
double   g_gzLastBuyEntry    = 0;
double   g_gzLastSellEntry   = 0;

// Volatility based gapping
int      g_gzHandleATR       = INVALID_HANDLE;
double   g_gzATR             = 0;      // last closed-bar ATR used for spacing
double   g_gzStepAbs         = 0;      // grid step in price (last bar)
double   g_gzGapAbs          = 0;      // chain gap in price (last bar)

// Martingale position cap
bool     g_gzBuyExitPending  = false;  // OUT in progress: keep closing until the side is flat
bool     g_gzSellExitPending = false;
bool     g_gzBuyCapNoted     = false;  // HOLD message printed once per basket
bool     g_gzSellCapNoted    = false;
ulong    g_gzLastExitTryMs   = 0;

//+------------------------------------------------------------------+
//| 6 DRAMATICALLY DIFFERENT TRAIL SPEEDS                            |
//+------------------------------------------------------------------+
GZ_TrailConfig GZ_GetTrailConfig(ENUM_GZ_TRAIL_SPEED speed)
{
   GZ_TrailConfig cfg;
   cfg.triggerSpreads   = 3.0;
   cfg.trailDistSpreads = 2.5;
   cfg.ratchetFraction  = 0.40;
   cfg.minLockSpreads   = 1.0;

   switch(speed)
   {
      case GZ_TRAIL_SLOWEST:
         cfg.triggerSpreads   = 10.0;
         cfg.trailDistSpreads = 8.0;
         cfg.ratchetFraction  = 0.10;
         cfg.minLockSpreads   = 1.0;
         break;
      case GZ_TRAIL_SLOWER:
         cfg.triggerSpreads   = 6.0;
         cfg.trailDistSpreads = 5.0;
         cfg.ratchetFraction  = 0.20;
         cfg.minLockSpreads   = 0.8;
         break;
      case GZ_TRAIL_SLOW:
         cfg.triggerSpreads   = 3.0;
         cfg.trailDistSpreads = 2.5;
         cfg.ratchetFraction  = 0.40;
         cfg.minLockSpreads   = 0.5;
         break;
      case GZ_TRAIL_FAST:
         cfg.triggerSpreads   = 1.5;
         cfg.trailDistSpreads = 1.0;
         cfg.ratchetFraction  = 0.70;
         cfg.minLockSpreads   = 0.3;
         break;
      case GZ_TRAIL_FASTER:
         cfg.triggerSpreads   = 0.8;
         cfg.trailDistSpreads = 0.4;
         cfg.ratchetFraction  = 0.90;
         cfg.minLockSpreads   = 0.15;
         break;
      case GZ_TRAIL_FASTEST:
         cfg.triggerSpreads   = 0.3;
         cfg.trailDistSpreads = 0.1;
         cfg.ratchetFraction  = 0.98;
         cfg.minLockSpreads   = 0.05;
         break;
   }
   return cfg;
}

//+------------------------------------------------------------------+
string GZ_TrailSpeedName(ENUM_GZ_TRAIL_SPEED speed)
{
   switch(speed)
   {
      case GZ_TRAIL_SLOWEST: return "SLOWEST";
      case GZ_TRAIL_SLOWER:  return "SLOWER";
      case GZ_TRAIL_SLOW:    return "SLOW";
      case GZ_TRAIL_FAST:    return "FAST";
      case GZ_TRAIL_FASTER:  return "FASTER";
      case GZ_TRAIL_FASTEST: return "FASTEST";
   }
   return "SLOW";
}

//+------------------------------------------------------------------+
double GZ_GetSpreadPrice()
{
   double ask = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);
   double spread = ask - bid;
   if(spread < g_gzPoint) spread = g_gzPoint;
   return spread;
}

//+------------------------------------------------------------------+
void GZ_ResetTrailState()
{
   g_gzBuyTrailActive  = false;
   g_gzSellTrailActive = false;
   g_gzBuyPeakPrice    = 0;
   g_gzSellPeakPrice   = DBL_MAX;
   g_gzBuyTrailSL      = 0;
   g_gzSellTrailSL     = 0;
   g_gzBuyBE           = 0;
   g_gzSellBE          = 0;
}

//+------------------------------------------------------------------+
void GZ_ReconstructGridState()
{
   g_gzBuyTotalOrders  = 0;
   g_gzSellTotalOrders = 0;
   g_gzLastBuyEntry    = 0;
   g_gzLastSellEntry   = 0;

   datetime latestBuyTime = 0, latestSellTime = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);

      if(type == POSITION_TYPE_BUY)
      {
         g_gzBuyTotalOrders++;
         if(openTime > latestBuyTime) { latestBuyTime = openTime; g_gzLastBuyEntry = openPrice; }
      }
      else if(type == POSITION_TYPE_SELL)
      {
         g_gzSellTotalOrders++;
         if(openTime > latestSellTime) { latestSellTime = openTime; g_gzLastSellEntry = openPrice; }
      }
   }

   g_gzBuyChainCount  = (g_gzBuyTotalOrders > 0)  ? (((g_gzBuyTotalOrders - 1) % InpGZ_GridChainSize) + 1) : 0;
   g_gzSellChainCount = (g_gzSellTotalOrders > 0) ? (((g_gzSellTotalOrders - 1) % InpGZ_GridChainSize) + 1) : 0;

   if(g_gzBuyChainCount >= InpGZ_GridChainSize)  { g_gzBuyInGap = true;  g_gzBuyGapAnchor = g_gzLastBuyEntry; }
   if(g_gzSellChainCount >= InpGZ_GridChainSize) { g_gzSellInGap = true; g_gzSellGapAnchor = g_gzLastSellEntry; }

   Print("[GridZ] Reconstructed: Buys=", g_gzBuyTotalOrders, " chain=", g_gzBuyChainCount,
         " | Sells=", g_gzSellTotalOrders, " chain=", g_gzSellChainCount);
}

//+------------------------------------------------------------------+
//| Weighted average entry + total lots (side: 0=buy, 1=sell)        |
//+------------------------------------------------------------------+
void GZ_GetBasketInfo(int side, double &avgEntry, double &totalLots, int &count)
{
   avgEntry = 0; totalLots = 0; count = 0;
   double sumWeighted = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      if((side == 0 && type != POSITION_TYPE_BUY) ||
         (side == 1 && type != POSITION_TYPE_SELL))
         continue;

      double vol   = PositionGetDouble(POSITION_VOLUME);
      double price = PositionGetDouble(POSITION_PRICE_OPEN);
      sumWeighted += price * vol;
      totalLots   += vol;
      count++;
   }

   if(totalLots > 0) avgEntry = sumWeighted / totalLots;
}

//+------------------------------------------------------------------+
//| Collect ALL tickets for a side into an array                     |
//+------------------------------------------------------------------+
int GZ_CollectTickets(int side, ulong &tickets[])
{
   int cnt = 0;
   ArrayResize(tickets, 0);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      if((side == 0 && type != POSITION_TYPE_BUY) ||
         (side == 1 && type != POSITION_TYPE_SELL))
         continue;

      ArrayResize(tickets, cnt + 1);
      tickets[cnt] = ticket;
      cnt++;
   }
   return cnt;
}

//+------------------------------------------------------------------+
//| FORCE SL on a single ticket — 10 retries, 100ms apart            |
//| Returns true if SL was successfully set                          |
//+------------------------------------------------------------------+
bool GZ_ForceSLOnTicket(ulong ticket, double newSL, bool clearing)
{
   int digits = g_gzDigits;

   for(int attempt = 0; attempt < 10; attempt++)
   {
      // Re-select position each attempt (might have been closed)
      if(!PositionSelectByTicket(ticket))
      {
         Print("[GridZ] ForceSL: ticket ", ticket, " no longer exists, skip");
         return true; // position gone, nothing to do
      }

      double currentSL = PositionGetDouble(POSITION_SL);
      double currentTP = PositionGetDouble(POSITION_TP);

      // If clearing and already 0, done
      if(clearing && currentSL == 0) return true;

      // If not clearing, check if already at correct level
      if(!clearing && MathAbs(currentSL - newSL) < g_gzPoint * 0.5)
         return true; // already correct

      MqlTradeRequest req = {};
      MqlTradeResult  res = {};

      req.action   = TRADE_ACTION_SLTP;
      req.symbol   = g_gzSymbol;
      req.position = ticket;
      req.sl       = clearing ? 0 : NormalizeDouble(newSL, digits);
      req.tp       = currentTP;

      ResetLastError();
      bool sent = OrderSend(req, res);

      if(sent && (res.retcode == 10009 || res.retcode == 10008))
      {
         return true; // success
      }

      // 10025 = no changes needed
      if(res.retcode == 10025)
         return true;

      Print("[GridZ] ForceSL RETRY ", attempt + 1, "/10 | ticket=", ticket,
            " | SL=", DoubleToString(clearing ? 0 : newSL, digits),
            " | err=", res.retcode, " ", res.comment);

      if(attempt < 9)
         Sleep(100);
   }

   Print("[GridZ] ForceSL FAILED after 10 attempts | ticket=", ticket);
   return false;
}

//+------------------------------------------------------------------+
//| SET SL ON ALL POSITIONS OF A SIDE                                |
//| Forces SL on EVERY ticket — no position is ever skipped          |
//| Retries 10x per ticket if broker rejects                         |
//+------------------------------------------------------------------+
void GZ_SetSLOnSide(int side, double newSL)
{
   int digits = g_gzDigits;
   newSL = NormalizeDouble(newSL, digits);

   bool clearing = (newSL <= 0);

   // Collect all tickets first (avoid modifying while iterating)
   ulong tickets[];
   int count = GZ_CollectTickets(side, tickets);
   if(count == 0) return;

   if(!clearing)
   {
      // Profit guarantee: clamp SL to BE
      if(side == 0 && g_gzBuyBE > 0 && newSL < g_gzBuyBE)
         newSL = NormalizeDouble(g_gzBuyBE, digits);
      if(side == 1 && g_gzSellBE > 0 && newSL > g_gzSellBE)
         newSL = NormalizeDouble(g_gzSellBE, digits);

      // Broker stop level enforcement
      long stopLevelPts = SymbolInfoInteger(g_gzSymbol, SYMBOL_TRADE_STOPS_LEVEL);
      double stoplevel  = stopLevelPts * g_gzPoint;
      double bid = SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);

      if(side == 0) // BUY: SL must be below bid - stoplevel
      {
         double maxAllowed = NormalizeDouble(bid - stoplevel, digits);
         if(newSL > maxAllowed)
         {
            // If max allowed SL is below BE, we can't place profitable SL right now
            // But we still try — broker may accept at maxAllowed
            if(maxAllowed >= g_gzBuyBE || g_gzBuyBE == 0)
               newSL = maxAllowed;
            else
               return; // truly impossible right now, try next tick
         }
         if(newSL <= 0) return;
      }
      else // SELL: SL must be above ask + stoplevel
      {
         double minAllowed = NormalizeDouble(ask + stoplevel, digits);
         if(newSL < minAllowed)
         {
            if(minAllowed <= g_gzSellBE || g_gzSellBE == 0)
               newSL = minAllowed;
            else
               return;
         }
      }
   }

   //--- Force SL on EVERY ticket, no exceptions
   int successCount = 0;
   int failCount    = 0;

   for(int t = 0; t < count; t++)
   {
      // For non-clearing: only tighten direction check
      if(!clearing)
      {
         if(PositionSelectByTicket(tickets[t]))
         {
            double curSL = PositionGetDouble(POSITION_SL);
            if(curSL > 0)
            {
               if(side == 0 && newSL <= curSL) continue; // BUY: only move SL UP
               if(side == 1 && newSL >= curSL) continue; // SELL: only move SL DOWN
            }
         }
      }

      if(GZ_ForceSLOnTicket(tickets[t], newSL, clearing))
         successCount++;
      else
         failCount++;
   }

   if(failCount > 0)
      Print("[GridZ] SetSLOnSide WARNING: ", failCount, "/", count, " tickets failed SL placement");
}

//+------------------------------------------------------------------+
//| FORCE SL ON ENTIRE SIDE IMMEDIATELY — no conditions              |
//| Called after new grid order to ensure ALL positions get same SL  |
//| This recalculates BE from scratch and applies SL to everyone     |
//+------------------------------------------------------------------+
void GZ_ForceRecalcAndSetSL(int side)
{
   double avgEntry = 0, totalLots = 0;
   int count = 0;
   GZ_GetBasketInfo(side, avgEntry, totalLots, count);

   if(count == 0 || avgEntry == 0) return;

   double spread = GZ_GetSpreadPrice();
   int digits = g_gzDigits;

   if(side == 0) // BUY
   {
      double buyBE = NormalizeDouble(avgEntry + spread, digits);
      g_gzBuyBE = buyBE;

      // If trailing IS active, recalculate SL for the new basket.
      if(g_gzBuyTrailActive)
      {
         GZ_TrailConfig cfg = GZ_GetTrailConfig((count == 1) ? InpGZ_TrailFirst : InpGZ_TrailGrid);
         double bid = SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);

         // Check if we're still above trigger for new basket
         double triggerPrice = buyBE + cfg.triggerSpreads * spread;
         if(bid >= triggerPrice)
         {
            double trailDist   = cfg.trailDistSpreads * spread;
            double minProfitSL = NormalizeDouble(buyBE + cfg.minLockSpreads * spread, digits);

            g_gzBuyPeakPrice = bid;
            g_gzBuyTrailSL   = NormalizeDouble(bid - trailDist, digits);
            if(g_gzBuyTrailSL < minProfitSL) g_gzBuyTrailSL = minProfitSL;

            // Force SL on ALL buy positions including any that were missed
            GZ_SetSLOnSide(0, g_gzBuyTrailSL);
         }
         else
         {
            // New basket moved BE up, we're no longer above trigger
            // Clear all SLs and reset trailing
            g_gzBuyTrailActive = false;
            g_gzBuyPeakPrice   = 0;
            g_gzBuyTrailSL     = 0;
            GZ_SetSLOnSide(0, 0);
         }
      }
   }
   else // SELL
   {
      double sellBE = NormalizeDouble(avgEntry - spread, digits);
      g_gzSellBE = sellBE;

      if(g_gzSellTrailActive)
      {
         GZ_TrailConfig cfg = GZ_GetTrailConfig((count == 1) ? InpGZ_TrailFirst : InpGZ_TrailGrid);
         double ask = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);

         double triggerPrice = sellBE - cfg.triggerSpreads * spread;
         if(ask <= triggerPrice)
         {
            double trailDist   = cfg.trailDistSpreads * spread;
            double maxProfitSL = NormalizeDouble(sellBE - cfg.minLockSpreads * spread, digits);

            g_gzSellPeakPrice = ask;
            g_gzSellTrailSL   = NormalizeDouble(ask + trailDist, digits);
            if(g_gzSellTrailSL > maxProfitSL) g_gzSellTrailSL = maxProfitSL;

            GZ_SetSLOnSide(1, g_gzSellTrailSL);
         }
         else
         {
            g_gzSellTrailActive = false;
            g_gzSellPeakPrice   = DBL_MAX;
            g_gzSellTrailSL     = 0;
            GZ_SetSLOnSide(1, 0);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Verify all positions on a side are counted in grid               |
//+------------------------------------------------------------------+
void GZ_VerifyAllPositionsTracked(int side, int expectedCount)
{
   int actualCount = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      if((side == 0 && type == POSITION_TYPE_BUY) ||
         (side == 1 && type == POSITION_TYPE_SELL))
         actualCount++;
   }

   if(actualCount != expectedCount)
   {
      Print("[GridZ] POSITION COUNT MISMATCH! side=", side,
            " expected=", expectedCount, " actual=", actualCount,
            " | Fixing grid count...");

      if(side == 0)
      {
         g_gzBuyTotalOrders = actualCount;
         g_gzBuyChainCount  = (actualCount > 0) ? (((actualCount - 1) % InpGZ_GridChainSize) + 1) : 0;
      }
      else
      {
         g_gzSellTotalOrders = actualCount;
         g_gzSellChainCount  = (actualCount > 0) ? (((actualCount - 1) % InpGZ_GridChainSize) + 1) : 0;
      }
   }
}

//+------------------------------------------------------------------+
//| ENFORCE SL on ALL positions — catches missed SLs                 |
//+------------------------------------------------------------------+
void GZ_EnforceSLOnAll(int side, double requiredSL)
{
   int digits = g_gzDigits;
   double slNorm = NormalizeDouble(requiredSL, digits);

   if(slNorm <= 0) return;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;

      long type = PositionGetInteger(POSITION_TYPE);
      if((side == 0 && type != POSITION_TYPE_BUY) ||
         (side == 1 && type != POSITION_TYPE_SELL))
         continue;

      double currentSL = PositionGetDouble(POSITION_SL);

      // If SL is missing or wrong, force it
      bool needsFix = false;

      if(currentSL == 0)
      {
         needsFix = true; // No SL at all — must fix
      }
      else if(side == 0 && currentSL < slNorm - g_gzPoint)
      {
         needsFix = true; // Buy SL too low
      }
      else if(side == 1 && currentSL > slNorm + g_gzPoint)
      {
         needsFix = true; // Sell SL too high
      }

      if(needsFix)
      {
         Print("[GridZ] ENFORCE SL FIX: ticket=", ticket, " currentSL=",
               DoubleToString(currentSL, digits), " → requiredSL=",
               DoubleToString(slNorm, digits));
         GZ_ForceSLOnTicket(ticket, slNorm, false);
      }
   }
}

//+------------------------------------------------------------------+
//| REAL SL TRAILING — GUARANTEED PROFIT EXIT                        |
//| Runs every tick. Forces SL on ALL positions of each side.        |
//+------------------------------------------------------------------+
void GZ_ManageSLTrailing()
{
   int digits = g_gzDigits;
   double spread = GZ_GetSpreadPrice();
   double bid    = SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);
   double ask    = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);

   //=================================================================
   // BUY SIDE
   //=================================================================
   double buyAvg = 0, buyLots = 0;
   int buyCount = 0;
   GZ_GetBasketInfo(0, buyAvg, buyLots, buyCount);

   if(buyCount > 0 && buyAvg > 0)
   {
      // Pick trail config: 1 position = first trade speed, 2+ = grid speed
      GZ_TrailConfig cfg = GZ_GetTrailConfig((buyCount == 1) ? InpGZ_TrailFirst : InpGZ_TrailGrid);

      double buyBE = NormalizeDouble(buyAvg + spread, digits);
      g_gzBuyBE = buyBE;

      double triggerPrice = buyBE + cfg.triggerSpreads * spread;
      double trailDist    = cfg.trailDistSpreads * spread;
      double minProfitSL  = NormalizeDouble(buyBE + cfg.minLockSpreads * spread, digits);

      if(!g_gzBuyTrailActive)
      {
         if(bid >= triggerPrice)
         {
            g_gzBuyTrailActive = true;
            g_gzBuyPeakPrice   = bid;
            g_gzBuyTrailSL     = NormalizeDouble(bid - trailDist, digits);
            if(g_gzBuyTrailSL < minProfitSL) g_gzBuyTrailSL = minProfitSL;

            // Force SL on ALL buy positions — every single one
            GZ_SetSLOnSide(0, g_gzBuyTrailSL);

            Print("[GridZ] BUY TRAIL ON [", GZ_TrailSpeedName((buyCount == 1) ? InpGZ_TrailFirst : InpGZ_TrailGrid),
                  "] bid=", DoubleToString(bid, digits),
                  " BE=", DoubleToString(buyBE, digits),
                  " SL=", DoubleToString(g_gzBuyTrailSL, digits),
                  " positions=", buyCount);
         }
         else
         {
            // Not yet triggered — verify ALL positions are accounted for
            GZ_VerifyAllPositionsTracked(0, buyCount);
         }
      }
      else
      {
         trailDist   = cfg.trailDistSpreads * spread;
         minProfitSL = NormalizeDouble(buyBE + cfg.minLockSpreads * spread, digits);

         if(bid > g_gzBuyPeakPrice)
            g_gzBuyPeakPrice = bid;

         double idealSL    = g_gzBuyPeakPrice - trailDist;
         double proposedSL = g_gzBuyTrailSL + (idealSL - g_gzBuyTrailSL) * cfg.ratchetFraction;
         proposedSL = NormalizeDouble(proposedSL, digits);

         if(proposedSL < minProfitSL) proposedSL = minProfitSL;

         if(proposedSL > g_gzBuyTrailSL)
         {
            g_gzBuyTrailSL = proposedSL;
            // Force on ALL — catches any position that was missed earlier
            GZ_SetSLOnSide(0, g_gzBuyTrailSL);
         }
         else
         {
            // SL didn't move, but still verify every position has SL set
            GZ_EnforceSLOnAll(0, g_gzBuyTrailSL);
         }
      }
   }
   else
   {
      if(g_gzBuyTrailActive || g_gzBuyTotalOrders > 0)
      {
         g_gzBuyTrailActive = false;
         g_gzBuyPeakPrice   = 0;
         g_gzBuyTrailSL     = 0;
         g_gzBuyBE          = 0;
         g_gzBuyChainCount  = 0;
         g_gzBuyInGap       = false;
         g_gzBuyGapAnchor   = 0;
         g_gzBuyTotalOrders = 0;
         g_gzLastBuyEntry   = 0;
      }
   }

   //=================================================================
   // SELL SIDE
   //=================================================================
   double sellAvg = 0, sellLots = 0;
   int sellCount = 0;
   GZ_GetBasketInfo(1, sellAvg, sellLots, sellCount);

   if(sellCount > 0 && sellAvg > 0)
   {
      GZ_TrailConfig cfg = GZ_GetTrailConfig((sellCount == 1) ? InpGZ_TrailFirst : InpGZ_TrailGrid);

      double sellBE = NormalizeDouble(sellAvg - spread, digits);
      g_gzSellBE = sellBE;

      double triggerPrice = sellBE - cfg.triggerSpreads * spread;
      double trailDist    = cfg.trailDistSpreads * spread;
      double maxProfitSL  = NormalizeDouble(sellBE - cfg.minLockSpreads * spread, digits);

      if(!g_gzSellTrailActive)
      {
         if(ask <= triggerPrice)
         {
            g_gzSellTrailActive = true;
            g_gzSellPeakPrice   = ask;
            g_gzSellTrailSL     = NormalizeDouble(ask + trailDist, digits);
            if(g_gzSellTrailSL > maxProfitSL) g_gzSellTrailSL = maxProfitSL;

            GZ_SetSLOnSide(1, g_gzSellTrailSL);

            Print("[GridZ] SELL TRAIL ON [", GZ_TrailSpeedName((sellCount == 1) ? InpGZ_TrailFirst : InpGZ_TrailGrid),
                  "] ask=", DoubleToString(ask, digits),
                  " BE=", DoubleToString(sellBE, digits),
                  " SL=", DoubleToString(g_gzSellTrailSL, digits),
                  " positions=", sellCount);
         }
         else
         {
            GZ_VerifyAllPositionsTracked(1, sellCount);
         }
      }
      else
      {
         trailDist   = cfg.trailDistSpreads * spread;
         maxProfitSL = NormalizeDouble(sellBE - cfg.minLockSpreads * spread, digits);

         if(ask < g_gzSellPeakPrice)
            g_gzSellPeakPrice = ask;

         double idealSL    = g_gzSellPeakPrice + trailDist;
         double proposedSL = g_gzSellTrailSL - (g_gzSellTrailSL - idealSL) * cfg.ratchetFraction;
         proposedSL = NormalizeDouble(proposedSL, digits);

         if(proposedSL > maxProfitSL) proposedSL = maxProfitSL;

         if(proposedSL < g_gzSellTrailSL)
         {
            g_gzSellTrailSL = proposedSL;
            GZ_SetSLOnSide(1, g_gzSellTrailSL);
         }
         else
         {
            GZ_EnforceSLOnAll(1, g_gzSellTrailSL);
         }
      }
   }
   else
   {
      if(g_gzSellTrailActive || g_gzSellTotalOrders > 0)
      {
         g_gzSellTrailActive = false;
         g_gzSellPeakPrice   = DBL_MAX;
         g_gzSellTrailSL     = 0;
         g_gzSellBE          = 0;
         g_gzSellChainCount  = 0;
         g_gzSellInGap       = false;
         g_gzSellGapAnchor   = 0;
         g_gzSellTotalOrders = 0;
         g_gzLastSellEntry   = 0;
      }
   }
}

//+------------------------------------------------------------------+
double GZ_CalcZScore(int shift)
{
   double ma[], std[];
   if(CopyBuffer(g_gzHandleMA, 0, shift, 1, ma) < 1)    return EMPTY_VALUE;
   if(CopyBuffer(g_gzHandleStd, 0, shift, 1, std) < 1)  return EMPTY_VALUE;
   double close = iClose(g_gzSymbol, g_gzTF, shift);
   if(close <= 0) return EMPTY_VALUE;                    // history not loaded yet
   if(std[0] < g_gzPoint * 0.001) return 0.0;
   return (close - ma[0]) / std[0];
}

//+------------------------------------------------------------------+
void GZ_CountPositions(int &buyCount, int &sellCount)
{
   buyCount = 0; sellCount = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      if(type == POSITION_TYPE_BUY)  buyCount++;
      else if(type == POSITION_TYPE_SELL) sellCount++;
   }
}

//+------------------------------------------------------------------+
//| VOLATILITY BASED GAPPING                                         |
//| Grid step and chain gap follow the ATR of the engine timeframe,  |
//| so the grid spreads out when the market moves fast.              |
//| The fixed % inputs stay as a MINIMUM, so the spacing is never    |
//| tighter than the original fixed-% grid.                          |
//+------------------------------------------------------------------+
double GZ_GetATR()
{
   if(g_gzHandleATR == INVALID_HANDLE) return 0.0;
   double b[];
   if(CopyBuffer(g_gzHandleATR, 0, 1, 1, b) < 1) return 0.0;   // last CLOSED bar
   if(b[0] <= 0 || b[0] == EMPTY_VALUE) return 0.0;
   return b[0];
}

void GZ_CalcSpacing(double refPrice, double &stepAbs, double &gapAbs)
{
   stepAbs = refPrice * InpGZ_GridThreshold / 100.0;
   gapAbs  = refPrice * InpGZ_GapResetPct  / 100.0;

   if(InpGZ_GapMode == GZ_GAP_VOLATILITY)
   {
      double atr = GZ_GetATR();
      g_gzATR = atr;
      if(atr > 0)                                   // ATR not ready -> fixed % is used
      {
         stepAbs = MathMax(stepAbs, atr * InpGZ_VolStepMult);
         gapAbs  = MathMax(gapAbs,  atr * InpGZ_VolGapMult);
      }
   }
}

//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING GZ_FillingMode()
{
   long fillType = SymbolInfoInteger(g_gzSymbol, SYMBOL_FILLING_MODE);
   if((fillType & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
   if((fillType & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

//+------------------------------------------------------------------+
//| MARTINGALE POSITION CAP                                          |
//+------------------------------------------------------------------+
void GZ_ResetSide(int side)
{
   if(side == 0)
   {
      g_gzBuyTrailActive = false;
      g_gzBuyPeakPrice   = 0;
      g_gzBuyTrailSL     = 0;
      g_gzBuyBE          = 0;
      g_gzBuyChainCount  = 0;
      g_gzBuyInGap       = false;
      g_gzBuyGapAnchor   = 0;
      g_gzBuyTotalOrders = 0;
      g_gzLastBuyEntry   = 0;
      g_gzBuyCapNoted    = false;
   }
   else
   {
      g_gzSellTrailActive = false;
      g_gzSellPeakPrice   = DBL_MAX;
      g_gzSellTrailSL     = 0;
      g_gzSellBE          = 0;
      g_gzSellChainCount  = 0;
      g_gzSellInGap       = false;
      g_gzSellGapAnchor   = 0;
      g_gzSellTotalOrders = 0;
      g_gzLastSellEntry   = 0;
      g_gzSellCapNoted    = false;
   }
}

// Close ONE grid position at market. Returns true when it is gone.
bool GZ_ClosePosition(ulong ticket)
{
   for(int attempt = 0; attempt < 5; attempt++)
   {
      if(!PositionSelectByTicket(ticket)) return true;          // already closed

      long   type = PositionGetInteger(POSITION_TYPE);
      double vol  = PositionGetDouble(POSITION_VOLUME);

      MqlTradeRequest req = {};
      MqlTradeResult  res = {};

      req.action       = TRADE_ACTION_DEAL;
      req.symbol       = g_gzSymbol;
      req.position     = ticket;
      req.volume       = vol;
      req.type         = (type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
      req.price        = (type == POSITION_TYPE_BUY) ? SymbolInfoDouble(g_gzSymbol, SYMBOL_BID)
                                                     : SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);
      req.deviation    = InpGZ_Slippage;
      req.magic        = InpGZ_Magic;
      req.comment      = InpGZ_Comment + " CAP OUT";
      req.type_filling = GZ_FillingMode();

      ResetLastError();
      bool sent = OrderSend(req, res);
      if(sent && res.retcode == TRADE_RETCODE_DONE) return true;
      if(sent && res.retcode == TRADE_RETCODE_DONE_PARTIAL) continue;   // close the remainder

      Print("[GridZ] CAP OUT close RETRY ", attempt + 1, "/5 | ticket=", ticket,
            " | err=", res.retcode, " ", res.comment);
      if(attempt < 4) Sleep(100);
   }
   return !PositionSelectByTicket(ticket);
}

// Close every grid position of one side (this engine's asset + magic only).
bool GZ_CloseSide(int side)
{
   ulong tickets[];
   int count = GZ_CollectTickets(side, tickets);
   bool allClosed = true;
   for(int t = 0; t < count; t++)
      if(!GZ_ClosePosition(tickets[t])) allClosed = false;
   return allClosed;
}

// Runs every tick: finishes an OUT that could not close everything at once.
void GZ_RunPendingExits()
{
   if(!g_gzBuyExitPending && !g_gzSellExitPending) return;

   ulong now = GetTickCount64();
   if(g_gzLastExitTryMs != 0 && now - g_gzLastExitTryMs < 2000) return;   // don't hammer the broker
   g_gzLastExitTryMs = (now == 0) ? 1 : now;

   if(g_gzBuyExitPending && GZ_CloseSide(0))
   {
      g_gzBuyExitPending = false;
      GZ_ResetSide(0);
      Print("[GridZ] CAP OUT: BUY basket closed");
   }
   if(g_gzSellExitPending && GZ_CloseSide(1))
   {
      g_gzSellExitPending = false;
      GZ_ResetSide(1);
      Print("[GridZ] CAP OUT: SELL basket closed");
   }
}

// Called when a side is AT the cap and price has reached the level where the
// next martingale order (or the next chain) would have been opened.
void GZ_OnCapHit(int side, int count)
{
   string sideTxt = (side == 0) ? "BUY" : "SELL";

   if(InpGZ_CapAction == GZ_CAP_OUT)
   {
      Print("[GridZ] POSITION CAP ", InpGZ_MaxPositions, " reached on ", sideTxt, " side (", count,
            " open) and the next level was hit -> OUT: closing the whole ", sideTxt, " basket");
      if(side == 0) g_gzBuyExitPending = true; else g_gzSellExitPending = true;
      g_gzLastExitTryMs = 0;
      GZ_RunPendingExits();
   }
   else
   {
      bool noted = (side == 0) ? g_gzBuyCapNoted : g_gzSellCapNoted;
      if(!noted)
      {
         Print("[GridZ] POSITION CAP ", InpGZ_MaxPositions, " reached on ", sideTxt, " side (", count,
               " open) -> HOLD: no more orders are added, basket stays open");
         if(side == 0) g_gzBuyCapNoted = true; else g_gzSellCapNoted = true;
      }
   }
}

//+------------------------------------------------------------------+
double GZ_CalcLot(int chainLevel)
{
   double baseLot = InpGZ_FixedLot;

   if(InpGZ_LotMode == GZ_LOT_RISK_PCT)
   {
      double equity = AccountInfoDouble(ACCOUNT_EQUITY);
      double riskAmount = equity * InpGZ_RiskPct / 100.0;
      double tickVal  = SymbolInfoDouble(g_gzSymbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSize = SymbolInfoDouble(g_gzSymbol, SYMBOL_TRADE_TICK_SIZE);
      double price    = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);
      double thresholdPrice = 0, gapUnused = 0;
      GZ_CalcSpacing(price, thresholdPrice, gapUnused);   // same step the grid uses
      double thresholdPts   = (tickSize > 0) ? thresholdPrice / tickSize : 0;
      if(tickVal > 0 && thresholdPts > 0)
         baseLot = riskAmount / (thresholdPts * tickVal);
      else
         baseLot = InpGZ_FixedLot;
   }

   double lot = baseLot * MathPow(InpGZ_MartingaleMult, chainLevel - 1);
   double minLot  = SymbolInfoDouble(g_gzSymbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(g_gzSymbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(g_gzSymbol, SYMBOL_VOLUME_STEP);
   if(stepLot <= 0) stepLot = 0.01;
   lot = MathMax(lot, minLot);
   lot = MathMin(lot, maxLot);
   lot = MathFloor(lot / stepLot) * stepLot;
   return NormalizeDouble(lot, 2);
}

//+------------------------------------------------------------------+
bool GZ_OpenOrder(ENUM_ORDER_TYPE type, double lot, string comment)
{
   MqlTradeRequest req = {};
   MqlTradeResult  res = {};

   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = g_gzSymbol;
   req.volume    = lot;
   req.type      = type;
   req.price     = (type == ORDER_TYPE_BUY) ? SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK)
                                             : SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);
   req.deviation = InpGZ_Slippage;
   req.magic     = InpGZ_Magic;
   req.comment   = InpGZ_Comment + " " + comment;

   req.type_filling = GZ_FillingMode();

   if(!OrderSend(req, res))
   {
      Print("[GridZ] OrderSend FAILED: ", res.retcode, " | ", res.comment, " | ", comment);
      return false;
   }

   Print("[GridZ] ORDER: ", comment, " | Lot=", DoubleToString(lot, 2),
         " | Price=", DoubleToString(req.price, g_gzDigits),
         " | Ticket=", res.order);
   return true;
}

//+------------------------------------------------------------------+
//| Engine A dashboard (chart comment, top-left)                     |
//+------------------------------------------------------------------+
void GZ_DrawDashboard(double zscore, int buyCount, int sellCount)
{
   if(!InpGZ_ShowOnChart) return;

   double totalPnL = 0, totalLots = 0;
   int totalPos = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;
      totalPnL  += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      totalLots += PositionGetDouble(POSITION_VOLUME);
      totalPos++;
   }

   int digits = g_gzDigits;
   string sp1 = GZ_TrailSpeedName(InpGZ_TrailFirst);
   string spG = GZ_TrailSpeedName(InpGZ_TrailGrid);

   // Active trail speed label (switches when grid forms)
   string buyActiveSpeed  = (buyCount >= 2) ? spG : sp1;
   string sellActiveSpeed = (sellCount >= 2) ? spG : sp1;

   string buyTrailStr = "---";
   if(g_gzBuyTrailActive)
      buyTrailStr = "TRAILING SL=" + DoubleToString(g_gzBuyTrailSL, digits)
                  + " Peak=" + DoubleToString(g_gzBuyPeakPrice, digits)
                  + " BE=" + DoubleToString(g_gzBuyBE, digits);
   else if(buyCount > 0)
      buyTrailStr = "ARMED [" + buyActiveSpeed + "]";

   string sellTrailStr = "---";
   if(g_gzSellTrailActive)
      sellTrailStr = "TRAILING SL=" + DoubleToString(g_gzSellTrailSL, digits)
                   + " Trough=" + DoubleToString(g_gzSellPeakPrice, digits)
                   + " BE=" + DoubleToString(g_gzSellBE, digits);
   else if(sellCount > 0)
      sellTrailStr = "ARMED [" + sellActiveSpeed + "]";

   string buyGapStr  = g_gzBuyInGap  ? "GAP WAIT" : IntegerToString(g_gzBuyChainCount)  + "/" + IntegerToString(InpGZ_GridChainSize);
   string sellGapStr = g_gzSellInGap ? "GAP WAIT" : IntegerToString(g_gzSellChainCount) + "/" + IntegerToString(InpGZ_GridChainSize);
   int buyChainNum  = (g_gzBuyTotalOrders > 0)  ? ((g_gzBuyTotalOrders - 1) / InpGZ_GridChainSize) + 1 : 0;
   int sellChainNum = (g_gzSellTotalOrders > 0) ? ((g_gzSellTotalOrders - 1) / InpGZ_GridChainSize) + 1 : 0;

   double buyAvg = 0, buyL = 0; int bc2 = 0;
   double sellAvg = 0, sellL = 0; int sc2 = 0;
   GZ_GetBasketInfo(0, buyAvg, buyL, bc2);
   GZ_GetBasketInfo(1, sellAvg, sellL, sc2);

   // Count positions with SL vs without SL
   int buySLCount = 0, buyNoSLCount = 0;
   int sellSLCount = 0, sellNoSLCount = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_gzSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpGZ_Magic) continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double sl = PositionGetDouble(POSITION_SL);
      if(type == POSITION_TYPE_BUY)  { if(sl > 0) buySLCount++;  else buyNoSLCount++; }
      if(type == POSITION_TYPE_SELL) { if(sl > 0) sellSLCount++; else sellNoSLCount++; }
   }

   string dash = "";
   dash += "╔═══════════════════════════════════════════════════════╗\n";
   dash += "║   ZSCORE AND LEVANDO MIX\n";
   dash += "║   ENGINE A — GRID Z-SCORE MEAN REVERSION v3.2\n";
   dash += "║   DXB TRADING | @TheMoneyMakerIND\n";
   dash += "║   Asset: " + g_gzSymbol + "  |  TF: " + TFToText(g_gzTF) + "  |  Magic: " + IntegerToString(InpGZ_Magic) + "\n";
   dash += "╠═══════════════════════════════════════════════════════╣\n";
   dash += "║ Z-Score: " + DoubleToString(zscore, 4) + "  Spread: " + DoubleToString(GZ_GetSpreadPrice(), digits) + "\n";
   dash += "╠═══════════════════════════════════════════════════════╣\n";
   dash += "║ BUYS:  " + IntegerToString(buyCount) + " | Chain " + buyGapStr + " (set " + IntegerToString(buyChainNum) + ")\n";
   if(buyCount > 0)
   {
      dash += "║   Avg=" + DoubleToString(buyAvg, digits) + " Lots=" + DoubleToString(buyL, 2) + " BE=" + DoubleToString(g_gzBuyBE, digits) + "\n";
      dash += "║   SL: " + IntegerToString(buySLCount) + " set / " + IntegerToString(buyNoSLCount) + " pending  [" + buyActiveSpeed + "]\n";
   }
   dash += "║   " + buyTrailStr + "\n";
   dash += "║ SELLS: " + IntegerToString(sellCount) + " | Chain " + sellGapStr + " (set " + IntegerToString(sellChainNum) + ")\n";
   if(sellCount > 0)
   {
      dash += "║   Avg=" + DoubleToString(sellAvg, digits) + " Lots=" + DoubleToString(sellL, 2) + " BE=" + DoubleToString(g_gzSellBE, digits) + "\n";
      dash += "║   SL: " + IntegerToString(sellSLCount) + " set / " + IntegerToString(sellNoSLCount) + " pending  [" + sellActiveSpeed + "]\n";
   }
   dash += "║   " + sellTrailStr + "\n";
   dash += "╠═══════════════════════════════════════════════════════╣\n";
   dash += "║ PnL:        $" + DoubleToString(totalPnL, 2) + "\n";
   dash += "║ Positions:  " + IntegerToString(totalPos) + "  Lots: " + DoubleToString(totalLots, 2) + "\n";
   dash += "║ Both Sides: " + (InpGZ_AllowBothSides ? "YES" : "NO") + "\n";
   dash += "║ 1st Trail:  " + sp1 + "  |  Grid Trail: " + spG + "\n";
   dash += "║ Martingale: x" + DoubleToString(InpGZ_MartingaleMult, 2) + "\n";
   dash += "║ Gapping:    " + (InpGZ_GapMode == GZ_GAP_VOLATILITY
                              ? "VOLATILITY  ATR(" + IntegerToString(InpGZ_VolATRPeriod) + ")=" + DoubleToString(g_gzATR, digits)
                              : "FIXED %")
                          + "  Step=" + DoubleToString(g_gzStepAbs, digits)
                          + "  Gap=" + DoubleToString(g_gzGapAbs, digits) + "\n";
   dash += "║ Pos cap:    " + (InpGZ_MaxPositions > 0
                              ? IntegerToString(InpGZ_MaxPositions) + " per side -> " + (InpGZ_CapAction == GZ_CAP_OUT ? "OUT" : "HOLD")
                              : "OFF")
                          + ((g_gzBuyExitPending || g_gzSellExitPending) ? "   [CLOSING BASKET]" : "") + "\n";
   dash += "╚═══════════════════════════════════════════════════════╝\n";

   Comment(dash);
}

//+------------------------------------------------------------------+
//| Engine A init                                                    |
//+------------------------------------------------------------------+
bool GZ_Init()
{
   if(InpGZ_ZscorePeriod < 2 || InpGZ_GridChainSize < 1)
   {
      MixFail("[GridZ] Z-Score period must be >= 2 and Grid Chain Size must be >= 1.");
      return false;
   }

   g_gzTF     = (InpGZ_Timeframe == PERIOD_CURRENT) ? (ENUM_TIMEFRAMES)Period() : InpGZ_Timeframe;
   g_gzPoint  = SymbolInfoDouble(g_gzSymbol, SYMBOL_POINT);
   g_gzDigits = (int)SymbolInfoInteger(g_gzSymbol, SYMBOL_DIGITS);
   if(g_gzPoint <= 0)
   {
      MixFail("[GridZ] cannot read symbol properties for '" + g_gzSymbol + "'.");
      return false;
   }

   g_gzHandleMA = iMA(g_gzSymbol, g_gzTF, InpGZ_ZscorePeriod, 0, MODE_SMA, PRICE_CLOSE);
   if(g_gzHandleMA == INVALID_HANDLE)
   {
      MixFail("[GridZ] failed to create MA handle.");
      return false;
   }

   g_gzHandleStd = iStdDev(g_gzSymbol, g_gzTF, InpGZ_ZscorePeriod, 0, MODE_SMA, PRICE_CLOSE);
   if(g_gzHandleStd == INVALID_HANDLE)
   {
      MixFail("[GridZ] failed to create StdDev handle.");
      return false;
   }

   if(InpGZ_GapMode == GZ_GAP_VOLATILITY)
   {
      if(InpGZ_VolATRPeriod < 1 || InpGZ_VolStepMult <= 0 || InpGZ_VolGapMult <= 0)
      {
         MixFail("[GridZ] volatility gapping needs ATR period >= 1 and both ATR multipliers > 0.");
         return false;
      }
      g_gzHandleATR = iATR(g_gzSymbol, g_gzTF, InpGZ_VolATRPeriod);
      if(g_gzHandleATR == INVALID_HANDLE)
      {
         MixFail("[GridZ] failed to create ATR handle.");
         return false;
      }
   }

   g_gzBuyExitPending  = false;
   g_gzSellExitPending = false;
   g_gzBuyCapNoted     = false;
   g_gzSellCapNoted    = false;
   g_gzLastExitTryMs   = 0;

   GZ_ReconstructGridState();
   GZ_ResetTrailState();
   g_gzLastBarTime = 0;
   g_gzTickCounter = 0;
   g_gzHaveZ       = false;

   Print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
   Print("  ENGINE A: GridZScoreMR v3.2 | DXB TRADING");
   Print("  Asset: ", g_gzSymbol, " | TF: ", TFToText(g_gzTF), " | Magic=", InpGZ_Magic);
   Print("  1st Trade Trail: ", GZ_TrailSpeedName(InpGZ_TrailFirst));
   Print("  Grid Trail:      ", GZ_TrailSpeedName(InpGZ_TrailGrid));
   Print("  Gapping: ", (InpGZ_GapMode == GZ_GAP_VOLATILITY
                        ? "VOLATILITY (ATR " + IntegerToString(InpGZ_VolATRPeriod) + ", step x" + DoubleToString(InpGZ_VolStepMult, 2) +
                          ", gap x" + DoubleToString(InpGZ_VolGapMult, 2) + ", fixed % as minimum)"
                        : "FIXED %"));
   Print("  Martingale: x", DoubleToString(InpGZ_MartingaleMult, 2), " | Position cap: ",
         (InpGZ_MaxPositions > 0 ? IntegerToString(InpGZ_MaxPositions) + " per side -> " + (InpGZ_CapAction == GZ_CAP_OUT ? "OUT" : "HOLD") : "OFF"));
   Print("  GUARANTEED PROFIT EXIT | Force SL 10x Retry");
   Print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
   return true;
}

void GZ_Deinit()
{
   if(g_gzHandleMA  != INVALID_HANDLE) { IndicatorRelease(g_gzHandleMA);  g_gzHandleMA  = INVALID_HANDLE; }
   if(g_gzHandleStd != INVALID_HANDLE) { IndicatorRelease(g_gzHandleStd); g_gzHandleStd = INVALID_HANDLE; }
   if(g_gzHandleATR != INVALID_HANDLE) { IndicatorRelease(g_gzHandleATR); g_gzHandleATR = INVALID_HANDLE; }
   Comment("");
}

//+------------------------------------------------------------------+
//| Engine A — one pass (called on every tick of ITS asset)          |
//+------------------------------------------------------------------+
void GZ_Process()
{
   //--- Finish any position-cap OUT that is still closing
   GZ_RunPendingExits();

   //--- Real SL trailing EVERY TICK on ALL positions
   GZ_ManageSLTrailing();

   //--- Keep the dashboard fresh between bars (display only)
   g_gzTickCounter++;
   if(g_gzHaveZ && (g_gzTickCounter % 5 == 0))
   {
      int b = 0, s = 0;
      GZ_CountPositions(b, s);
      GZ_DrawDashboard(g_gzLastZ, b, s);
   }

   //--- Grid logic on a NEW BAR of the engine's own timeframe only
   datetime barTime = iTime(g_gzSymbol, g_gzTF, 0);
   if(barTime <= 0 || barTime == g_gzLastBarTime) return;

   double zscore = GZ_CalcZScore(1);
   if(zscore == EMPTY_VALUE) return;     // history/indicator not ready — retry this same bar next tick
   g_gzLastBarTime = barTime;
   g_gzLastZ       = zscore;
   g_gzHaveZ       = true;

   int buyCount = 0, sellCount = 0;
   GZ_CountPositions(buyCount, sellCount);

   double closeBar1    = iClose(g_gzSymbol, g_gzTF, 1);
   double thresholdAbs = 0, gapAbs = 0;
   GZ_CalcSpacing(closeBar1, thresholdAbs, gapAbs);   // fixed % or volatility (ATR) based
   g_gzStepAbs = thresholdAbs;
   g_gzGapAbs  = gapAbs;

   if(buyCount  == 0) g_gzBuyCapNoted  = false;
   if(sellCount == 0) g_gzSellCapNoted = false;

   // Detect if SL trail closed all positions
   if(buyCount == 0 && g_gzBuyTotalOrders > 0)
   {
      g_gzBuyChainCount = 0; g_gzBuyInGap = false; g_gzBuyGapAnchor = 0;
      g_gzBuyTotalOrders = 0; g_gzLastBuyEntry = 0;
   }
   if(sellCount == 0 && g_gzSellTotalOrders > 0)
   {
      g_gzSellChainCount = 0; g_gzSellInGap = false; g_gzSellGapAnchor = 0;
      g_gzSellTotalOrders = 0; g_gzLastSellEntry = 0;
   }

   //=================================================================
   //  BUY SIDE
   //=================================================================
   bool buyAllowed = (InpGZ_AllowBothSides || sellCount == 0) && !g_gzBuyExitPending;
   bool buyAtCap   = (InpGZ_MaxPositions > 0 && buyCount >= InpGZ_MaxPositions);

   if(buyAllowed)
   {
      if(buyCount == 0 && zscore <= InpGZ_ZscoreBuyTh)
      {
         double lot = GZ_CalcLot(1);
         if(GZ_OpenOrder(ORDER_TYPE_BUY, lot, "GridZ B#1 C1"))
         {
            g_gzBuyChainCount  = 1;
            g_gzBuyTotalOrders = 1;
            g_gzBuyInGap       = false;
            g_gzLastBuyEntry   = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);

            // Reset trail for fresh basket
            g_gzBuyTrailActive = false;
            g_gzBuyPeakPrice   = 0;
            g_gzBuyTrailSL     = 0;
            g_gzBuyBE          = 0;

            Print("[GridZ] Z-SCORE BUY #1 | zscore=", DoubleToString(zscore, 4));
         }
      }
      else if(buyCount > 0)
      {
         if(g_gzBuyInGap)
         {
            double dropFromAnchor = g_gzBuyGapAnchor - closeBar1;
            if(dropFromAnchor >= gapAbs && buyAtCap)
            {
               GZ_OnCapHit(0, buyCount);   // at the cap: OUT or HOLD instead of a new chain
            }
            else if(dropFromAnchor >= gapAbs)
            {
               g_gzBuyChainCount = 0;
               g_gzBuyInGap      = false;

               double lot = GZ_CalcLot(1);
               int chainNum = (g_gzBuyTotalOrders / InpGZ_GridChainSize) + 1;
               if(GZ_OpenOrder(ORDER_TYPE_BUY, lot, "GridZ B#1 C" + IntegerToString(chainNum + 1)))
               {
                  g_gzBuyChainCount  = 1;
                  g_gzBuyTotalOrders++;
                  g_gzLastBuyEntry   = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);

                  // Reset + recalc SL for new basket (ALL positions)
                  g_gzBuyTrailActive = false;
                  g_gzBuyPeakPrice   = 0;
                  g_gzBuyTrailSL     = 0;
                  g_gzBuyBE          = 0;
                  GZ_SetSLOnSide(0, 0);       // clear old SLs
                  GZ_ForceRecalcAndSetSL(0);  // recalc BE + set SL on ALL

                  Print("[GridZ] GAP RESET BUY | New chain | drop=", DoubleToString(dropFromAnchor, 2));
               }
            }
         }
         else
         {
            double dropFromLast = g_gzLastBuyEntry - closeBar1;

            if(dropFromLast >= thresholdAbs && buyAtCap)
            {
               GZ_OnCapHit(0, buyCount);   // at the cap: OUT or HOLD instead of the next martingale order
            }
            else if(dropFromLast >= thresholdAbs)
            {
               int chainLevel = g_gzBuyChainCount + 1;
               double lot = GZ_CalcLot(chainLevel);
               int chainNum = (g_gzBuyTotalOrders / InpGZ_GridChainSize) + 1;

               if(GZ_OpenOrder(ORDER_TYPE_BUY, lot, "GridZ B#" + IntegerToString(chainLevel) + " C" + IntegerToString(chainNum)))
               {
                  g_gzBuyChainCount++;
                  g_gzBuyTotalOrders++;
                  g_gzLastBuyEntry = SymbolInfoDouble(g_gzSymbol, SYMBOL_ASK);

                  // CRITICAL: Reset trail + clear old SLs + recalc for ALL positions
                  g_gzBuyTrailActive = false;
                  g_gzBuyPeakPrice   = 0;
                  g_gzBuyTrailSL     = 0;
                  g_gzBuyBE          = 0;
                  GZ_SetSLOnSide(0, 0);       // clear ALL buy SLs
                  GZ_ForceRecalcAndSetSL(0);  // recalc + set on ALL

                  Print("[GridZ] GRID BUY #", g_gzBuyChainCount, " C", chainNum,
                        " | lot=", DoubleToString(lot, 2));

                  if(g_gzBuyChainCount >= InpGZ_GridChainSize)
                  {
                     g_gzBuyInGap     = true;
                     g_gzBuyGapAnchor = g_gzLastBuyEntry;
                     Print("[GridZ] BUY CHAIN FULL → GAP MODE");
                  }
               }
            }
            else if(closeBar1 < g_gzLastBuyEntry)
            {
               Print("[GridZ] Buy: drop=", DoubleToString(dropFromLast, 2),
                     " < th=", DoubleToString(thresholdAbs, 2), " | NO TRADE");
            }
         }
      }
   }

   //=================================================================
   //  SELL SIDE
   //=================================================================
   bool sellAllowed = (InpGZ_AllowBothSides || buyCount == 0) && !g_gzSellExitPending;
   bool sellAtCap   = (InpGZ_MaxPositions > 0 && sellCount >= InpGZ_MaxPositions);

   if(sellAllowed)
   {
      if(sellCount == 0 && zscore >= InpGZ_ZscoreSellTh)
      {
         double lot = GZ_CalcLot(1);
         if(GZ_OpenOrder(ORDER_TYPE_SELL, lot, "GridZ S#1 C1"))
         {
            g_gzSellChainCount  = 1;
            g_gzSellTotalOrders = 1;
            g_gzSellInGap       = false;
            g_gzLastSellEntry   = SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);

            g_gzSellTrailActive = false;
            g_gzSellPeakPrice   = DBL_MAX;
            g_gzSellTrailSL     = 0;
            g_gzSellBE          = 0;

            Print("[GridZ] Z-SCORE SELL #1 | zscore=", DoubleToString(zscore, 4));
         }
      }
      else if(sellCount > 0)
      {
         if(g_gzSellInGap)
         {
            double riseFromAnchor = closeBar1 - g_gzSellGapAnchor;
            if(riseFromAnchor >= gapAbs && sellAtCap)
            {
               GZ_OnCapHit(1, sellCount);
            }
            else if(riseFromAnchor >= gapAbs)
            {
               g_gzSellChainCount = 0;
               g_gzSellInGap      = false;

               double lot = GZ_CalcLot(1);
               int chainNum = (g_gzSellTotalOrders / InpGZ_GridChainSize) + 1;
               if(GZ_OpenOrder(ORDER_TYPE_SELL, lot, "GridZ S#1 C" + IntegerToString(chainNum + 1)))
               {
                  g_gzSellChainCount  = 1;
                  g_gzSellTotalOrders++;
                  g_gzLastSellEntry   = SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);

                  g_gzSellTrailActive = false;
                  g_gzSellPeakPrice   = DBL_MAX;
                  g_gzSellTrailSL     = 0;
                  g_gzSellBE          = 0;
                  GZ_SetSLOnSide(1, 0);
                  GZ_ForceRecalcAndSetSL(1);

                  Print("[GridZ] GAP RESET SELL | New chain | rise=", DoubleToString(riseFromAnchor, 2));
               }
            }
         }
         else
         {
            double riseFromLast = closeBar1 - g_gzLastSellEntry;

            if(riseFromLast >= thresholdAbs && sellAtCap)
            {
               GZ_OnCapHit(1, sellCount);
            }
            else if(riseFromLast >= thresholdAbs)
            {
               int chainLevel = g_gzSellChainCount + 1;
               double lot = GZ_CalcLot(chainLevel);
               int chainNum = (g_gzSellTotalOrders / InpGZ_GridChainSize) + 1;

               if(GZ_OpenOrder(ORDER_TYPE_SELL, lot, "GridZ S#" + IntegerToString(chainLevel) + " C" + IntegerToString(chainNum)))
               {
                  g_gzSellChainCount++;
                  g_gzSellTotalOrders++;
                  g_gzLastSellEntry = SymbolInfoDouble(g_gzSymbol, SYMBOL_BID);

                  g_gzSellTrailActive = false;
                  g_gzSellPeakPrice   = DBL_MAX;
                  g_gzSellTrailSL     = 0;
                  g_gzSellBE          = 0;
                  GZ_SetSLOnSide(1, 0);
                  GZ_ForceRecalcAndSetSL(1);

                  Print("[GridZ] GRID SELL #", g_gzSellChainCount, " C", chainNum,
                        " | lot=", DoubleToString(lot, 2));

                  if(g_gzSellChainCount >= InpGZ_GridChainSize)
                  {
                     g_gzSellInGap     = true;
                     g_gzSellGapAnchor = g_gzLastSellEntry;
                     Print("[GridZ] SELL CHAIN FULL → GAP MODE");
                  }
               }
            }
            else if(closeBar1 > g_gzLastSellEntry)
            {
               Print("[GridZ] Sell: rise=", DoubleToString(riseFromLast, 2),
                     " < th=", DoubleToString(thresholdAbs, 2), " | NO TRADE");
            }
         }
      }
   }

   //--- Dashboard
   int bc = 0, sc = 0;
   GZ_CountPositions(bc, sc);
   GZ_DrawDashboard(zscore, bc, sc);
}


// ╔═══════════════════════════════════════════════════════════════════╗
// ║                                                                   ║
// ║        ENGINE B — LEVANDO CASCADE MULTI-TF SAME-RISK v4.10        ║
// ║        Multi-TF Heikin-Ashi signal pockets, one trade at a time   ║
// ║        Cascade Manager + Recovery + Same-Risk Lot Anchor          ║
// ║                                                                   ║
// ╚═══════════════════════════════════════════════════════════════════╝

//+------------------------------------------------------------------+
//| AUTO STEP/TRAIL ENGINE — internal constants (NO inputs)          |
//| From the resulting ratio x:  InitSL = x*ATR, FinalSL = (x/2)*ATR,|
//| TP/step = (2x)*ATR.                                              |
//+------------------------------------------------------------------+
const int    LV_AUTO_AC_PERIOD   = 14;    // returns-autocorrelation lookback (closed bars)
const double LV_AUTO_BASE_RATIO  = 1.5;   // neutral step ratio when regime is flat
const double LV_AUTO_AC_SCALE    = 0.6;   // how strongly regime stretches the ratio
const bool   LV_AUTO_AC_INDIRECT = true;  // true: stronger regime -> wider gaps
const double LV_AUTO_AC_ALPHA    = 0.05;  // EMA smoothing on raw autocorrelation

// Engine B context + trade objects (used by Engine B only)
string         g_lvSymbol        = "";
double         g_lvPoint         = 0;
int            g_lvDigits        = 0;

CTrade         g_lvTrade;
CPositionInfo  g_lvPos;
COrderInfo     g_lvOrd;

bool           g_lvRecoveryEnabled = false;   // derived from InpLV_RecoveryGapPct > 0

//+------------------------------------------------------------------+
//| MULTI-TIMEFRAME SIGNAL POCKETS                                   |
//+------------------------------------------------------------------+
struct LV_TFSignal {
    ENUM_TIMEFRAMES tf;
    int             minutes;
    datetime        lastBarTime;
    int             atrHandle;
    double          currentATR;
    double          smoothedAC;
    bool            acInit;
    string          lastDir;
};

LV_TFSignal g_lvSig[];
int         g_lvTfCount   = 0;
int         g_lvAnchorIdx = 0;     // index of the HIGHEST timeframe (first-trade source)

//+------------------------------------------------------------------+
//| RISK / LOT ANCHOR STATE                                          |
//+------------------------------------------------------------------+
double   g_lvAnchorRiskMoney    = 0.0;   // equalised $ risk every trade targets
bool     g_lvAwaitingFirstTrade = true;  // first trade must come from the highest TF
string   g_lvAnchorFilePath;

//+------------------------------------------------------------------+
//| PENDING ENTRY CONTEXT (handed to LV_InitializeChain)             |
//+------------------------------------------------------------------+
bool     g_lvHaveEntryCtx = false;
int      g_lvEntryTFIdx   = -1;
double   g_lvEntryATR     = 0;
double   g_lvEntryInitM   = 0;
double   g_lvEntryFinalM  = 0;
double   g_lvEntryTPM     = 0;
double   g_lvEntryLot     = 0;

//+------------------------------------------------------------------+
//| CASCADE CHAIN STRUCTURE                                          |
//+------------------------------------------------------------------+
struct LV_CascadeChain {
    ulong          chainID;
    bool           isActive;
    ENUM_POSITION_TYPE direction;
    datetime       startTime;
    int            chainTFIndex;       // which signal pocket spawned this chain
    double         chainATR;
    double         chainLot;

    double         chainInitSLMult;
    double         chainFinalSLMult;
    double         chainTPMult;

    ulong          tickets[];
    double         entryPrices[];
    bool           positionActive[];
    int            currentLevel;
    double         currentSL;
    ulong          pendingTicket;
    double         pendingPrice;
    double         pendingOrderSL;

    double         levelEntryPrices[];
    double         levelThresholdPrices[];
    double         levelBreakevenSLs[];
    bool           levelBETriggered[];
    bool           needsSLSync;

    double         initialRiskMoney;
    double         recoveryGapPrice;
    double         nextRecoveryPrice;
    ulong          recoveryTickets[];
    bool           recoveryActive[];
    int            recoveryCount;
    bool           isRecovered;
};

LV_CascadeChain g_lvChains[];
int             g_lvTotalChains       = 0;
int             g_lvTickCounter       = 0;
int             g_lvLastPositionCount = 0;


// ── Engine B dashboard (chart labels, bottom-left) ─────────────────────

void LV_DrawLabel(string name, int x, int y, string text, color clr, int size) {
    if(ObjectFind(0, name) < 0) {
        ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
        ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_LOWER);
        ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
        ObjectSetString(0, name, OBJPROP_FONT, "Trebuchet MS");
        ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
        ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
    }
    ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
    ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
    ObjectSetString(0, name, OBJPROP_TEXT, text);
    ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
    ObjectSetInteger(0, name, OBJPROP_FONTSIZE, size);
}

void LV_UpdateDashboard() {
    if(!InpLV_ShowOnChart) return;

    bool   isFlat = LV_IsSystemFlat();
    string stateStr;
    color  stateClr;
    if(g_lvAwaitingFirstTrade) {
        stateStr = "AWAITING FIRST SIGNAL on " + TFToText(g_lvSig[g_lvAnchorIdx].tf) + " (anchor)";
        stateClr = clrAqua;
    } else if(isFlat) {
        stateStr = "FLAT — next signal from ANY TF will be taken";
        stateClr = clrLightGray;
    } else {
        stateStr = "ACTIVE — one trade running, new signals ignored";
        stateClr = clrOrange;
    }

    // Build TF list with last-direction summary
    string tfList = "";
    for(int i = 0; i < g_lvTfCount; i++) {
        string tag = TFToText(g_lvSig[i].tf);
        if(i == g_lvAnchorIdx) tag += "*";
        tfList += tag + "(" + g_lvSig[i].lastDir + ")";
        if(i < g_lvTfCount - 1) tfList += "  ";
    }

    // Active chain summary
    string chainStr = "—";
    for(int c = 0; c < g_lvTotalChains; c++) {
        if(g_lvChains[c].isActive) {
            chainStr = (g_lvChains[c].direction == POSITION_TYPE_BUY ? "BUY" : "SELL")
                     + " | src " + TFToText(g_lvSig[g_lvChains[c].chainTFIndex].tf)
                     + " | lvl " + IntegerToString(g_lvChains[c].currentLevel)
                     + " | lot " + DoubleToString(g_lvChains[c].chainLot, 2)
                     + " | rec " + IntegerToString(g_lvChains[c].recoveryCount);
            break;
        }
    }

    // y is measured UP from the bottom edge of the chart
    LV_DrawLabel("LVD_Title", 20, 110, "ZSCORE AND LEVANDO MIX  |  ENGINE B — LeVanDo Cascade Multi-TF Same-Risk v4.10  |  Asset: " + g_lvSymbol +
                                       "  |  Magic: " + IntegerToString(InpLV_MagicNumber),              clrGold,         12);
    LV_DrawLabel("LVD_State", 20, 88,  "System: " + stateStr,                                            stateClr,        10);
    LV_DrawLabel("LVD_TFs",   20, 68,  "Timeframes (*=anchor): " + tfList,                               clrWhite,        10);
    LV_DrawLabel("LVD_Risk",  20, 48,  "Risk%: " + DoubleToString(InpLV_RiskPercent, 2) +
                                       "  |  Anchor Risk $: " + DoubleToString(g_lvAnchorRiskMoney, 2) +
                                       "  |  Recovery: " + (g_lvRecoveryEnabled ? "ON" : "OFF"),
                                       clrLightSkyBlue, 10);
    LV_DrawLabel("LVD_Chain", 20, 28,  "Chain: " + chainStr,                                             clrLightSkyBlue, 10);
}

void LV_CleanDashboard() { ObjectsDeleteAll(0, "LVD_"); }


// ── Timeframe parser ────────────────────────────────────────────────────

ENUM_TIMEFRAMES LV_MinutesToTimeframe(int m) {
    int mins[]              = {1,2,3,4,5,6,10,12,15,20,30,60,120,180,240,360,480,720,1440,10080,43200};
    ENUM_TIMEFRAMES tfs[]   = {PERIOD_M1,PERIOD_M2,PERIOD_M3,PERIOD_M4,PERIOD_M5,PERIOD_M6,
                               PERIOD_M10,PERIOD_M12,PERIOD_M15,PERIOD_M20,PERIOD_M30,
                               PERIOD_H1,PERIOD_H2,PERIOD_H3,PERIOD_H4,PERIOD_H6,PERIOD_H8,
                               PERIOD_H12,PERIOD_D1,PERIOD_W1,PERIOD_MN1};
    int n = ArraySize(mins);
    for(int i = 0; i < n; i++) if(mins[i] == m) return tfs[i];          // exact match
    int bestI = 0, bestD = INT_MAX;                                      // else nearest valid TF
    for(int i = 0; i < n; i++) { int d = (int)MathAbs(mins[i] - m); if(d < bestD) { bestD = d; bestI = i; } }
    return tfs[bestI];
}

bool LV_ParseTimeframes() {
    string parts[];
    ushort sep = StringGetCharacter(",", 0);
    int n = StringSplit(InpLV_Timeframes, sep, parts);
    if(n <= 0) return false;

    g_lvTfCount = 0;
    ArrayResize(g_lvSig, 0);

    for(int i = 0; i < n; i++) {
        string s = parts[i];
        StringTrimLeft(s); StringTrimRight(s);
        if(StringLen(s) == 0) continue;
        int m = (int)StringToInteger(s);
        if(m <= 0) continue;
        ENUM_TIMEFRAMES tf = LV_MinutesToTimeframe(m);

        // de-duplicate
        bool dup = false;
        for(int k = 0; k < g_lvTfCount; k++) if(g_lvSig[k].tf == tf) { dup = true; break; }
        if(dup) continue;

        int idx = g_lvTfCount++;
        ArrayResize(g_lvSig, g_lvTfCount);
        g_lvSig[idx].tf          = tf;
        g_lvSig[idx].minutes     = (int)(PeriodSeconds(tf) / 60);
        g_lvSig[idx].lastBarTime = 0;
        g_lvSig[idx].atrHandle   = INVALID_HANDLE;
        g_lvSig[idx].currentATR  = 0;
        g_lvSig[idx].smoothedAC  = 0;
        g_lvSig[idx].acInit      = false;
        g_lvSig[idx].lastDir     = "—";
    }

    if(g_lvTfCount == 0) return false;

    // highest TF = largest period in seconds → anchor / first-trade source
    g_lvAnchorIdx = 0;
    int bestSec = PeriodSeconds(g_lvSig[0].tf);
    for(int i = 1; i < g_lvTfCount; i++) {
        int sec = PeriodSeconds(g_lvSig[i].tf);
        if(sec > bestSec) { bestSec = sec; g_lvAnchorIdx = i; }
    }
    return true;
}


// ── Autocorrelation regime estimator (per timeframe) ────────────────────

double LV_CalculateAutocorrelation(ENUM_TIMEFRAMES tf) {
    int length = (LV_AUTO_AC_PERIOD < 3) ? 3 : LV_AUTO_AC_PERIOD;
    double closes[];
    ArraySetAsSeries(closes, true);
    int needed = length + 2;
    if(CopyClose(g_lvSymbol, tf, 0, needed, closes) < needed) return 0.0;

    double ret[];
    ArrayResize(ret, length + 1);
    for(int i = 0; i <= length; i++) ret[i] = closes[i] - closes[i + 1];

    double sumY = 0, sumX = 0;
    for(int i = 0; i < length; i++) { sumY += ret[i]; sumX += ret[i + 1]; }
    double meanY = sumY / length, meanX = sumX / length;

    double sumXY = 0, sumX2 = 0, sumY2 = 0;
    for(int i = 0; i < length; i++) {
        double dy = ret[i] - meanY, dx = ret[i + 1] - meanX;
        sumXY += dx * dy; sumX2 += dx * dx; sumY2 += dy * dy;
    }
    double denom = MathSqrt(sumX2 * sumY2);
    if(denom == 0) return 0.0;
    double ac = sumXY / denom;
    return MathMax(-1.0, MathMin(1.0, ac));
}

void LV_UpdateTFAutocorrelation(int i) {
    double rawAC = LV_CalculateAutocorrelation(g_lvSig[i].tf);
    if(!g_lvSig[i].acInit) { g_lvSig[i].smoothedAC = rawAC; g_lvSig[i].acInit = true; }
    else g_lvSig[i].smoothedAC = LV_AUTO_AC_ALPHA * rawAC + (1.0 - LV_AUTO_AC_ALPHA) * g_lvSig[i].smoothedAC;
}

// Map the smoothed regime estimate to ATR multipliers. Fully automatic, asset-universal.
void LV_MultsFromAC(double smAC, double &initM, double &finalM, double &tpM) {
    double direction = LV_AUTO_AC_INDIRECT ? 1.0 : -1.0;
    double factor    = MathMax(0.2, 1.0 + direction * LV_AUTO_AC_SCALE * MathAbs(smAC));
    double x         = LV_AUTO_BASE_RATIO * factor;
    initM  = x;
    finalM = x / 2.0;
    tpM    = x * 2.0;
}


// ── Per-timeframe ATR + signal engine ───────────────────────────────────

void LV_RefreshAllATR() {
    double b[];
    ArraySetAsSeries(b, true);
    for(int i = 0; i < g_lvTfCount; i++) {
        if(g_lvSig[i].atrHandle == INVALID_HANDLE) continue;
        if(CopyBuffer(g_lvSig[i].atrHandle, 0, 0, 1, b) > 0) g_lvSig[i].currentATR = b[0];
    }
}

double LV_AnchorATR() { return (g_lvTfCount > 0) ? g_lvSig[g_lvAnchorIdx].currentATR : 0.0; }

// Build Heikin-Ashi over the last fully-CLOSED bars of a TF (non-repainting).
// Returns the latest closed HA bar (o1/c1 = shift 1) and the one before (o2/c2 = shift 2).
bool LV_GetClosedHA(ENUM_TIMEFRAMES tf, double &o1, double &c1, double &o2, double &c2) {
    MqlRates r[];
    ArraySetAsSeries(r, false);                 // chronological: r[0] oldest, r[3] = shift 1
    if(CopyRates(g_lvSymbol, tf, 1, 4, r) < 4) return false;
    double haO[4], haC[4];
    for(int k = 0; k < 4; k++) {
        haC[k] = (r[k].open + r[k].high + r[k].low + r[k].close) / 4.0;
        haO[k] = (k == 0) ? (r[k].open + r[k].close) / 2.0 : (haO[k-1] + haC[k-1]) / 2.0;
    }
    o1 = haO[3]; c1 = haC[3];                   // last closed bar (shift 1)
    o2 = haO[2]; c2 = haC[2];                   // bar before  (shift 2)
    return true;
}

// On a new bar of pocket i, refresh its AC and detect a Heikin-Ashi colour flip.
bool LV_DetectTFSignal(int i, bool &buy, bool &sell) {
    buy = false; sell = false;
    ENUM_TIMEFRAMES tf = g_lvSig[i].tf;
    datetime t0 = iTime(g_lvSymbol, tf, 0);
    if(t0 <= 0) return false;

    if(g_lvSig[i].lastBarTime == 0) { g_lvSig[i].lastBarTime = t0; return false; } // seed only
    if(t0 == g_lvSig[i].lastBarTime) return false;                                 // no new bar
    g_lvSig[i].lastBarTime = t0;                                                   // new bar formed

    LV_UpdateTFAutocorrelation(i);

    double o1, c1, o2, c2;
    if(!LV_GetClosedHA(tf, o1, c1, o2, c2)) return false;

    buy  = (c2 <= o2) && (c1 > o1);   // flipped to bullish on the just-closed bar
    sell = (c2 >= o2) && (c1 < o1);   // flipped to bearish on the just-closed bar

    if(buy)  g_lvSig[i].lastDir = "BULLISH";
    if(sell) g_lvSig[i].lastDir = "BEARISH";
    return (buy || sell);
}


// ── Same-risk lot engine ────────────────────────────────────────────────

int LV_LotDigits() {
    double step = SymbolInfoDouble(g_lvSymbol, SYMBOL_VOLUME_STEP);
    if(step <= 0) return 2;
    int d = (int)MathRound(-MathLog10(step));
    if(d < 0) d = 0;
    if(d > 8) d = 8;
    return d;
}

// Round to broker step and clamp to broker MIN/MAX only (no artificial user limits).
double LV_NormalizeLot(double lot) {
    double step = SymbolInfoDouble(g_lvSymbol, SYMBOL_VOLUME_STEP);
    double bmin = SymbolInfoDouble(g_lvSymbol, SYMBOL_VOLUME_MIN);
    double bmax = SymbolInfoDouble(g_lvSymbol, SYMBOL_VOLUME_MAX);
    if(step <= 0) step = 0.01;
    lot = MathFloor(lot / step) * step;
    if(lot < bmin) lot = bmin;
    if(bmax > 0 && lot > bmax) lot = bmax;
    return NormalizeDouble(lot, LV_LotDigits());
}

// Same-risk core: lot = riskMoney / ($ value of the initial-SL distance for 1.0 lot).
double LV_LotForSL(double slDistPrice, double riskMoney) {
    double tickValue = SymbolInfoDouble(g_lvSymbol, SYMBOL_TRADE_TICK_VALUE);
    double tickSize  = SymbolInfoDouble(g_lvSymbol, SYMBOL_TRADE_TICK_SIZE);
    double bmin      = SymbolInfoDouble(g_lvSymbol, SYMBOL_VOLUME_MIN);
    if(slDistPrice <= 0 || tickValue <= 0 || tickSize <= 0 || riskMoney <= 0) return bmin;
    double valuePerLot = (slDistPrice / tickSize) * tickValue;   // $ lost at SL for 1.0 lot
    if(valuePerLot <= 0) return bmin;
    return LV_NormalizeLot(riskMoney / valuePerLot);
}

double LV_FirstTradeRiskMoney() {
    double eq = AccountInfoDouble(ACCOUNT_EQUITY);
    return eq * InpLV_RiskPercent / 100.0;
}


// ── Anchor persistence ──────────────────────────────────────────────────

void LV_SaveAnchor() {
    int handle = FileOpen(g_lvAnchorFilePath, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
    if(handle == INVALID_HANDLE)
        handle = FileOpen(g_lvAnchorFilePath, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
    if(handle == INVALID_HANDLE) return;
    FileWrite(handle, "AnchorRiskMoney", DoubleToString(g_lvAnchorRiskMoney, 2));
    FileClose(handle);
}

double LV_LoadAnchor() {
    int handle = FileOpen(g_lvAnchorFilePath, FILE_READ | FILE_CSV | FILE_ANSI, ',');
    if(handle == INVALID_HANDLE)
        handle = FileOpen(g_lvAnchorFilePath, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
    if(handle == INVALID_HANDLE) return 0.0;
    double val = 0.0;
    if(!FileIsEnding(handle)) { FileReadString(handle); val = StringToDouble(FileReadString(handle)); }
    FileClose(handle);
    return (val > 0 ? val : 0.0);
}

int LV_CountMyPositions() {
    int count = 0;
    for(int i = PositionsTotal() - 1; i >= 0; i--) {
        if(PositionGetSymbol(i) == g_lvSymbol && PositionGetInteger(POSITION_MAGIC) == InpLV_MagicNumber) count++;
    }
    return count;
}


// ── Cascade manager helpers ─────────────────────────────────────────────

double LV_GetChainATR(int idx) {
    if(InpLV_UseStaticATR) return g_lvChains[idx].chainATR;
    int t = g_lvChains[idx].chainTFIndex;
    if(t >= 0 && t < g_lvTfCount && g_lvSig[t].currentATR > 0) return g_lvSig[t].currentATR;
    return g_lvChains[idx].chainATR;
}

double LV_CalcSLPrice(ENUM_POSITION_TYPE dir, double entry, double atr, double mult) {
    double d = atr * mult;
    return NormalizeDouble(dir == POSITION_TYPE_BUY ? entry - d : entry + d, g_lvDigits);
}

double LV_CalcNextCascadePrice(ENUM_POSITION_TYPE dir, double entry, double atr, double mult) {
    double d = atr * mult;
    return NormalizeDouble(dir == POSITION_TYPE_BUY ? entry + d : entry - d, g_lvDigits);
}

double LV_CalcBreakevenTriggerPrice(ENUM_POSITION_TYPE dir, double entry, double nextPrice, double pct) {
    double d = MathAbs(nextPrice - entry) * (pct / 100.0);
    return NormalizeDouble(dir == POSITION_TYPE_BUY ? entry + d : entry - d, g_lvDigits);
}

double LV_GetExitPrice(ENUM_POSITION_TYPE dir) {
    return SymbolInfoDouble(g_lvSymbol, dir == POSITION_TYPE_BUY ? SYMBOL_BID : SYMBOL_ASK);
}

bool LV_HasReachedBreakevenTrigger(ENUM_POSITION_TYPE dir, double current, double trigger) {
    return dir == POSITION_TYPE_BUY ? current >= trigger : current <= trigger;
}

ENUM_ORDER_TYPE LV_GetPendingOrderType(ENUM_POSITION_TYPE dir, double targetPrice) {
    if(dir == POSITION_TYPE_BUY)
        return targetPrice > SymbolInfoDouble(g_lvSymbol, SYMBOL_ASK) ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_BUY_LIMIT;
    return targetPrice < SymbolInfoDouble(g_lvSymbol, SYMBOL_BID) ? ORDER_TYPE_SELL_STOP : ORDER_TYPE_SELL_LIMIT;
}

bool LV_PositionExists(ulong ticket) { return g_lvPos.SelectByTicket(ticket); }
bool LV_OrderExists(ulong ticket)    {
    for(int i = 0; i < OrdersTotal(); i++) if(g_lvOrd.SelectByIndex(i) && g_lvOrd.Ticket() == ticket) return true;
    return false;
}

bool LV_ModifySL(ulong ticket, double newSL) {
    for(int attempt = 0; attempt < InpLV_MaxRetry; attempt++) {
        if(!g_lvPos.SelectByTicket(ticket)) return false;
        if(MathAbs(g_lvPos.StopLoss() - newSL) < g_lvPoint) return true;
        if(g_lvPos.Volume() <= 0) return false;
        ResetLastError();
        if(g_lvTrade.PositionModify(ticket, newSL, 0)) return true;
        int err = GetLastError(); if(err == 4753 || err == 4108 || err == 4756) return false;
        if(attempt < InpLV_MaxRetry - 1) Sleep(InpLV_RetryDelayMs);
    }
    return false;
}

void LV_UpdateAllChainSL(int idx, double newSL) {
    for(int i = 0; i <= g_lvChains[idx].currentLevel; i++) {
        if(g_lvChains[idx].positionActive[i]) {
            if(!LV_ModifySL(g_lvChains[idx].tickets[i], newSL) && !LV_PositionExists(g_lvChains[idx].tickets[i]))
                g_lvChains[idx].positionActive[i] = false;
        }
    }
    for(int i = 0; i < g_lvChains[idx].recoveryCount; i++) {
        if(g_lvChains[idx].recoveryActive[i]) {
            if(!LV_ModifySL(g_lvChains[idx].recoveryTickets[i], newSL) && !LV_PositionExists(g_lvChains[idx].recoveryTickets[i]))
                g_lvChains[idx].recoveryActive[i] = false;
        }
    }
    g_lvChains[idx].currentSL = newSL;
}

bool LV_PlacePendingOrder(int idx, double price, double sl) {
    price = NormalizeDouble(price, g_lvDigits); sl = NormalizeDouble(sl, g_lvDigits);
    ENUM_POSITION_TYPE dir = g_lvChains[idx].direction;
    string comment = "CASCADE_" + IntegerToString(g_lvChains[idx].chainID)
                   + "_L" + IntegerToString(g_lvChains[idx].currentLevel + 1);
    double lot = g_lvChains[idx].chainLot;
    for(int attempt = 0; attempt < InpLV_MaxRetry; attempt++) {
        ENUM_ORDER_TYPE ot = LV_GetPendingOrderType(dir, price);
        bool ok = false;
        ResetLastError();
        switch(ot) {
            case ORDER_TYPE_BUY_STOP:   ok = g_lvTrade.BuyStop  (lot, price, g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment); break;
            case ORDER_TYPE_BUY_LIMIT:  ok = g_lvTrade.BuyLimit (lot, price, g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment); break;
            case ORDER_TYPE_SELL_STOP:  ok = g_lvTrade.SellStop (lot, price, g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment); break;
            case ORDER_TYPE_SELL_LIMIT: ok = g_lvTrade.SellLimit(lot, price, g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment); break;
        }
        if(ok) { g_lvChains[idx].pendingTicket = g_lvTrade.ResultOrder(); g_lvChains[idx].pendingPrice = price; return true; }
        int err = GetLastError(); if(err == 4753 || err == 4756) return false;
        if(attempt < InpLV_MaxRetry - 1) Sleep(InpLV_RetryDelayMs);
    }
    return false;
}

bool LV_PlaceMarketOrder(bool isBuy, double lot, string comment) {
    for(int attempt = 0; attempt < InpLV_MaxRetry; attempt++) {
        ResetLastError();
        bool ok = isBuy ? g_lvTrade.Buy (lot, g_lvSymbol, SymbolInfoDouble(g_lvSymbol, SYMBOL_ASK), 0, 0, comment)
                        : g_lvTrade.Sell(lot, g_lvSymbol, SymbolInfoDouble(g_lvSymbol, SYMBOL_BID), 0, 0, comment);
        if(ok) return true;
        int err = GetLastError(); if(err == 4753 || err == 4756) return false;
        if(attempt < InpLV_MaxRetry - 1) Sleep(InpLV_RetryDelayMs);
    }
    return false;
}

bool LV_ClosePositionRetry(ulong ticket) {
    for(int attempt = 0; attempt < InpLV_MaxRetry; attempt++) {
        if(!LV_PositionExists(ticket)) return true;
        ResetLastError();
        if(g_lvTrade.PositionClose(ticket)) return true;
        int err = GetLastError(); if(err == 4753 || err == 4756) return false;
        if(attempt < InpLV_MaxRetry - 1) Sleep(InpLV_RetryDelayMs);
    }
    return false;
}

bool LV_DeleteOrderRetry(ulong ticket) {
    for(int attempt = 0; attempt < InpLV_MaxRetry; attempt++) {
        if(!LV_OrderExists(ticket)) return true;
        ResetLastError();
        if(g_lvTrade.OrderDelete(ticket)) return true;
        int err = GetLastError(); if(err == 4753 || err == 4756) return false;
        if(attempt < InpLV_MaxRetry - 1) Sleep(InpLV_RetryDelayMs);
    }
    return false;
}

bool LV_IsTicketInAnyChain(ulong ticket) {
    for(int c = 0; c < g_lvTotalChains; c++) {
        if(!g_lvChains[c].isActive) continue;
        for(int i = 0; i < ArraySize(g_lvChains[c].tickets);         i++) if(g_lvChains[c].tickets[i]         == ticket) return true;
        for(int i = 0; i < ArraySize(g_lvChains[c].recoveryTickets); i++) if(g_lvChains[c].recoveryTickets[i] == ticket) return true;
        if(g_lvChains[c].pendingTicket == ticket) return true;
    }
    return false;
}

bool LV_IsCascadeComment(string comment) {
    return StringFind(comment, "CASCADE_") == 0 || StringFind(comment, "RECOVERY_") == 0;
}


// ── Chain initializer ───────────────────────────────────────────────────

void LV_InitializeChain(ulong ticket) {
    if(!g_lvPos.SelectByTicket(ticket))        return;
    if(LV_IsCascadeComment(g_lvPos.Comment())) return;
    if(LV_IsTicketInAnyChain(ticket))          return;
    if(g_lvPos.Magic() != InpLV_MagicNumber)   return;

    // ── Resolve the ATR / multipliers / lot / source TF for this chain ──
    double atrUsed, initM, finalM, tpM, lotUsed;
    int    tfIdx;
    if(g_lvHaveEntryCtx) {
        // Context handed over by the signal that opened this position.
        tfIdx   = g_lvEntryTFIdx;
        atrUsed = g_lvEntryATR;
        initM   = g_lvEntryInitM;
        finalM  = g_lvEntryFinalM;
        tpM     = g_lvEntryTPM;
        lotUsed = g_lvEntryLot;
        g_lvHaveEntryCtx = false;               // consume
    } else {
        // Adoption fallback (manual trade / restart): use anchor TF context.
        tfIdx   = g_lvAnchorIdx;
        atrUsed = LV_AnchorATR();
        if(atrUsed <= 0) atrUsed = g_lvSig[g_lvAnchorIdx].currentATR;
        LV_UpdateTFAutocorrelation(g_lvAnchorIdx);
        LV_MultsFromAC(g_lvSig[g_lvAnchorIdx].smoothedAC, initM, finalM, tpM);
        lotUsed = g_lvPos.Volume();             // keep the position's real volume
    }
    if(atrUsed <= 0) return;                     // cannot manage without an ATR

    int idx = g_lvTotalChains++;
    ArrayResize(g_lvChains, g_lvTotalChains);

    g_lvChains[idx].chainID          = ticket;
    g_lvChains[idx].isActive         = true;
    g_lvChains[idx].direction        = g_lvPos.PositionType();
    g_lvChains[idx].startTime        = TimeCurrent();
    g_lvChains[idx].chainTFIndex     = tfIdx;
    g_lvChains[idx].chainATR         = atrUsed;
    g_lvChains[idx].chainLot         = lotUsed;
    g_lvChains[idx].currentLevel     = 0;
    g_lvChains[idx].pendingTicket    = 0;
    g_lvChains[idx].needsSLSync      = false;
    g_lvChains[idx].chainInitSLMult  = initM;
    g_lvChains[idx].chainFinalSLMult = finalM;
    g_lvChains[idx].chainTPMult      = tpM;
    g_lvChains[idx].recoveryCount    = 0;
    g_lvChains[idx].isRecovered      = false;

    ArrayResize(g_lvChains[idx].tickets,               1);
    ArrayResize(g_lvChains[idx].entryPrices,           1);
    ArrayResize(g_lvChains[idx].positionActive,        1);
    ArrayResize(g_lvChains[idx].levelEntryPrices,      1);
    ArrayResize(g_lvChains[idx].levelThresholdPrices,  1);
    ArrayResize(g_lvChains[idx].levelBreakevenSLs,     1);
    ArrayResize(g_lvChains[idx].levelBETriggered,      1);
    ArrayResize(g_lvChains[idx].recoveryTickets,       0);
    ArrayResize(g_lvChains[idx].recoveryActive,        0);

    g_lvChains[idx].tickets[0]          = ticket;
    g_lvChains[idx].entryPrices[0]      = g_lvPos.PriceOpen();
    g_lvChains[idx].positionActive[0]   = true;
    g_lvChains[idx].levelBETriggered[0] = false;

    double atr   = LV_GetChainATR(idx);
    double entry = g_lvChains[idx].entryPrices[0];
    ENUM_POSITION_TYPE dir = g_lvChains[idx].direction;

    double initialSL = LV_CalcSLPrice(dir, entry, atr, g_lvChains[idx].chainInitSLMult);
    g_lvChains[idx].currentSL = initialSL;
    if(InpLV_OverwriteSLTP || g_lvPos.StopLoss() == 0) LV_ModifySL(ticket, initialSL);

    // Risk reference for recovery / basket max-loss = the equalised anchor risk.
    double slDist = MathAbs(entry - initialSL);
    if(g_lvAnchorRiskMoney > 0) g_lvChains[idx].initialRiskMoney = g_lvAnchorRiskMoney;
    else {
        double tickValue = SymbolInfoDouble(g_lvSymbol, SYMBOL_TRADE_TICK_VALUE);
        double tickSize  = SymbolInfoDouble(g_lvSymbol, SYMBOL_TRADE_TICK_SIZE);
        g_lvChains[idx].initialRiskMoney = (tickSize > 0) ? (slDist / tickSize) * tickValue * g_lvChains[idx].chainLot : 10.0;
    }
    if(g_lvChains[idx].initialRiskMoney <= 0) g_lvChains[idx].initialRiskMoney = 10.0;

    // Recovery geometry — only meaningful when recovery is enabled (InpLV_RecoveryGapPct > 0).
    g_lvChains[idx].recoveryGapPrice  = slDist * (InpLV_RecoveryGapPct / 100.0);
    g_lvChains[idx].nextRecoveryPrice = dir == POSITION_TYPE_BUY
                                        ? entry - g_lvChains[idx].recoveryGapPrice
                                        : entry + g_lvChains[idx].recoveryGapPrice;

    double nextPrice = LV_CalcNextCascadePrice(dir, entry, atr, g_lvChains[idx].chainTPMult);
    double buf       = SymbolInfoInteger(g_lvSymbol, SYMBOL_TRADE_STOPS_LEVEL) * g_lvPoint;

    g_lvChains[idx].levelEntryPrices[0]     = entry;
    g_lvChains[idx].levelThresholdPrices[0] = LV_CalcBreakevenTriggerPrice(dir, entry, nextPrice, InpLV_BEThresholdPct);
    g_lvChains[idx].levelBreakevenSLs[0]    = NormalizeDouble(dir == POSITION_TYPE_BUY ? entry + buf : entry - buf, g_lvDigits);

    double pendingSL = LV_CalcSLPrice(dir, nextPrice, atr, g_lvChains[idx].chainFinalSLMult);
    g_lvChains[idx].pendingOrderSL = pendingSL;
    LV_PlacePendingOrder(idx, nextPrice, pendingSL);
}


// ── Recovery + breakeven + trail + cascade fill ─────────────────────────

bool LV_CloseEntireChain(int idx) {
    bool allClosed = true;
    for(int i = 0; i <= g_lvChains[idx].currentLevel; i++) {
        if(g_lvChains[idx].positionActive[i]) {
            if(LV_ClosePositionRetry(g_lvChains[idx].tickets[i])) g_lvChains[idx].positionActive[i] = false;
            else allClosed = false;
        }
    }
    for(int i = 0; i < g_lvChains[idx].recoveryCount; i++) {
        if(g_lvChains[idx].recoveryActive[i]) {
            if(LV_ClosePositionRetry(g_lvChains[idx].recoveryTickets[i])) g_lvChains[idx].recoveryActive[i] = false;
            else allClosed = false;
        }
    }
    if(g_lvChains[idx].pendingTicket > 0) {
        if(!LV_DeleteOrderRetry(g_lvChains[idx].pendingTicket)) allClosed = false;
        g_lvChains[idx].pendingTicket = 0;
    }
    return allClosed;
}

void LV_ProcessRecovery(int idx) {
    if(!g_lvChains[idx].isActive) return;

    double totalPnL    = 0;
    int    activeCount = 0;

    for(int i = 0; i <= g_lvChains[idx].currentLevel; i++) {
        if(g_lvChains[idx].positionActive[i] && g_lvPos.SelectByTicket(g_lvChains[idx].tickets[i])) {
            totalPnL += g_lvPos.Profit() + g_lvPos.Swap() + g_lvPos.Commission();
            activeCount++;
        }
    }
    for(int i = 0; i < g_lvChains[idx].recoveryCount; i++) {
        if(g_lvChains[idx].recoveryActive[i] && g_lvPos.SelectByTicket(g_lvChains[idx].recoveryTickets[i])) {
            totalPnL += g_lvPos.Profit() + g_lvPos.Swap() + g_lvPos.Commission();
            activeCount++;
        }
    }
    if(activeCount == 0) return;

    // Basket max-loss kill switch — stays active regardless of the recovery toggle.
    if(totalPnL <= -g_lvChains[idx].initialRiskMoney) { LV_CloseEntireChain(idx); return; }

    // Recovery feature fully OFF when InpLV_RecoveryGapPct <= 0 → no averaging-in, no resume.
    if(!g_lvRecoveryEnabled) return;

    // Recovery reached target profit → resume cascade
    if(!g_lvChains[idx].isRecovered && g_lvChains[idx].recoveryCount > 0
       && totalPnL >= g_lvChains[idx].initialRiskMoney) {
        g_lvChains[idx].isRecovered = true;
        ENUM_POSITION_TYPE dir = g_lvChains[idx].direction;
        double atr = LV_GetChainATR(idx);
        if(g_lvChains[idx].pendingTicket > 0) { LV_DeleteOrderRetry(g_lvChains[idx].pendingTicket); g_lvChains[idx].pendingTicket = 0; }
        double refPrice  = g_lvChains[idx].entryPrices[g_lvChains[idx].currentLevel];
        double nextPrice = LV_CalcNextCascadePrice(dir, refPrice, atr, g_lvChains[idx].chainTPMult);
        double pendingSL = LV_CalcSLPrice(dir, nextPrice, atr, g_lvChains[idx].chainFinalSLMult);
        g_lvChains[idx].pendingOrderSL = pendingSL;
        LV_PlacePendingOrder(idx, nextPrice, pendingSL);
        return;
    }

    // Trigger new recovery position
    if(!g_lvChains[idx].isRecovered) {
        ENUM_POSITION_TYPE dir    = g_lvChains[idx].direction;
        double             price  = LV_GetExitPrice(dir);
        bool triggered = (dir == POSITION_TYPE_BUY)
                         ? price <= g_lvChains[idx].nextRecoveryPrice
                         : price >= g_lvChains[idx].nextRecoveryPrice;
        bool withinSL  = (dir == POSITION_TYPE_BUY)
                         ? price > g_lvChains[idx].currentSL
                         : price < g_lvChains[idx].currentSL;

        if(triggered && withinSL) {
            string comment = "RECOVERY_" + IntegerToString(g_lvChains[idx].chainID)
                           + "_R" + IntegerToString(g_lvChains[idx].recoveryCount + 1);
            bool ok = false;
            for(int attempt = 0; attempt < InpLV_MaxRetry; attempt++) {
                if(dir == POSITION_TYPE_BUY) ok = g_lvTrade.Buy (g_lvChains[idx].chainLot, g_lvSymbol, SymbolInfoDouble(g_lvSymbol, SYMBOL_ASK), g_lvChains[idx].currentSL, 0, comment);
                else                         ok = g_lvTrade.Sell(g_lvChains[idx].chainLot, g_lvSymbol, SymbolInfoDouble(g_lvSymbol, SYMBOL_BID), g_lvChains[idx].currentSL, 0, comment);
                if(ok) break;
                Sleep(InpLV_RetryDelayMs);
            }
            if(ok) {
                int rIdx = g_lvChains[idx].recoveryCount++;
                ArrayResize(g_lvChains[idx].recoveryTickets, g_lvChains[idx].recoveryCount);
                ArrayResize(g_lvChains[idx].recoveryActive,  g_lvChains[idx].recoveryCount);
                g_lvChains[idx].recoveryTickets[rIdx] = g_lvTrade.ResultOrder();
                g_lvChains[idx].recoveryActive[rIdx]  = true;
                g_lvChains[idx].nextRecoveryPrice += (dir == POSITION_TYPE_BUY)
                                                     ? -g_lvChains[idx].recoveryGapPrice
                                                     :  g_lvChains[idx].recoveryGapPrice;
            }
        }
    }
}

void LV_UpdatePendingOrderSL(int idx, double newSL) {
    if(g_lvChains[idx].pendingTicket == 0) return;
    if(!LV_OrderExists(g_lvChains[idx].pendingTicket)) { g_lvChains[idx].pendingTicket = 0; return; }
    ENUM_POSITION_TYPE dir = g_lvChains[idx].direction;
    bool needsUpdate = (dir == POSITION_TYPE_BUY) ? newSL > g_lvChains[idx].pendingOrderSL
                                                   : newSL < g_lvChains[idx].pendingOrderSL;
    if(!needsUpdate) return;
    ulong oldTicket   = g_lvChains[idx].pendingTicket;
    double orderPrice = g_lvChains[idx].pendingPrice;
    if(!LV_DeleteOrderRetry(oldTicket)) return;
    g_lvChains[idx].pendingTicket  = 0;
    g_lvChains[idx].pendingOrderSL = newSL;
    LV_PlacePendingOrder(idx, orderPrice, newSL);
}

void LV_ProcessBreakeven(int idx) {
    if(!InpLV_EnableFirstBE && !InpLV_EnableEveryCascadeBE) return;
    if(g_lvChains[idx].pendingTicket == 0) return;
    int level = InpLV_EnableEveryCascadeBE ? g_lvChains[idx].currentLevel : 0;
    if(g_lvChains[idx].levelBETriggered[level]) return;
    if(!g_lvChains[idx].positionActive[level])  return;
    if(!LV_PositionExists(g_lvChains[idx].tickets[level])) { g_lvChains[idx].positionActive[level] = false; return; }

    ENUM_POSITION_TYPE dir = g_lvChains[idx].direction;
    if(LV_HasReachedBreakevenTrigger(dir, LV_GetExitPrice(dir), g_lvChains[idx].levelThresholdPrices[level])) {
        double beSL = g_lvChains[idx].levelBreakevenSLs[level];
        LV_UpdateAllChainSL(idx, beSL);
        g_lvChains[idx].levelBETriggered[level] = true;
        LV_UpdatePendingOrderSL(idx, beSL);
    }
}

void LV_ManageTrailingStop(int idx) {
    if(!InpLV_EnableTrail || !g_lvChains[idx].isActive) return;
    ENUM_POSITION_TYPE dir  = g_lvChains[idx].direction;
    double currentPrice     = LV_GetExitPrice(dir);
    double trailStep        = LV_GetChainATR(idx) * g_lvChains[idx].chainFinalSLMult;
    if(dir == POSITION_TYPE_BUY) {
        double newSL = NormalizeDouble(currentPrice - trailStep, g_lvDigits);
        if(newSL > g_lvChains[idx].currentSL + g_lvPoint) LV_UpdateAllChainSL(idx, newSL);
    } else {
        double newSL = NormalizeDouble(currentPrice + trailStep, g_lvDigits);
        if(newSL < g_lvChains[idx].currentSL - g_lvPoint || g_lvChains[idx].currentSL == 0) LV_UpdateAllChainSL(idx, newSL);
    }
}

void LV_ProcessCascadeFill(int idx) {
    if(g_lvChains[idx].pendingTicket == 0) return;
    ulong pt = g_lvChains[idx].pendingTicket;
    if(LV_PositionExists(pt)) {
        int newLevel = g_lvChains[idx].currentLevel + 1;
        ArrayResize(g_lvChains[idx].tickets,              newLevel + 1);
        ArrayResize(g_lvChains[idx].entryPrices,          newLevel + 1);
        ArrayResize(g_lvChains[idx].positionActive,       newLevel + 1);
        ArrayResize(g_lvChains[idx].levelEntryPrices,     newLevel + 1);
        ArrayResize(g_lvChains[idx].levelThresholdPrices, newLevel + 1);
        ArrayResize(g_lvChains[idx].levelBreakevenSLs,    newLevel + 1);
        ArrayResize(g_lvChains[idx].levelBETriggered,     newLevel + 1);

        g_lvPos.SelectByTicket(pt);
        double newEntry = g_lvPos.PriceOpen();
        g_lvChains[idx].tickets[newLevel]            = pt;
        g_lvChains[idx].entryPrices[newLevel]        = newEntry;
        g_lvChains[idx].positionActive[newLevel]     = true;
        g_lvChains[idx].currentLevel                 = newLevel;
        g_lvChains[idx].pendingTicket                = 0;
        g_lvChains[idx].needsSLSync                  = true;
        g_lvChains[idx].levelBETriggered[newLevel]   = false;

        double atr  = LV_GetChainATR(idx);
        ENUM_POSITION_TYPE dir = g_lvChains[idx].direction;
        double newSL = LV_CalcSLPrice(dir, newEntry, atr, g_lvChains[idx].chainFinalSLMult);
        LV_UpdateAllChainSL(idx, newSL);

        double nextPrice = LV_CalcNextCascadePrice(dir, newEntry, atr, g_lvChains[idx].chainTPMult);
        double buf       = SymbolInfoInteger(g_lvSymbol, SYMBOL_TRADE_STOPS_LEVEL) * g_lvPoint;
        g_lvChains[idx].levelEntryPrices[newLevel]     = newEntry;
        g_lvChains[idx].levelThresholdPrices[newLevel] = LV_CalcBreakevenTriggerPrice(dir, newEntry, nextPrice, InpLV_BEThresholdPct);
        g_lvChains[idx].levelBreakevenSLs[newLevel]    = NormalizeDouble(dir == POSITION_TYPE_BUY ? newEntry + buf : newEntry - buf, g_lvDigits);

        double pendingSL = LV_CalcSLPrice(dir, nextPrice, atr, g_lvChains[idx].chainFinalSLMult);
        g_lvChains[idx].pendingOrderSL = pendingSL;
        LV_PlacePendingOrder(idx, nextPrice, pendingSL);
    }
    else if(!LV_OrderExists(pt)) {
        g_lvChains[idx].pendingTicket  = 0;
        g_lvChains[idx].pendingOrderSL = 0;
    }
}

void LV_SyncNewCascadeSL(int idx) {
    if(!g_lvChains[idx].needsSLSync) return;
    g_lvChains[idx].needsSLSync = false;
    ulong ticket = g_lvChains[idx].tickets[g_lvChains[idx].currentLevel];
    if(!LV_PositionExists(ticket)) return;
    if(MathAbs(g_lvPos.StopLoss() - g_lvChains[idx].currentSL) > g_lvPoint) LV_ModifySL(ticket, g_lvChains[idx].currentSL);
}

void LV_ProcessChainTermination(int idx) {
    int active = 0, closed = 0;
    for(int i = 0; i <= g_lvChains[idx].currentLevel; i++) {
        if(g_lvChains[idx].positionActive[i]) {
            if(LV_PositionExists(g_lvChains[idx].tickets[i])) active++;
            else { g_lvChains[idx].positionActive[i] = false; closed++; }
        }
    }
    for(int i = 0; i < g_lvChains[idx].recoveryCount; i++) {
        if(g_lvChains[idx].recoveryActive[i]) {
            if(LV_PositionExists(g_lvChains[idx].recoveryTickets[i])) active++;
            else { g_lvChains[idx].recoveryActive[i] = false; closed++; }
        }
    }
    if(closed > 0 && active > 0) { if(LV_CloseEntireChain(idx)) g_lvChains[idx].isActive = false; }
    else if(active == 0) {
        if(g_lvChains[idx].pendingTicket > 0) {
            if(LV_DeleteOrderRetry(g_lvChains[idx].pendingTicket))
                g_lvChains[idx].pendingTicket = 0;
        }
        g_lvChains[idx].isActive = false;
    }
}

void LV_ManageChains() {
    for(int c = 0; c < g_lvTotalChains; c++) {
        if(!g_lvChains[c].isActive) continue;
        LV_ProcessRecovery(c);
        LV_ProcessCascadeFill(c);
        LV_SyncNewCascadeSL(c);
        LV_ProcessBreakeven(c);
        LV_ManageTrailingStop(c);
        LV_ProcessChainTermination(c); // every tick — catch SL/TP hits immediately
    }
}


// ── System state helpers ────────────────────────────────────────────────

void LV_PurgeOrphanedPendingOrders() {
    for(int c = 0; c < g_lvTotalChains; c++) {
        if(g_lvChains[c].pendingTicket == 0) continue;
        int active = 0;
        for(int i = 0; i <= g_lvChains[c].currentLevel; i++)
            if(g_lvChains[c].positionActive[i] && LV_PositionExists(g_lvChains[c].tickets[i])) active++;
        for(int i = 0; i < g_lvChains[c].recoveryCount; i++)
            if(g_lvChains[c].recoveryActive[i] && LV_PositionExists(g_lvChains[c].recoveryTickets[i])) active++;
        if(active == 0) {
            if(LV_DeleteOrderRetry(g_lvChains[c].pendingTicket))
                g_lvChains[c].pendingTicket = 0;
            g_lvChains[c].isActive = false;
        }
    }
}

// True only when Engine B is genuinely flat: no live positions, no pending orders
// (its own asset + its own magic only). The single gate for "one trade at a time".
bool LV_IsSystemFlat() {
    if(LV_CountMyPositions() > 0) return false;
    LV_PurgeOrphanedPendingOrders();
    for(int i = 0; i < OrdersTotal(); i++) {
        if(g_lvOrd.SelectByIndex(i) && g_lvOrd.Magic() == InpLV_MagicNumber && g_lvOrd.Symbol() == g_lvSymbol) return false;
    }
    for(int c = 0; c < g_lvTotalChains; c++) g_lvChains[c].isActive = false;
    return true;
}

void LV_CleanFlatState() {
    for(int i = OrdersTotal() - 1; i >= 0; i--) {
        if(g_lvOrd.SelectByIndex(i) && g_lvOrd.Symbol() == g_lvSymbol && g_lvOrd.Magic() == InpLV_MagicNumber)
            LV_DeleteOrderRetry(g_lvOrd.Ticket());
    }
    for(int c = 0; c < g_lvTotalChains; c++) {
        g_lvChains[c].pendingTicket = 0;
        g_lvChains[c].isActive      = false;
    }
}

void LV_ScanForNewTrades() {
    for(int i = PositionsTotal() - 1; i >= 0; i--) {
        if(!g_lvPos.SelectByIndex(i)) continue;
        if(g_lvPos.Symbol() != g_lvSymbol || g_lvPos.Magic() != InpLV_MagicNumber) continue;
        ulong ticket = g_lvPos.Ticket();
        if(LV_IsTicketInAnyChain(ticket) || LV_IsCascadeComment(g_lvPos.Comment())) continue;

        // Attach to an existing active chain of the same direction, else open a new chain.
        int existingIdx = -1;
        for(int c = 0; c < g_lvTotalChains; c++) {
            if(g_lvChains[c].isActive && g_lvChains[c].direction == g_lvPos.PositionType()) { existingIdx = c; break; }
        }
        if(existingIdx >= 0) {
            int rIdx = g_lvChains[existingIdx].recoveryCount++;
            ArrayResize(g_lvChains[existingIdx].recoveryTickets, g_lvChains[existingIdx].recoveryCount);
            ArrayResize(g_lvChains[existingIdx].recoveryActive,  g_lvChains[existingIdx].recoveryCount);
            g_lvChains[existingIdx].recoveryTickets[rIdx] = ticket;
            g_lvChains[existingIdx].recoveryActive[rIdx]  = true;
            if(InpLV_OverwriteSLTP || g_lvPos.StopLoss() == 0) LV_ModifySL(ticket, g_lvChains[existingIdx].currentSL);
        } else {
            LV_InitializeChain(ticket);
        }
    }
}


// ── Signal → entry decision ─────────────────────────────────────────────

// Evaluate every pocket on its own new bar. Always refresh state so flips
// during an active trade aren't acted on (they "expire"); only flips that
// occur while flat are taken. First trade after init must be the anchor TF.
void LV_EvaluateSignals() {
    bool flat = LV_IsSystemFlat();
    bool placedThisTick = false;

    for(int i = 0; i < g_lvTfCount; i++) {
        bool buy, sell;
        bool fired = LV_DetectTFSignal(i, buy, sell);   // also advances bar state + AC
        if(!fired || placedThisTick) continue;
        if(!flat) continue;                             // one trade at a time — ignore
        if(g_lvAwaitingFirstTrade && i != g_lvAnchorIdx) continue; // first trade = highest TF only

        double atr = g_lvSig[i].currentATR;
        if(atr <= 0) continue;

        double initM, finalM, tpM;
        LV_MultsFromAC(g_lvSig[i].smoothedAC, initM, finalM, tpM);

        double slDist = atr * initM;
        double riskMoney = g_lvAwaitingFirstTrade
                           ? LV_FirstTradeRiskMoney()                                          // 1st trade: risk %
                           : (g_lvAnchorRiskMoney > 0 ? g_lvAnchorRiskMoney : LV_FirstTradeRiskMoney()); // rest: anchor $
        double lot = LV_LotForSL(slDist, riskMoney);

        // hand context to LV_InitializeChain
        g_lvHaveEntryCtx = true;
        g_lvEntryTFIdx   = i;
        g_lvEntryATR     = atr;
        g_lvEntryInitM   = initM;
        g_lvEntryFinalM  = finalM;
        g_lvEntryTPM     = tpM;
        g_lvEntryLot     = lot;

        LV_CleanFlatState();   // safety-purge any leftover orders/flags before opening
        bool ok = LV_PlaceMarketOrder(buy, lot, InpLV_Comment + "|TF" + IntegerToString(g_lvSig[i].minutes));
        if(ok) {
            if(g_lvAwaitingFirstTrade) {
                g_lvAnchorRiskMoney    = riskMoney;   // freeze the equalised $ risk
                LV_SaveAnchor();
                g_lvAwaitingFirstTrade = false;
            }
            LV_ScanForNewTrades();                    // adopt + cascade immediately
            g_lvLastPositionCount = LV_CountMyPositions();
            placedThisTick = true;
            flat = false;
        } else {
            g_lvHaveEntryCtx = false;                 // discard context on failure
        }
    }
}


// ── Engine B init / deinit / one pass ───────────────────────────────────

bool LV_Init() {
    g_lvPoint  = SymbolInfoDouble(g_lvSymbol, SYMBOL_POINT);
    g_lvDigits = (int)SymbolInfoInteger(g_lvSymbol, SYMBOL_DIGITS);
    if(g_lvPoint <= 0) {
        MixFail("[LeVanDo] cannot read symbol properties for '" + g_lvSymbol + "'.");
        return false;
    }

    g_lvTrade.SetExpertMagicNumber(InpLV_MagicNumber);
    g_lvTrade.SetDeviationInPoints(10);
    g_lvTrade.SetTypeFilling(ORDER_FILLING_RETURN);
    g_lvTrade.SetAsyncMode(false);

    g_lvRecoveryEnabled = (InpLV_RecoveryGapPct > 0.0);

    if(!LV_ParseTimeframes()) {
        MixFail("[LeVanDo] timeframes input parsed to zero valid timeframes — e.g. \"30,60,120,240\"");
        return false;
    }

    for(int i = 0; i < g_lvTfCount; i++) {
        g_lvSig[i].atrHandle = iATR(g_lvSymbol, g_lvSig[i].tf, InpLV_ATRPeriod);
        if(g_lvSig[i].atrHandle == INVALID_HANDLE) {
            MixFail("[LeVanDo] iATR handle failed for " + TFToText(g_lvSig[i].tf));
            return false;
        }
    }

    Sleep(100);
    LV_RefreshAllATR();

    // Seed bar times + AC for each pocket (no signals on the seeding pass).
    for(int i = 0; i < g_lvTfCount; i++) {
        g_lvSig[i].lastBarTime = iTime(g_lvSymbol, g_lvSig[i].tf, 0);
        LV_UpdateTFAutocorrelation(i);
    }

    g_lvAnchorFilePath = InpLV_FileName + "_" + g_lvSymbol + ".csv";
    if(InpLV_ResetAnchor) FileDelete(g_lvAnchorFilePath);
    g_lvAnchorRiskMoney = LV_LoadAnchor();

    // Adopt anything already open, then decide first-trade state.
    g_lvLastPositionCount = LV_CountMyPositions();
    LV_ScanForNewTrades();

    if(LV_IsSystemFlat()) {
        g_lvAwaitingFirstTrade = true;            // next trade must be the highest TF; it re-anchors risk
    } else {
        g_lvAwaitingFirstTrade = false;
        if(g_lvAnchorRiskMoney <= 0) { g_lvAnchorRiskMoney = LV_FirstTradeRiskMoney(); LV_SaveAnchor(); }
    }

    LV_UpdateDashboard();

    string tfTxt = "";
    for(int i = 0; i < g_lvTfCount; i++) tfTxt += TFToText(g_lvSig[i].tf) + (i < g_lvTfCount-1 ? "," : "");
    Print("ENGINE B: LeVanDo Multi-TF v4.10 ready. Asset: ", g_lvSymbol,
          " | Timeframes: ", tfTxt,
          " | Anchor TF: ", TFToText(g_lvSig[g_lvAnchorIdx].tf),
          " | Anchor risk $: ", DoubleToString(g_lvAnchorRiskMoney, 2),
          " | Recovery: ", (g_lvRecoveryEnabled ? "ON" : "OFF"),
          " | Magic=", InpLV_MagicNumber);
    return true;
}

void LV_Deinit() {
    for(int i = 0; i < g_lvTfCount; i++) {
        if(g_lvSig[i].atrHandle != INVALID_HANDLE) {
            IndicatorRelease(g_lvSig[i].atrHandle);
            g_lvSig[i].atrHandle = INVALID_HANDLE;
        }
    }
    LV_CleanDashboard();
}

// One pass of Engine B (called on every tick of ITS asset)
void LV_Process() {
    g_lvTickCounter++;
    LV_RefreshAllATR(); // every tick for SL/TP distance accuracy

    // ── Position-change gate: adopt new trades / purge orphans on count change ──
    int currentPositions = LV_CountMyPositions();
    if(currentPositions != g_lvLastPositionCount) {
        if(currentPositions < g_lvLastPositionCount) LV_PurgeOrphanedPendingOrders();
        g_lvLastPositionCount = currentPositions;
        LV_ScanForNewTrades();
    }

    // ── Multi-TF signal evaluation (per-pocket new-bar gating inside) ──
    LV_EvaluateSignals();

    // ── Chain management (every tick) ──
    LV_ManageChains();

    // ── Dashboard (throttled) ──
    if(g_lvTickCounter % 5 == 0) LV_UpdateDashboard();
}


// ╔═══════════════════════════════════════════════════════════════════╗
// ║                     EXPERT EVENT HANDLERS                         ║
// ╚═══════════════════════════════════════════════════════════════════╝

int OnInit()
{
   if(!InpGZ_Enable && !InpLV_Enable)
   {
      MixFail("both engines are disabled — enable at least one.");
      return INIT_PARAMETERS_INCORRECT;
   }

   //--- Resolve each engine's asset first
   if(InpGZ_Enable && !ResolveSymbol(InpGZ_Symbol, "GridZ",   g_gzSymbol)) return INIT_PARAMETERS_INCORRECT;
   if(InpLV_Enable && !ResolveSymbol(InpLV_Symbol, "LeVanDo", g_lvSymbol)) return INIT_PARAMETERS_INCORRECT;

   //--- Isolation guard: on the same asset the two engines MUST have different magics
   if(InpGZ_Enable && InpLV_Enable && g_gzSymbol == g_lvSymbol)
   {
      if(InpGZ_Magic == InpLV_MagicNumber)
      {
         MixFail("both engines trade " + g_gzSymbol + " with the SAME magic number. " +
                   "Give each engine its own magic so they cannot touch each other's trades.");
         return INIT_PARAMETERS_INCORRECT;
      }
      if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
         Print("Zscore and Levando MIX WARNING: this is not a hedging account. Both engines trade ", g_gzSymbol,
               " — on a netting account their positions merge into one and the engines cannot stay separate.");
   }

   //--- Start engines
   if(InpGZ_Enable && !GZ_Init()) return INIT_FAILED;
   if(InpLV_Enable && !LV_Init()) return INIT_FAILED;

   //--- An engine on the chart's own asset runs from OnTick (exactly like the standalone EA).
   //    An engine on a different asset runs from a fast timer, once per new quote of its asset.
   g_gzOnTimer = (InpGZ_Enable && g_gzSymbol != _Symbol);
   g_lvOnTimer = (InpLV_Enable && g_lvSymbol != _Symbol);
   if(g_gzOnTimer || g_lvOnTimer) EventSetMillisecondTimer(200);

   Print("Zscore and Levando MIX ready | Engine A (GridZ): ",
         (InpGZ_Enable ? g_gzSymbol + " " + TFToText(g_gzTF) + (g_gzOnTimer ? " [timer]" : " [chart ticks]") : "OFF"),
         " | Engine B (LeVanDo): ",
         (InpLV_Enable ? g_lvSymbol + " " + InpLV_Timeframes + (g_lvOnTimer ? " [timer]" : " [chart ticks]") : "OFF"));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   GZ_Deinit();
   LV_Deinit();
}

void OnTick()
{
   if(InpGZ_Enable && !g_gzOnTimer) GZ_Process();
   if(InpLV_Enable && !g_lvOnTimer) LV_Process();
}

void OnTimer()
{
   if(InpGZ_Enable && g_gzOnTimer && IsNewQuote(g_gzSymbol, g_gzQuoteMsc, g_gzQuoteBid, g_gzQuoteAsk)) GZ_Process();
   if(InpLV_Enable && g_lvOnTimer && IsNewQuote(g_lvSymbol, g_lvQuoteMsc, g_lvQuoteBid, g_lvQuoteAsk)) LV_Process();
}

//+------------------------------------------------------------------+
//| Strategy Tester custom criterion (from Grid Z-Score): profit/DD  |
//+------------------------------------------------------------------+
double OnTester()
{
   double profit = TesterStatistics(STAT_PROFIT);
   double dd     = TesterStatistics(STAT_EQUITY_DDREL_PERCENT);
   if(dd < 0.01) dd = 0.01;
   return profit / dd;
}
//+------------------------------------------------------------------+
