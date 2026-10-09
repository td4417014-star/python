"""Zscore and Levando MIX v1.10 - line-by-line port of experts/Zscore_and_Levando_MIX.mq5.

Every MQL5 function keeps its name and statement order; MQL globals are
attributes on ``self`` (same names). Inputs are read automatically from the
.mq5 file, so ``self.InpGZ_ZscorePeriod`` etc. always match the EA.

Only intentional deviations (none change trading decisions):
* chart drawing (Comment / labels) is skipped unless VISUAL=True; the
  side-effecting call inside LV_UpdateDashboard (LV_IsSystemFlat) is kept;
* loops over the ever-growing g_lvChains array visit only chains that can
  still be affected (active or holding a pending order) - identical result,
  but O(live chains) instead of O(all chains ever opened) per tick.
"""
from __future__ import annotations

import math

from ubt.mql5 import *          # noqa: F401,F403  MQL5 API emulation
from ubt.strategy import Strategy

# ENUMS (ENGINE A)
GZ_LOT_FIXED, GZ_LOT_RISK_PCT = 0, 1
GZ_TRAIL_SLOWEST, GZ_TRAIL_SLOWER, GZ_TRAIL_SLOW, GZ_TRAIL_FAST, GZ_TRAIL_FASTER, GZ_TRAIL_FASTEST = range(6)
GZ_GAP_FIXED_PCT, GZ_GAP_VOLATILITY = 0, 1
GZ_CAP_OUT, GZ_CAP_HOLD = 0, 1

# AUTO STEP/TRAIL ENGINE constants (Engine B)
LV_AUTO_AC_PERIOD = 14
LV_AUTO_BASE_RATIO = 1.5
LV_AUTO_AC_SCALE = 0.6
LV_AUTO_AC_INDIRECT = True
LV_AUTO_AC_ALPHA = 0.05


class GZ_TrailConfig:
    __slots__ = ("triggerSpreads", "trailDistSpreads", "ratchetFraction", "minLockSpreads")


class LV_TFSignal:
    def __init__(self):
        self.tf = 0
        self.minutes = 0
        self.lastBarTime = 0
        self.atrHandle = INVALID_HANDLE
        self.currentATR = 0.0
        self.smoothedAC = 0.0
        self.acInit = False
        self.lastDir = "—"


class LV_CascadeChain:
    def __init__(self):
        self.chainID = 0
        self.isActive = False
        self.direction = 0
        self.startTime = 0
        self.chainTFIndex = 0
        self.chainATR = 0.0
        self.chainLot = 0.0
        self.chainInitSLMult = 0.0
        self.chainFinalSLMult = 0.0
        self.chainTPMult = 0.0
        self.tickets = []
        self.entryPrices = []
        self.positionActive = []
        self.currentLevel = 0
        self.currentSL = 0.0
        self.pendingTicket = 0
        self.pendingPrice = 0.0
        self.pendingOrderSL = 0.0
        self.levelEntryPrices = []
        self.levelThresholdPrices = []
        self.levelBreakevenSLs = []
        self.levelBETriggered = []
        self.needsSLSync = False
        self.initialRiskMoney = 0.0
        self.recoveryGapPrice = 0.0
        self.nextRecoveryPrice = 0.0
        self.recoveryTickets = []
        self.recoveryActive = []
        self.recoveryCount = 0
        self.isRecovered = False


def _resize(arr, n, fill):
    if len(arr) < n:
        arr.extend([fill] * (n - len(arr)))
    else:
        del arr[n:]


def TFToText(tf):
    return TIMEFRAME_NAMES.get(tf, str(tf))


class ZscoreLevandoMix(Strategy):
    MQ5_FILE = "../experts/Zscore_and_Levando_MIX.mq5"
    VISUAL = False

    def __init__(self, inputs=None):
        super().__init__(inputs)
        # shared
        self.g_gzOnTimer = False
        self.g_lvOnTimer = False
        self.g_gzQuoteMsc = 0
        self.g_gzQuoteBid = 0.0
        self.g_gzQuoteAsk = 0.0
        self.g_lvQuoteMsc = 0
        self.g_lvQuoteBid = 0.0
        self.g_lvQuoteAsk = 0.0
        # Engine A context
        self.g_gzSymbol = ""
        self.g_gzTF = PERIOD_M5
        self.g_gzPoint = 0.0
        self.g_gzDigits = 0
        self.g_gzHandleMA = INVALID_HANDLE
        self.g_gzHandleStd = INVALID_HANDLE
        self.g_gzLastBarTime = 0
        self.g_gzTickCounter = 0
        self.g_gzLastZ = 0.0
        self.g_gzHaveZ = False
        self.g_gzBuyPeakPrice = 0.0
        self.g_gzSellPeakPrice = DBL_MAX
        self.g_gzBuyTrailActive = False
        self.g_gzSellTrailActive = False
        self.g_gzBuyTrailSL = 0.0
        self.g_gzSellTrailSL = 0.0
        self.g_gzBuyBE = 0.0
        self.g_gzSellBE = 0.0
        self.g_gzBuyChainCount = 0
        self.g_gzSellChainCount = 0
        self.g_gzBuyInGap = False
        self.g_gzSellInGap = False
        self.g_gzBuyGapAnchor = 0.0
        self.g_gzSellGapAnchor = 0.0
        self.g_gzBuyTotalOrders = 0
        self.g_gzSellTotalOrders = 0
        self.g_gzLastBuyEntry = 0.0
        self.g_gzLastSellEntry = 0.0
        self.g_gzHandleATR = INVALID_HANDLE
        self.g_gzATR = 0.0
        self.g_gzStepAbs = 0.0
        self.g_gzGapAbs = 0.0
        self.g_gzBuyExitPending = False
        self.g_gzSellExitPending = False
        self.g_gzBuyCapNoted = False
        self.g_gzSellCapNoted = False
        self.g_gzLastExitTryMs = 0
        # Engine B context
        self.g_lvSymbol = ""
        self.g_lvPoint = 0.0
        self.g_lvDigits = 0
        self.g_lvTrade = CTrade()
        self.g_lvPos = CPositionInfo()
        self.g_lvOrd = COrderInfo()
        self.g_lvRecoveryEnabled = False
        self.g_lvSig = []
        self.g_lvTfCount = 0
        self.g_lvAnchorIdx = 0
        self.g_lvAnchorRiskMoney = 0.0
        self.g_lvAwaitingFirstTrade = True
        self.g_lvAnchorFilePath = ""
        self.g_lvHaveEntryCtx = False
        self.g_lvEntryTFIdx = -1
        self.g_lvEntryATR = 0.0
        self.g_lvEntryInitM = 0.0
        self.g_lvEntryFinalM = 0.0
        self.g_lvEntryTPM = 0.0
        self.g_lvEntryLot = 0.0
        self.g_lvChains = []
        self.g_lvTotalChains = 0
        self.g_lvTickCounter = 0
        self.g_lvLastPositionCount = 0
        self._lv_live = []

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║                       SHARED HELPERS                          ║
    # ╚═══════════════════════════════════════════════════════════════╝
    def MixFail(self, msg):
        Print("Zscore and Levando MIX ERROR: ", msg)
        Alert("Zscore and Levando MIX ERROR: ", msg)

    def ResolveSymbol(self, requested, tag):
        """returns (ok, resolved)"""
        s = requested.strip()
        if len(s) == 0:
            return True, Symbol()
        if SymbolSelect(s, True):
            return True, s
        chartUp = Symbol().upper()
        reqUp = s.upper()
        if chartUp.find(reqUp) >= 0:
            Print("[", tag, "] asset '", s, "' not found at this broker — using chart symbol '", Symbol(), "'")
            return True, Symbol()
        self.MixFail("[" + tag + "] asset '" + s + "' does not exist at this broker. " +
                     "Type the exact name from Market Watch, or leave it blank to use the chart symbol.")
        return False, ""

    def IsNewQuote(self, sym, which):
        t = MqlTick()
        if not SymbolInfoTick(sym, t):
            return False
        if which == "gz":
            if t.time_msc == self.g_gzQuoteMsc and t.bid == self.g_gzQuoteBid and t.ask == self.g_gzQuoteAsk:
                return False
            self.g_gzQuoteMsc, self.g_gzQuoteBid, self.g_gzQuoteAsk = t.time_msc, t.bid, t.ask
        else:
            if t.time_msc == self.g_lvQuoteMsc and t.bid == self.g_lvQuoteBid and t.ask == self.g_lvQuoteAsk:
                return False
            self.g_lvQuoteMsc, self.g_lvQuoteBid, self.g_lvQuoteAsk = t.time_msc, t.bid, t.ask
        return True

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║        ENGINE A — GRID Z-SCORE MEAN REVERSION v3.2            ║
    # ╚═══════════════════════════════════════════════════════════════╝
    @staticmethod
    def GZ_GetTrailConfig(speed):
        cfg = GZ_TrailConfig()
        cfg.triggerSpreads, cfg.trailDistSpreads, cfg.ratchetFraction, cfg.minLockSpreads = 3.0, 2.5, 0.40, 1.0
        if speed == GZ_TRAIL_SLOWEST:
            cfg.triggerSpreads, cfg.trailDistSpreads, cfg.ratchetFraction, cfg.minLockSpreads = 10.0, 8.0, 0.10, 1.0
        elif speed == GZ_TRAIL_SLOWER:
            cfg.triggerSpreads, cfg.trailDistSpreads, cfg.ratchetFraction, cfg.minLockSpreads = 6.0, 5.0, 0.20, 0.8
        elif speed == GZ_TRAIL_SLOW:
            cfg.triggerSpreads, cfg.trailDistSpreads, cfg.ratchetFraction, cfg.minLockSpreads = 3.0, 2.5, 0.40, 0.5
        elif speed == GZ_TRAIL_FAST:
            cfg.triggerSpreads, cfg.trailDistSpreads, cfg.ratchetFraction, cfg.minLockSpreads = 1.5, 1.0, 0.70, 0.3
        elif speed == GZ_TRAIL_FASTER:
            cfg.triggerSpreads, cfg.trailDistSpreads, cfg.ratchetFraction, cfg.minLockSpreads = 0.8, 0.4, 0.90, 0.15
        elif speed == GZ_TRAIL_FASTEST:
            cfg.triggerSpreads, cfg.trailDistSpreads, cfg.ratchetFraction, cfg.minLockSpreads = 0.3, 0.1, 0.98, 0.05
        return cfg

    @staticmethod
    def GZ_TrailSpeedName(speed):
        return {GZ_TRAIL_SLOWEST: "SLOWEST", GZ_TRAIL_SLOWER: "SLOWER", GZ_TRAIL_SLOW: "SLOW",
                GZ_TRAIL_FAST: "FAST", GZ_TRAIL_FASTER: "FASTER", GZ_TRAIL_FASTEST: "FASTEST"}.get(speed, "SLOW")

    def GZ_GetSpreadPrice(self):
        ask = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)
        bid = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID)
        spread = ask - bid
        if spread < self.g_gzPoint:
            spread = self.g_gzPoint
        return spread

    def GZ_ResetTrailState(self):
        self.g_gzBuyTrailActive = False
        self.g_gzSellTrailActive = False
        self.g_gzBuyPeakPrice = 0.0
        self.g_gzSellPeakPrice = DBL_MAX
        self.g_gzBuyTrailSL = 0.0
        self.g_gzSellTrailSL = 0.0
        self.g_gzBuyBE = 0.0
        self.g_gzSellBE = 0.0

    def GZ_ReconstructGridState(self):
        self.g_gzBuyTotalOrders = 0
        self.g_gzSellTotalOrders = 0
        self.g_gzLastBuyEntry = 0.0
        self.g_gzLastSellEntry = 0.0
        latestBuyTime = latestSellTime = 0
        for i in range(PositionsTotal() - 1, -1, -1):
            ticket = PositionGetTicket(i)
            if ticket == 0:
                continue
            if PositionGetString(POSITION_SYMBOL) != self.g_gzSymbol:
                continue
            if PositionGetInteger(POSITION_MAGIC) != self.InpGZ_Magic:
                continue
            type_ = PositionGetInteger(POSITION_TYPE)
            openPrice = PositionGetDouble(POSITION_PRICE_OPEN)
            openTime = PositionGetInteger(POSITION_TIME)
            if type_ == POSITION_TYPE_BUY:
                self.g_gzBuyTotalOrders += 1
                if openTime > latestBuyTime:
                    latestBuyTime = openTime
                    self.g_gzLastBuyEntry = openPrice
            elif type_ == POSITION_TYPE_SELL:
                self.g_gzSellTotalOrders += 1
                if openTime > latestSellTime:
                    latestSellTime = openTime
                    self.g_gzLastSellEntry = openPrice
        cs = self.InpGZ_GridChainSize
        self.g_gzBuyChainCount = (((self.g_gzBuyTotalOrders - 1) % cs) + 1) if self.g_gzBuyTotalOrders > 0 else 0
        self.g_gzSellChainCount = (((self.g_gzSellTotalOrders - 1) % cs) + 1) if self.g_gzSellTotalOrders > 0 else 0
        if self.g_gzBuyChainCount >= cs:
            self.g_gzBuyInGap = True
            self.g_gzBuyGapAnchor = self.g_gzLastBuyEntry
        if self.g_gzSellChainCount >= cs:
            self.g_gzSellInGap = True
            self.g_gzSellGapAnchor = self.g_gzLastSellEntry
        Print("[GridZ] Reconstructed: Buys=", self.g_gzBuyTotalOrders, " chain=", self.g_gzBuyChainCount,
              " | Sells=", self.g_gzSellTotalOrders, " chain=", self.g_gzSellChainCount)

    def GZ_GetBasketInfo(self, side):
        """returns (avgEntry, totalLots, count)"""
        avgEntry = totalLots = 0.0
        count = 0
        sumWeighted = 0.0
        for i in range(PositionsTotal() - 1, -1, -1):
            ticket = PositionGetTicket(i)
            if ticket == 0:
                continue
            if PositionGetString(POSITION_SYMBOL) != self.g_gzSymbol:
                continue
            if PositionGetInteger(POSITION_MAGIC) != self.InpGZ_Magic:
                continue
            type_ = PositionGetInteger(POSITION_TYPE)
            if (side == 0 and type_ != POSITION_TYPE_BUY) or (side == 1 and type_ != POSITION_TYPE_SELL):
                continue
            vol = PositionGetDouble(POSITION_VOLUME)
            price = PositionGetDouble(POSITION_PRICE_OPEN)
            sumWeighted += price * vol
            totalLots += vol
            count += 1
        if totalLots > 0:
            avgEntry = sumWeighted / totalLots
        return avgEntry, totalLots, count

    def GZ_CollectTickets(self, side):
        tickets = []
        for i in range(PositionsTotal() - 1, -1, -1):
            ticket = PositionGetTicket(i)
            if ticket == 0:
                continue
            if PositionGetString(POSITION_SYMBOL) != self.g_gzSymbol:
                continue
            if PositionGetInteger(POSITION_MAGIC) != self.InpGZ_Magic:
                continue
            type_ = PositionGetInteger(POSITION_TYPE)
            if (side == 0 and type_ != POSITION_TYPE_BUY) or (side == 1 and type_ != POSITION_TYPE_SELL):
                continue
            tickets.append(ticket)
        return tickets

    def GZ_ForceSLOnTicket(self, ticket, newSL, clearing):
        digits = self.g_gzDigits
        for attempt in range(10):
            if not PositionSelectByTicket(ticket):
                Print("[GridZ] ForceSL: ticket ", ticket, " no longer exists, skip")
                return True
            currentSL = PositionGetDouble(POSITION_SL)
            currentTP = PositionGetDouble(POSITION_TP)
            if clearing and currentSL == 0:
                return True
            if not clearing and abs(currentSL - newSL) < self.g_gzPoint * 0.5:
                return True
            req = MqlTradeRequest()
            res = MqlTradeResult()
            req.action = TRADE_ACTION_SLTP
            req.symbol = self.g_gzSymbol
            req.position = ticket
            req.sl = 0 if clearing else NormalizeDouble(newSL, digits)
            req.tp = currentTP
            ResetLastError()
            sent = OrderSend(req, res)
            if sent and (res.retcode == 10009 or res.retcode == 10008):
                return True
            if res.retcode == 10025:
                return True
            Print("[GridZ] ForceSL RETRY ", attempt + 1, "/10 | ticket=", ticket,
                  " | SL=", DoubleToString(0 if clearing else newSL, digits),
                  " | err=", res.retcode, " ", res.comment)
            if attempt < 9:
                Sleep(100)
        Print("[GridZ] ForceSL FAILED after 10 attempts | ticket=", ticket)
        return False

    def GZ_SetSLOnSide(self, side, newSL):
        digits = self.g_gzDigits
        newSL = NormalizeDouble(newSL, digits)
        clearing = (newSL <= 0)
        tickets = self.GZ_CollectTickets(side)
        count = len(tickets)
        if count == 0:
            return
        if not clearing:
            if side == 0 and self.g_gzBuyBE > 0 and newSL < self.g_gzBuyBE:
                newSL = NormalizeDouble(self.g_gzBuyBE, digits)
            if side == 1 and self.g_gzSellBE > 0 and newSL > self.g_gzSellBE:
                newSL = NormalizeDouble(self.g_gzSellBE, digits)
            stopLevelPts = SymbolInfoInteger(self.g_gzSymbol, SYMBOL_TRADE_STOPS_LEVEL)
            stoplevel = stopLevelPts * self.g_gzPoint
            bid = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID)
            ask = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)
            if side == 0:
                maxAllowed = NormalizeDouble(bid - stoplevel, digits)
                if newSL > maxAllowed:
                    if maxAllowed >= self.g_gzBuyBE or self.g_gzBuyBE == 0:
                        newSL = maxAllowed
                    else:
                        return
                if newSL <= 0:
                    return
            else:
                minAllowed = NormalizeDouble(ask + stoplevel, digits)
                if newSL < minAllowed:
                    if minAllowed <= self.g_gzSellBE or self.g_gzSellBE == 0:
                        newSL = minAllowed
                    else:
                        return
        successCount = failCount = 0
        for t in range(count):
            if not clearing:
                if PositionSelectByTicket(tickets[t]):
                    curSL = PositionGetDouble(POSITION_SL)
                    if curSL > 0:
                        if side == 0 and newSL <= curSL:
                            continue
                        if side == 1 and newSL >= curSL:
                            continue
            if self.GZ_ForceSLOnTicket(tickets[t], newSL, clearing):
                successCount += 1
            else:
                failCount += 1
        if failCount > 0:
            Print("[GridZ] SetSLOnSide WARNING: ", failCount, "/", count, " tickets failed SL placement")

    def GZ_ForceRecalcAndSetSL(self, side):
        avgEntry, totalLots, count = self.GZ_GetBasketInfo(side)
        if count == 0 or avgEntry == 0:
            return
        spread = self.GZ_GetSpreadPrice()
        digits = self.g_gzDigits
        if side == 0:
            buyBE = NormalizeDouble(avgEntry + spread, digits)
            self.g_gzBuyBE = buyBE
            if self.g_gzBuyTrailActive:
                cfg = self.GZ_GetTrailConfig(self.InpGZ_TrailFirst if count == 1 else self.InpGZ_TrailGrid)
                bid = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID)
                triggerPrice = buyBE + cfg.triggerSpreads * spread
                if bid >= triggerPrice:
                    trailDist = cfg.trailDistSpreads * spread
                    minProfitSL = NormalizeDouble(buyBE + cfg.minLockSpreads * spread, digits)
                    self.g_gzBuyPeakPrice = bid
                    self.g_gzBuyTrailSL = NormalizeDouble(bid - trailDist, digits)
                    if self.g_gzBuyTrailSL < minProfitSL:
                        self.g_gzBuyTrailSL = minProfitSL
                    self.GZ_SetSLOnSide(0, self.g_gzBuyTrailSL)
                else:
                    self.g_gzBuyTrailActive = False
                    self.g_gzBuyPeakPrice = 0.0
                    self.g_gzBuyTrailSL = 0.0
                    self.GZ_SetSLOnSide(0, 0)
        else:
            sellBE = NormalizeDouble(avgEntry - spread, digits)
            self.g_gzSellBE = sellBE
            if self.g_gzSellTrailActive:
                cfg = self.GZ_GetTrailConfig(self.InpGZ_TrailFirst if count == 1 else self.InpGZ_TrailGrid)
                ask = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)
                triggerPrice = sellBE - cfg.triggerSpreads * spread
                if ask <= triggerPrice:
                    trailDist = cfg.trailDistSpreads * spread
                    maxProfitSL = NormalizeDouble(sellBE - cfg.minLockSpreads * spread, digits)
                    self.g_gzSellPeakPrice = ask
                    self.g_gzSellTrailSL = NormalizeDouble(ask + trailDist, digits)
                    if self.g_gzSellTrailSL > maxProfitSL:
                        self.g_gzSellTrailSL = maxProfitSL
                    self.GZ_SetSLOnSide(1, self.g_gzSellTrailSL)
                else:
                    self.g_gzSellTrailActive = False
                    self.g_gzSellPeakPrice = DBL_MAX
                    self.g_gzSellTrailSL = 0.0
                    self.GZ_SetSLOnSide(1, 0)

    def GZ_VerifyAllPositionsTracked(self, side, expectedCount):
        actualCount = 0
        for i in range(PositionsTotal() - 1, -1, -1):
            ticket = PositionGetTicket(i)
            if ticket == 0:
                continue
            if PositionGetString(POSITION_SYMBOL) != self.g_gzSymbol:
                continue
            if PositionGetInteger(POSITION_MAGIC) != self.InpGZ_Magic:
                continue
            type_ = PositionGetInteger(POSITION_TYPE)
            if (side == 0 and type_ == POSITION_TYPE_BUY) or (side == 1 and type_ == POSITION_TYPE_SELL):
                actualCount += 1
        if actualCount != expectedCount:
            Print("[GridZ] POSITION COUNT MISMATCH! side=", side, " expected=", expectedCount,
                  " actual=", actualCount, " | Fixing grid count...")
            cs = self.InpGZ_GridChainSize
            if side == 0:
                self.g_gzBuyTotalOrders = actualCount
                self.g_gzBuyChainCount = (((actualCount - 1) % cs) + 1) if actualCount > 0 else 0
            else:
                self.g_gzSellTotalOrders = actualCount
                self.g_gzSellChainCount = (((actualCount - 1) % cs) + 1) if actualCount > 0 else 0

    def GZ_EnforceSLOnAll(self, side, requiredSL):
        digits = self.g_gzDigits
        slNorm = NormalizeDouble(requiredSL, digits)
        if slNorm <= 0:
            return
        for i in range(PositionsTotal() - 1, -1, -1):
            ticket = PositionGetTicket(i)
            if ticket == 0:
                continue
            if PositionGetString(POSITION_SYMBOL) != self.g_gzSymbol:
                continue
            if PositionGetInteger(POSITION_MAGIC) != self.InpGZ_Magic:
                continue
            type_ = PositionGetInteger(POSITION_TYPE)
            if (side == 0 and type_ != POSITION_TYPE_BUY) or (side == 1 and type_ != POSITION_TYPE_SELL):
                continue
            currentSL = PositionGetDouble(POSITION_SL)
            needsFix = False
            if currentSL == 0:
                needsFix = True
            elif side == 0 and currentSL < slNorm - self.g_gzPoint:
                needsFix = True
            elif side == 1 and currentSL > slNorm + self.g_gzPoint:
                needsFix = True
            if needsFix:
                Print("[GridZ] ENFORCE SL FIX: ticket=", ticket, " currentSL=", DoubleToString(currentSL, digits),
                      " → requiredSL=", DoubleToString(slNorm, digits))
                self.GZ_ForceSLOnTicket(ticket, slNorm, False)

    def GZ_ManageSLTrailing(self):
        digits = self.g_gzDigits
        spread = self.GZ_GetSpreadPrice()
        bid = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID)
        ask = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)

        # BUY SIDE
        buyAvg, buyLots, buyCount = self.GZ_GetBasketInfo(0)
        if buyCount > 0 and buyAvg > 0:
            cfg = self.GZ_GetTrailConfig(self.InpGZ_TrailFirst if buyCount == 1 else self.InpGZ_TrailGrid)
            buyBE = NormalizeDouble(buyAvg + spread, digits)
            self.g_gzBuyBE = buyBE
            triggerPrice = buyBE + cfg.triggerSpreads * spread
            trailDist = cfg.trailDistSpreads * spread
            minProfitSL = NormalizeDouble(buyBE + cfg.minLockSpreads * spread, digits)
            if not self.g_gzBuyTrailActive:
                if bid >= triggerPrice:
                    self.g_gzBuyTrailActive = True
                    self.g_gzBuyPeakPrice = bid
                    self.g_gzBuyTrailSL = NormalizeDouble(bid - trailDist, digits)
                    if self.g_gzBuyTrailSL < minProfitSL:
                        self.g_gzBuyTrailSL = minProfitSL
                    self.GZ_SetSLOnSide(0, self.g_gzBuyTrailSL)
                    Print("[GridZ] BUY TRAIL ON [",
                          self.GZ_TrailSpeedName(self.InpGZ_TrailFirst if buyCount == 1 else self.InpGZ_TrailGrid),
                          "] bid=", DoubleToString(bid, digits), " BE=", DoubleToString(buyBE, digits),
                          " SL=", DoubleToString(self.g_gzBuyTrailSL, digits), " positions=", buyCount)
                else:
                    self.GZ_VerifyAllPositionsTracked(0, buyCount)
            else:
                trailDist = cfg.trailDistSpreads * spread
                minProfitSL = NormalizeDouble(buyBE + cfg.minLockSpreads * spread, digits)
                if bid > self.g_gzBuyPeakPrice:
                    self.g_gzBuyPeakPrice = bid
                idealSL = self.g_gzBuyPeakPrice - trailDist
                proposedSL = self.g_gzBuyTrailSL + (idealSL - self.g_gzBuyTrailSL) * cfg.ratchetFraction
                proposedSL = NormalizeDouble(proposedSL, digits)
                if proposedSL < minProfitSL:
                    proposedSL = minProfitSL
                if proposedSL > self.g_gzBuyTrailSL:
                    self.g_gzBuyTrailSL = proposedSL
                    self.GZ_SetSLOnSide(0, self.g_gzBuyTrailSL)
                else:
                    self.GZ_EnforceSLOnAll(0, self.g_gzBuyTrailSL)
        else:
            if self.g_gzBuyTrailActive or self.g_gzBuyTotalOrders > 0:
                self.g_gzBuyTrailActive = False
                self.g_gzBuyPeakPrice = 0.0
                self.g_gzBuyTrailSL = 0.0
                self.g_gzBuyBE = 0.0
                self.g_gzBuyChainCount = 0
                self.g_gzBuyInGap = False
                self.g_gzBuyGapAnchor = 0.0
                self.g_gzBuyTotalOrders = 0
                self.g_gzLastBuyEntry = 0.0

        # SELL SIDE
        sellAvg, sellLots, sellCount = self.GZ_GetBasketInfo(1)
        if sellCount > 0 and sellAvg > 0:
            cfg = self.GZ_GetTrailConfig(self.InpGZ_TrailFirst if sellCount == 1 else self.InpGZ_TrailGrid)
            sellBE = NormalizeDouble(sellAvg - spread, digits)
            self.g_gzSellBE = sellBE
            triggerPrice = sellBE - cfg.triggerSpreads * spread
            trailDist = cfg.trailDistSpreads * spread
            maxProfitSL = NormalizeDouble(sellBE - cfg.minLockSpreads * spread, digits)
            if not self.g_gzSellTrailActive:
                if ask <= triggerPrice:
                    self.g_gzSellTrailActive = True
                    self.g_gzSellPeakPrice = ask
                    self.g_gzSellTrailSL = NormalizeDouble(ask + trailDist, digits)
                    if self.g_gzSellTrailSL > maxProfitSL:
                        self.g_gzSellTrailSL = maxProfitSL
                    self.GZ_SetSLOnSide(1, self.g_gzSellTrailSL)
                    Print("[GridZ] SELL TRAIL ON [",
                          self.GZ_TrailSpeedName(self.InpGZ_TrailFirst if sellCount == 1 else self.InpGZ_TrailGrid),
                          "] ask=", DoubleToString(ask, digits), " BE=", DoubleToString(sellBE, digits),
                          " SL=", DoubleToString(self.g_gzSellTrailSL, digits), " positions=", sellCount)
                else:
                    self.GZ_VerifyAllPositionsTracked(1, sellCount)
            else:
                trailDist = cfg.trailDistSpreads * spread
                maxProfitSL = NormalizeDouble(sellBE - cfg.minLockSpreads * spread, digits)
                if ask < self.g_gzSellPeakPrice:
                    self.g_gzSellPeakPrice = ask
                idealSL = self.g_gzSellPeakPrice + trailDist
                proposedSL = self.g_gzSellTrailSL - (self.g_gzSellTrailSL - idealSL) * cfg.ratchetFraction
                proposedSL = NormalizeDouble(proposedSL, digits)
                if proposedSL > maxProfitSL:
                    proposedSL = maxProfitSL
                if proposedSL < self.g_gzSellTrailSL:
                    self.g_gzSellTrailSL = proposedSL
                    self.GZ_SetSLOnSide(1, self.g_gzSellTrailSL)
                else:
                    self.GZ_EnforceSLOnAll(1, self.g_gzSellTrailSL)
        else:
            if self.g_gzSellTrailActive or self.g_gzSellTotalOrders > 0:
                self.g_gzSellTrailActive = False
                self.g_gzSellPeakPrice = DBL_MAX
                self.g_gzSellTrailSL = 0.0
                self.g_gzSellBE = 0.0
                self.g_gzSellChainCount = 0
                self.g_gzSellInGap = False
                self.g_gzSellGapAnchor = 0.0
                self.g_gzSellTotalOrders = 0
                self.g_gzLastSellEntry = 0.0

    def GZ_CalcZScore(self, shift):
        ma, std = [], []
        if CopyBuffer(self.g_gzHandleMA, 0, shift, 1, ma) < 1:
            return EMPTY_VALUE
        if CopyBuffer(self.g_gzHandleStd, 0, shift, 1, std) < 1:
            return EMPTY_VALUE
        close = iClose(self.g_gzSymbol, self.g_gzTF, shift)
        if close <= 0:
            return EMPTY_VALUE
        if std[0] < self.g_gzPoint * 0.001:
            return 0.0
        return (close - ma[0]) / std[0]

    def GZ_CountPositions(self):
        buyCount = sellCount = 0
        for i in range(PositionsTotal() - 1, -1, -1):
            ticket = PositionGetTicket(i)
            if ticket == 0:
                continue
            if PositionGetString(POSITION_SYMBOL) != self.g_gzSymbol:
                continue
            if PositionGetInteger(POSITION_MAGIC) != self.InpGZ_Magic:
                continue
            type_ = PositionGetInteger(POSITION_TYPE)
            if type_ == POSITION_TYPE_BUY:
                buyCount += 1
            elif type_ == POSITION_TYPE_SELL:
                sellCount += 1
        return buyCount, sellCount

    def GZ_GetATR(self):
        if self.g_gzHandleATR == INVALID_HANDLE:
            return 0.0
        b = []
        if CopyBuffer(self.g_gzHandleATR, 0, 1, 1, b) < 1:
            return 0.0
        if b[0] <= 0 or b[0] == EMPTY_VALUE:
            return 0.0
        return b[0]

    def GZ_CalcSpacing(self, refPrice):
        stepAbs = refPrice * self.InpGZ_GridThreshold / 100.0
        gapAbs = refPrice * self.InpGZ_GapResetPct / 100.0
        if self.InpGZ_GapMode == GZ_GAP_VOLATILITY:
            atr = self.GZ_GetATR()
            self.g_gzATR = atr
            if atr > 0:
                stepAbs = max(stepAbs, atr * self.InpGZ_VolStepMult)
                gapAbs = max(gapAbs, atr * self.InpGZ_VolGapMult)
        return stepAbs, gapAbs

    def GZ_FillingMode(self):
        fillType = SymbolInfoInteger(self.g_gzSymbol, SYMBOL_FILLING_MODE)
        if (fillType & SYMBOL_FILLING_FOK) != 0:
            return ORDER_FILLING_FOK
        if (fillType & SYMBOL_FILLING_IOC) != 0:
            return ORDER_FILLING_IOC
        return ORDER_FILLING_RETURN

    def GZ_ResetSide(self, side):
        if side == 0:
            self.g_gzBuyTrailActive = False
            self.g_gzBuyPeakPrice = 0.0
            self.g_gzBuyTrailSL = 0.0
            self.g_gzBuyBE = 0.0
            self.g_gzBuyChainCount = 0
            self.g_gzBuyInGap = False
            self.g_gzBuyGapAnchor = 0.0
            self.g_gzBuyTotalOrders = 0
            self.g_gzLastBuyEntry = 0.0
            self.g_gzBuyCapNoted = False
        else:
            self.g_gzSellTrailActive = False
            self.g_gzSellPeakPrice = DBL_MAX
            self.g_gzSellTrailSL = 0.0
            self.g_gzSellBE = 0.0
            self.g_gzSellChainCount = 0
            self.g_gzSellInGap = False
            self.g_gzSellGapAnchor = 0.0
            self.g_gzSellTotalOrders = 0
            self.g_gzLastSellEntry = 0.0
            self.g_gzSellCapNoted = False

    def GZ_ClosePosition(self, ticket):
        for attempt in range(5):
            if not PositionSelectByTicket(ticket):
                return True
            type_ = PositionGetInteger(POSITION_TYPE)
            vol = PositionGetDouble(POSITION_VOLUME)
            req = MqlTradeRequest()
            res = MqlTradeResult()
            req.action = TRADE_ACTION_DEAL
            req.symbol = self.g_gzSymbol
            req.position = ticket
            req.volume = vol
            req.type = ORDER_TYPE_SELL if type_ == POSITION_TYPE_BUY else ORDER_TYPE_BUY
            req.price = (SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID) if type_ == POSITION_TYPE_BUY
                         else SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK))
            req.deviation = self.InpGZ_Slippage
            req.magic = self.InpGZ_Magic
            req.comment = self.InpGZ_Comment + " CAP OUT"
            req.type_filling = self.GZ_FillingMode()
            ResetLastError()
            sent = OrderSend(req, res)
            if sent and res.retcode == TRADE_RETCODE_DONE:
                return True
            if sent and res.retcode == TRADE_RETCODE_DONE_PARTIAL:
                continue
            Print("[GridZ] CAP OUT close RETRY ", attempt + 1, "/5 | ticket=", ticket,
                  " | err=", res.retcode, " ", res.comment)
            if attempt < 4:
                Sleep(100)
        return not PositionSelectByTicket(ticket)

    def GZ_CloseSide(self, side):
        tickets = self.GZ_CollectTickets(side)
        allClosed = True
        for t in tickets:
            if not self.GZ_ClosePosition(t):
                allClosed = False
        return allClosed

    def GZ_RunPendingExits(self):
        if not self.g_gzBuyExitPending and not self.g_gzSellExitPending:
            return
        now = GetTickCount64()
        if self.g_gzLastExitTryMs != 0 and now - self.g_gzLastExitTryMs < 2000:
            return
        self.g_gzLastExitTryMs = 1 if now == 0 else now
        if self.g_gzBuyExitPending and self.GZ_CloseSide(0):
            self.g_gzBuyExitPending = False
            self.GZ_ResetSide(0)
            Print("[GridZ] CAP OUT: BUY basket closed")
        if self.g_gzSellExitPending and self.GZ_CloseSide(1):
            self.g_gzSellExitPending = False
            self.GZ_ResetSide(1)
            Print("[GridZ] CAP OUT: SELL basket closed")

    def GZ_OnCapHit(self, side, count):
        sideTxt = "BUY" if side == 0 else "SELL"
        if self.InpGZ_CapAction == GZ_CAP_OUT:
            Print("[GridZ] POSITION CAP ", self.InpGZ_MaxPositions, " reached on ", sideTxt, " side (", count,
                  " open) and the next level was hit -> OUT: closing the whole ", sideTxt, " basket")
            if side == 0:
                self.g_gzBuyExitPending = True
            else:
                self.g_gzSellExitPending = True
            self.g_gzLastExitTryMs = 0
            self.GZ_RunPendingExits()
        else:
            noted = self.g_gzBuyCapNoted if side == 0 else self.g_gzSellCapNoted
            if not noted:
                Print("[GridZ] POSITION CAP ", self.InpGZ_MaxPositions, " reached on ", sideTxt, " side (", count,
                      " open) -> HOLD: no more orders are added, basket stays open")
                if side == 0:
                    self.g_gzBuyCapNoted = True
                else:
                    self.g_gzSellCapNoted = True

    def GZ_CalcLot(self, chainLevel):
        baseLot = self.InpGZ_FixedLot
        if self.InpGZ_LotMode == GZ_LOT_RISK_PCT:
            equity = AccountInfoDouble(ACCOUNT_EQUITY)
            riskAmount = equity * self.InpGZ_RiskPct / 100.0
            tickVal = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_TRADE_TICK_VALUE)
            tickSize = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_TRADE_TICK_SIZE)
            price = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)
            thresholdPrice, gapUnused = self.GZ_CalcSpacing(price)
            thresholdPts = thresholdPrice / tickSize if tickSize > 0 else 0
            if tickVal > 0 and thresholdPts > 0:
                baseLot = riskAmount / (thresholdPts * tickVal)
            else:
                baseLot = self.InpGZ_FixedLot
        lot = baseLot * math.pow(self.InpGZ_MartingaleMult, chainLevel - 1)
        minLot = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_VOLUME_MIN)
        maxLot = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_VOLUME_MAX)
        stepLot = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_VOLUME_STEP)
        if stepLot <= 0:
            stepLot = 0.01
        lot = max(lot, minLot)
        lot = min(lot, maxLot)
        lot = math.floor(lot / stepLot) * stepLot
        return NormalizeDouble(lot, 2)

    def GZ_OpenOrder(self, type_, lot, comment):
        req = MqlTradeRequest()
        res = MqlTradeResult()
        req.action = TRADE_ACTION_DEAL
        req.symbol = self.g_gzSymbol
        req.volume = lot
        req.type = type_
        req.price = (SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK) if type_ == ORDER_TYPE_BUY
                     else SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID))
        req.deviation = self.InpGZ_Slippage
        req.magic = self.InpGZ_Magic
        req.comment = self.InpGZ_Comment + " " + comment
        req.type_filling = self.GZ_FillingMode()
        if not OrderSend(req, res):
            Print("[GridZ] OrderSend FAILED: ", res.retcode, " | ", res.comment, " | ", comment)
            return False
        Print("[GridZ] ORDER: ", comment, " | Lot=", DoubleToString(lot, 2),
              " | Price=", DoubleToString(req.price, self.g_gzDigits), " | Ticket=", res.order)
        return True

    def GZ_DrawDashboard(self, zscore, buyCount, sellCount):
        if not self.InpGZ_ShowOnChart or not self.VISUAL:
            return   # chart output only; no trading state is touched
        Comment(f"GridZ z={zscore:.4f} buys={buyCount} sells={sellCount}")

    def GZ_Init(self):
        if self.InpGZ_ZscorePeriod < 2 or self.InpGZ_GridChainSize < 1:
            self.MixFail("[GridZ] Z-Score period must be >= 2 and Grid Chain Size must be >= 1.")
            return False
        self.g_gzTF = Period() if self.InpGZ_Timeframe == PERIOD_CURRENT else self.InpGZ_Timeframe
        self.g_gzPoint = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_POINT)
        self.g_gzDigits = SymbolInfoInteger(self.g_gzSymbol, SYMBOL_DIGITS)
        if self.g_gzPoint <= 0:
            self.MixFail("[GridZ] cannot read symbol properties for '" + self.g_gzSymbol + "'.")
            return False
        self.g_gzHandleMA = iMA(self.g_gzSymbol, self.g_gzTF, self.InpGZ_ZscorePeriod, 0, MODE_SMA, PRICE_CLOSE)
        if self.g_gzHandleMA == INVALID_HANDLE:
            self.MixFail("[GridZ] failed to create MA handle.")
            return False
        self.g_gzHandleStd = iStdDev(self.g_gzSymbol, self.g_gzTF, self.InpGZ_ZscorePeriod, 0, MODE_SMA, PRICE_CLOSE)
        if self.g_gzHandleStd == INVALID_HANDLE:
            self.MixFail("[GridZ] failed to create StdDev handle.")
            return False
        if self.InpGZ_GapMode == GZ_GAP_VOLATILITY:
            if self.InpGZ_VolATRPeriod < 1 or self.InpGZ_VolStepMult <= 0 or self.InpGZ_VolGapMult <= 0:
                self.MixFail("[GridZ] volatility gapping needs ATR period >= 1 and both ATR multipliers > 0.")
                return False
            self.g_gzHandleATR = iATR(self.g_gzSymbol, self.g_gzTF, self.InpGZ_VolATRPeriod)
            if self.g_gzHandleATR == INVALID_HANDLE:
                self.MixFail("[GridZ] failed to create ATR handle.")
                return False
        self.g_gzBuyExitPending = False
        self.g_gzSellExitPending = False
        self.g_gzBuyCapNoted = False
        self.g_gzSellCapNoted = False
        self.g_gzLastExitTryMs = 0
        self.GZ_ReconstructGridState()
        self.GZ_ResetTrailState()
        self.g_gzLastBarTime = 0
        self.g_gzTickCounter = 0
        self.g_gzHaveZ = False
        Print("  ENGINE A: GridZScoreMR v3.2 | Asset: ", self.g_gzSymbol, " | TF: ", TFToText(self.g_gzTF),
              " | Magic=", self.InpGZ_Magic)
        return True

    def GZ_Deinit(self):
        if self.g_gzHandleMA != INVALID_HANDLE:
            IndicatorRelease(self.g_gzHandleMA)
            self.g_gzHandleMA = INVALID_HANDLE
        if self.g_gzHandleStd != INVALID_HANDLE:
            IndicatorRelease(self.g_gzHandleStd)
            self.g_gzHandleStd = INVALID_HANDLE
        if self.g_gzHandleATR != INVALID_HANDLE:
            IndicatorRelease(self.g_gzHandleATR)
            self.g_gzHandleATR = INVALID_HANDLE
        Comment("")

    def GZ_Process(self):
        self.GZ_RunPendingExits()
        self.GZ_ManageSLTrailing()

        self.g_gzTickCounter += 1
        if self.g_gzHaveZ and (self.g_gzTickCounter % 5 == 0) and self.VISUAL:
            b, s = self.GZ_CountPositions()
            self.GZ_DrawDashboard(self.g_gzLastZ, b, s)

        barTime = iTime(self.g_gzSymbol, self.g_gzTF, 0)
        if barTime <= 0 or barTime == self.g_gzLastBarTime:
            return
        zscore = self.GZ_CalcZScore(1)
        if zscore == EMPTY_VALUE:
            return
        self.g_gzLastBarTime = barTime
        self.g_gzLastZ = zscore
        self.g_gzHaveZ = True

        buyCount, sellCount = self.GZ_CountPositions()
        closeBar1 = iClose(self.g_gzSymbol, self.g_gzTF, 1)
        thresholdAbs, gapAbs = self.GZ_CalcSpacing(closeBar1)
        self.g_gzStepAbs = thresholdAbs
        self.g_gzGapAbs = gapAbs

        if buyCount == 0:
            self.g_gzBuyCapNoted = False
        if sellCount == 0:
            self.g_gzSellCapNoted = False

        if buyCount == 0 and self.g_gzBuyTotalOrders > 0:
            self.g_gzBuyChainCount = 0
            self.g_gzBuyInGap = False
            self.g_gzBuyGapAnchor = 0.0
            self.g_gzBuyTotalOrders = 0
            self.g_gzLastBuyEntry = 0.0
        if sellCount == 0 and self.g_gzSellTotalOrders > 0:
            self.g_gzSellChainCount = 0
            self.g_gzSellInGap = False
            self.g_gzSellGapAnchor = 0.0
            self.g_gzSellTotalOrders = 0
            self.g_gzLastSellEntry = 0.0

        cs = self.InpGZ_GridChainSize
        # BUY SIDE
        buyAllowed = (self.InpGZ_AllowBothSides or sellCount == 0) and not self.g_gzBuyExitPending
        buyAtCap = (self.InpGZ_MaxPositions > 0 and buyCount >= self.InpGZ_MaxPositions)
        if buyAllowed:
            if buyCount == 0 and zscore <= self.InpGZ_ZscoreBuyTh:
                lot = self.GZ_CalcLot(1)
                if self.GZ_OpenOrder(ORDER_TYPE_BUY, lot, "GridZ B#1 C1"):
                    self.g_gzBuyChainCount = 1
                    self.g_gzBuyTotalOrders = 1
                    self.g_gzBuyInGap = False
                    self.g_gzLastBuyEntry = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)
                    self.g_gzBuyTrailActive = False
                    self.g_gzBuyPeakPrice = 0.0
                    self.g_gzBuyTrailSL = 0.0
                    self.g_gzBuyBE = 0.0
                    Print("[GridZ] Z-SCORE BUY #1 | zscore=", DoubleToString(zscore, 4))
            elif buyCount > 0:
                if self.g_gzBuyInGap:
                    dropFromAnchor = self.g_gzBuyGapAnchor - closeBar1
                    if dropFromAnchor >= gapAbs and buyAtCap:
                        self.GZ_OnCapHit(0, buyCount)
                    elif dropFromAnchor >= gapAbs:
                        self.g_gzBuyChainCount = 0
                        self.g_gzBuyInGap = False
                        lot = self.GZ_CalcLot(1)
                        chainNum = (self.g_gzBuyTotalOrders // cs) + 1
                        if self.GZ_OpenOrder(ORDER_TYPE_BUY, lot, "GridZ B#1 C" + IntegerToString(chainNum + 1)):
                            self.g_gzBuyChainCount = 1
                            self.g_gzBuyTotalOrders += 1
                            self.g_gzLastBuyEntry = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)
                            self.g_gzBuyTrailActive = False
                            self.g_gzBuyPeakPrice = 0.0
                            self.g_gzBuyTrailSL = 0.0
                            self.g_gzBuyBE = 0.0
                            self.GZ_SetSLOnSide(0, 0)
                            self.GZ_ForceRecalcAndSetSL(0)
                            Print("[GridZ] GAP RESET BUY | New chain | drop=", DoubleToString(dropFromAnchor, 2))
                else:
                    dropFromLast = self.g_gzLastBuyEntry - closeBar1
                    if dropFromLast >= thresholdAbs and buyAtCap:
                        self.GZ_OnCapHit(0, buyCount)
                    elif dropFromLast >= thresholdAbs:
                        chainLevel = self.g_gzBuyChainCount + 1
                        lot = self.GZ_CalcLot(chainLevel)
                        chainNum = (self.g_gzBuyTotalOrders // cs) + 1
                        if self.GZ_OpenOrder(ORDER_TYPE_BUY, lot, "GridZ B#" + IntegerToString(chainLevel) +
                                             " C" + IntegerToString(chainNum)):
                            self.g_gzBuyChainCount += 1
                            self.g_gzBuyTotalOrders += 1
                            self.g_gzLastBuyEntry = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_ASK)
                            self.g_gzBuyTrailActive = False
                            self.g_gzBuyPeakPrice = 0.0
                            self.g_gzBuyTrailSL = 0.0
                            self.g_gzBuyBE = 0.0
                            self.GZ_SetSLOnSide(0, 0)
                            self.GZ_ForceRecalcAndSetSL(0)
                            Print("[GridZ] GRID BUY #", self.g_gzBuyChainCount, " C", chainNum,
                                  " | lot=", DoubleToString(lot, 2))
                            if self.g_gzBuyChainCount >= cs:
                                self.g_gzBuyInGap = True
                                self.g_gzBuyGapAnchor = self.g_gzLastBuyEntry
                                Print("[GridZ] BUY CHAIN FULL → GAP MODE")
                    elif closeBar1 < self.g_gzLastBuyEntry:
                        Print("[GridZ] Buy: drop=", DoubleToString(dropFromLast, 2),
                              " < th=", DoubleToString(thresholdAbs, 2), " | NO TRADE")

        # SELL SIDE
        sellAllowed = (self.InpGZ_AllowBothSides or buyCount == 0) and not self.g_gzSellExitPending
        sellAtCap = (self.InpGZ_MaxPositions > 0 and sellCount >= self.InpGZ_MaxPositions)
        if sellAllowed:
            if sellCount == 0 and zscore >= self.InpGZ_ZscoreSellTh:
                lot = self.GZ_CalcLot(1)
                if self.GZ_OpenOrder(ORDER_TYPE_SELL, lot, "GridZ S#1 C1"):
                    self.g_gzSellChainCount = 1
                    self.g_gzSellTotalOrders = 1
                    self.g_gzSellInGap = False
                    self.g_gzLastSellEntry = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID)
                    self.g_gzSellTrailActive = False
                    self.g_gzSellPeakPrice = DBL_MAX
                    self.g_gzSellTrailSL = 0.0
                    self.g_gzSellBE = 0.0
                    Print("[GridZ] Z-SCORE SELL #1 | zscore=", DoubleToString(zscore, 4))
            elif sellCount > 0:
                if self.g_gzSellInGap:
                    riseFromAnchor = closeBar1 - self.g_gzSellGapAnchor
                    if riseFromAnchor >= gapAbs and sellAtCap:
                        self.GZ_OnCapHit(1, sellCount)
                    elif riseFromAnchor >= gapAbs:
                        self.g_gzSellChainCount = 0
                        self.g_gzSellInGap = False
                        lot = self.GZ_CalcLot(1)
                        chainNum = (self.g_gzSellTotalOrders // cs) + 1
                        if self.GZ_OpenOrder(ORDER_TYPE_SELL, lot, "GridZ S#1 C" + IntegerToString(chainNum + 1)):
                            self.g_gzSellChainCount = 1
                            self.g_gzSellTotalOrders += 1
                            self.g_gzLastSellEntry = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID)
                            self.g_gzSellTrailActive = False
                            self.g_gzSellPeakPrice = DBL_MAX
                            self.g_gzSellTrailSL = 0.0
                            self.g_gzSellBE = 0.0
                            self.GZ_SetSLOnSide(1, 0)
                            self.GZ_ForceRecalcAndSetSL(1)
                            Print("[GridZ] GAP RESET SELL | New chain | rise=", DoubleToString(riseFromAnchor, 2))
                else:
                    riseFromLast = closeBar1 - self.g_gzLastSellEntry
                    if riseFromLast >= thresholdAbs and sellAtCap:
                        self.GZ_OnCapHit(1, sellCount)
                    elif riseFromLast >= thresholdAbs:
                        chainLevel = self.g_gzSellChainCount + 1
                        lot = self.GZ_CalcLot(chainLevel)
                        chainNum = (self.g_gzSellTotalOrders // cs) + 1
                        if self.GZ_OpenOrder(ORDER_TYPE_SELL, lot, "GridZ S#" + IntegerToString(chainLevel) +
                                             " C" + IntegerToString(chainNum)):
                            self.g_gzSellChainCount += 1
                            self.g_gzSellTotalOrders += 1
                            self.g_gzLastSellEntry = SymbolInfoDouble(self.g_gzSymbol, SYMBOL_BID)
                            self.g_gzSellTrailActive = False
                            self.g_gzSellPeakPrice = DBL_MAX
                            self.g_gzSellTrailSL = 0.0
                            self.g_gzSellBE = 0.0
                            self.GZ_SetSLOnSide(1, 0)
                            self.GZ_ForceRecalcAndSetSL(1)
                            Print("[GridZ] GRID SELL #", self.g_gzSellChainCount, " C", chainNum,
                                  " | lot=", DoubleToString(lot, 2))
                            if self.g_gzSellChainCount >= cs:
                                self.g_gzSellInGap = True
                                self.g_gzSellGapAnchor = self.g_gzLastSellEntry
                                Print("[GridZ] SELL CHAIN FULL → GAP MODE")
                    elif closeBar1 > self.g_gzLastSellEntry:
                        Print("[GridZ] Sell: rise=", DoubleToString(riseFromLast, 2),
                              " < th=", DoubleToString(thresholdAbs, 2), " | NO TRADE")

        if self.VISUAL:
            bc, sc = self.GZ_CountPositions()
            self.GZ_DrawDashboard(zscore, bc, sc)

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║     ENGINE B — LEVANDO CASCADE MULTI-TF SAME-RISK v4.10       ║
    # ╚═══════════════════════════════════════════════════════════════╝
    def _lv_live_idx(self):
        """Indices of chains that are active or still own a pending order, ascending.
        Every other chain is final (nothing can re-activate it), so skipping it in the
        MQL loops ``for(c = 0; c < g_lvTotalChains; c++)`` gives the identical result."""
        ch = self.g_lvChains
        live = [c for c in self._lv_live if ch[c].isActive or ch[c].pendingTicket != 0]
        self._lv_live = live
        return list(live)

    # ── dashboard ─────────────────────────────────────────────────────
    def LV_UpdateDashboard(self):
        if not self.InpLV_ShowOnChart:
            return
        isFlat = self.LV_IsSystemFlat()     # side effects (purges orphan orders) are part of the EA logic
        if not self.VISUAL:
            return
        if self.g_lvAwaitingFirstTrade:
            stateStr = "AWAITING FIRST SIGNAL on " + TFToText(self.g_lvSig[self.g_lvAnchorIdx].tf) + " (anchor)"
        elif isFlat:
            stateStr = "FLAT — next signal from ANY TF will be taken"
        else:
            stateStr = "ACTIVE — one trade running, new signals ignored"
        Comment("LeVanDo: " + stateStr)

    def LV_CleanDashboard(self):
        ObjectsDeleteAll(0, "LVD_")

    # ── timeframe parser ──────────────────────────────────────────────
    @staticmethod
    def LV_MinutesToTimeframe(m):
        mins = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440, 10080, 43200]
        tfs = [PERIOD_M1, PERIOD_M2, PERIOD_M3, PERIOD_M4, PERIOD_M5, PERIOD_M6, PERIOD_M10, PERIOD_M12,
               PERIOD_M15, PERIOD_M20, PERIOD_M30, PERIOD_H1, PERIOD_H2, PERIOD_H3, PERIOD_H4, PERIOD_H6,
               PERIOD_H8, PERIOD_H12, PERIOD_D1, PERIOD_W1, PERIOD_MN1]
        for i in range(len(mins)):
            if mins[i] == m:
                return tfs[i]
        bestI, bestD = 0, INT_MAX
        for i in range(len(mins)):
            d = abs(mins[i] - m)
            if d < bestD:
                bestD, bestI = d, i
        return tfs[bestI]

    def LV_ParseTimeframes(self):
        parts = self.InpLV_Timeframes.split(",")
        if len(parts) <= 0:
            return False
        self.g_lvTfCount = 0
        self.g_lvSig = []
        for s in parts:
            s = s.strip()
            if len(s) == 0:
                continue
            m = StringToInteger(s)
            if m <= 0:
                continue
            tf = self.LV_MinutesToTimeframe(m)
            if any(self.g_lvSig[k].tf == tf for k in range(self.g_lvTfCount)):
                continue
            sig = LV_TFSignal()
            sig.tf = tf
            sig.minutes = PeriodSeconds(tf) // 60
            self.g_lvSig.append(sig)
            self.g_lvTfCount += 1
        if self.g_lvTfCount == 0:
            return False
        self.g_lvAnchorIdx = 0
        bestSec = PeriodSeconds(self.g_lvSig[0].tf)
        for i in range(1, self.g_lvTfCount):
            sec = PeriodSeconds(self.g_lvSig[i].tf)
            if sec > bestSec:
                bestSec = sec
                self.g_lvAnchorIdx = i
        return True

    # ── autocorrelation regime estimator ──────────────────────────────
    def LV_CalculateAutocorrelation(self, tf):
        length = 3 if LV_AUTO_AC_PERIOD < 3 else LV_AUTO_AC_PERIOD
        closes = []
        needed = length + 2
        if CopyClose(self.g_lvSymbol, tf, 0, needed, closes, as_series=True) < needed:
            return 0.0
        ret = [closes[i] - closes[i + 1] for i in range(length + 1)]
        sumY = sumX = 0.0
        for i in range(length):
            sumY += ret[i]
            sumX += ret[i + 1]
        meanY, meanX = sumY / length, sumX / length
        sumXY = sumX2 = sumY2 = 0.0
        for i in range(length):
            dy = ret[i] - meanY
            dx = ret[i + 1] - meanX
            sumXY += dx * dy
            sumX2 += dx * dx
            sumY2 += dy * dy
        denom = math.sqrt(sumX2 * sumY2)
        if denom == 0:
            return 0.0
        ac = sumXY / denom
        return max(-1.0, min(1.0, ac))

    def LV_UpdateTFAutocorrelation(self, i):
        rawAC = self.LV_CalculateAutocorrelation(self.g_lvSig[i].tf)
        sig = self.g_lvSig[i]
        if not sig.acInit:
            sig.smoothedAC = rawAC
            sig.acInit = True
        else:
            sig.smoothedAC = LV_AUTO_AC_ALPHA * rawAC + (1.0 - LV_AUTO_AC_ALPHA) * sig.smoothedAC

    @staticmethod
    def LV_MultsFromAC(smAC):
        direction = 1.0 if LV_AUTO_AC_INDIRECT else -1.0
        factor = max(0.2, 1.0 + direction * LV_AUTO_AC_SCALE * abs(smAC))
        x = LV_AUTO_BASE_RATIO * factor
        return x, x / 2.0, x * 2.0     # initM, finalM, tpM

    # ── per-timeframe ATR + signal engine ─────────────────────────────
    def LV_RefreshAllATR(self):
        b = []
        for i in range(self.g_lvTfCount):
            sig = self.g_lvSig[i]
            if sig.atrHandle == INVALID_HANDLE:
                continue
            if CopyBuffer(sig.atrHandle, 0, 0, 1, b, as_series=True) > 0:
                sig.currentATR = b[0]

    def LV_AnchorATR(self):
        return self.g_lvSig[self.g_lvAnchorIdx].currentATR if self.g_lvTfCount > 0 else 0.0

    def LV_GetClosedHA(self, tf):
        """returns (ok, o1, c1, o2, c2)"""
        r = []
        if CopyRates(self.g_lvSymbol, tf, 1, 4, r) < 4:
            return False, 0.0, 0.0, 0.0, 0.0
        haO = [0.0] * 4
        haC = [0.0] * 4
        for k in range(4):
            haC[k] = (r[k].open + r[k].high + r[k].low + r[k].close) / 4.0
            haO[k] = (r[k].open + r[k].close) / 2.0 if k == 0 else (haO[k - 1] + haC[k - 1]) / 2.0
        return True, haO[3], haC[3], haO[2], haC[2]

    def LV_DetectTFSignal(self, i):
        """returns (fired, buy, sell)"""
        sig = self.g_lvSig[i]
        tf = sig.tf
        t0 = iTime(self.g_lvSymbol, tf, 0)
        if t0 <= 0:
            return False, False, False
        if sig.lastBarTime == 0:
            sig.lastBarTime = t0
            return False, False, False
        if t0 == sig.lastBarTime:
            return False, False, False
        sig.lastBarTime = t0
        self.LV_UpdateTFAutocorrelation(i)
        ok, o1, c1, o2, c2 = self.LV_GetClosedHA(tf)
        if not ok:
            return False, False, False
        buy = (c2 <= o2) and (c1 > o1)
        sell = (c2 >= o2) and (c1 < o1)
        if buy:
            sig.lastDir = "BULLISH"
        if sell:
            sig.lastDir = "BEARISH"
        return (buy or sell), buy, sell

    # ── same-risk lot engine ──────────────────────────────────────────
    def LV_LotDigits(self):
        step = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_VOLUME_STEP)
        if step <= 0:
            return 2
        d = int(MathRound(-math.log10(step)))
        return min(max(d, 0), 8)

    def LV_NormalizeLot(self, lot):
        step = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_VOLUME_STEP)
        bmin = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_VOLUME_MIN)
        bmax = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_VOLUME_MAX)
        if step <= 0:
            step = 0.01
        lot = math.floor(lot / step) * step
        if lot < bmin:
            lot = bmin
        if bmax > 0 and lot > bmax:
            lot = bmax
        return NormalizeDouble(lot, self.LV_LotDigits())

    def LV_LotForSL(self, slDistPrice, riskMoney):
        tickValue = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_TRADE_TICK_VALUE)
        tickSize = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_TRADE_TICK_SIZE)
        bmin = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_VOLUME_MIN)
        if slDistPrice <= 0 or tickValue <= 0 or tickSize <= 0 or riskMoney <= 0:
            return bmin
        valuePerLot = (slDistPrice / tickSize) * tickValue
        if valuePerLot <= 0:
            return bmin
        return self.LV_NormalizeLot(riskMoney / valuePerLot)

    def LV_FirstTradeRiskMoney(self):
        eq = AccountInfoDouble(ACCOUNT_EQUITY)
        return eq * self.InpLV_RiskPercent / 100.0

    # ── anchor persistence ────────────────────────────────────────────
    def LV_SaveAnchor(self):
        handle = FileOpen(self.g_lvAnchorFilePath, FILE_WRITE | FILE_CSV | FILE_ANSI, ',')
        if handle == INVALID_HANDLE:
            handle = FileOpen(self.g_lvAnchorFilePath, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',')
        if handle == INVALID_HANDLE:
            return
        FileWrite(handle, "AnchorRiskMoney", DoubleToString(self.g_lvAnchorRiskMoney, 2))
        FileClose(handle)

    def LV_LoadAnchor(self):
        handle = FileOpen(self.g_lvAnchorFilePath, FILE_READ | FILE_CSV | FILE_ANSI, ',')
        if handle == INVALID_HANDLE:
            handle = FileOpen(self.g_lvAnchorFilePath, FILE_READ | FILE_CSV | FILE_ANSI | FILE_COMMON, ',')
        if handle == INVALID_HANDLE:
            return 0.0
        val = 0.0
        if not FileIsEnding(handle):
            FileReadString(handle)
            val = StringToDouble(FileReadString(handle))
        FileClose(handle)
        return val if val > 0 else 0.0

    def LV_CountMyPositions(self):
        count = 0
        for i in range(PositionsTotal() - 1, -1, -1):
            if PositionGetSymbol(i) == self.g_lvSymbol and PositionGetInteger(POSITION_MAGIC) == self.InpLV_MagicNumber:
                count += 1
        return count

    # ── cascade manager helpers ───────────────────────────────────────
    def LV_GetChainATR(self, idx):
        ch = self.g_lvChains[idx]
        if self.InpLV_UseStaticATR:
            return ch.chainATR
        t = ch.chainTFIndex
        if 0 <= t < self.g_lvTfCount and self.g_lvSig[t].currentATR > 0:
            return self.g_lvSig[t].currentATR
        return ch.chainATR

    def LV_CalcSLPrice(self, dir_, entry, atr, mult):
        d = atr * mult
        return NormalizeDouble(entry - d if dir_ == POSITION_TYPE_BUY else entry + d, self.g_lvDigits)

    def LV_CalcNextCascadePrice(self, dir_, entry, atr, mult):
        d = atr * mult
        return NormalizeDouble(entry + d if dir_ == POSITION_TYPE_BUY else entry - d, self.g_lvDigits)

    def LV_CalcBreakevenTriggerPrice(self, dir_, entry, nextPrice, pct):
        d = abs(nextPrice - entry) * (pct / 100.0)
        return NormalizeDouble(entry + d if dir_ == POSITION_TYPE_BUY else entry - d, self.g_lvDigits)

    def LV_GetExitPrice(self, dir_):
        return SymbolInfoDouble(self.g_lvSymbol, SYMBOL_BID if dir_ == POSITION_TYPE_BUY else SYMBOL_ASK)

    @staticmethod
    def LV_HasReachedBreakevenTrigger(dir_, current, trigger):
        return current >= trigger if dir_ == POSITION_TYPE_BUY else current <= trigger

    def LV_GetPendingOrderType(self, dir_, targetPrice):
        if dir_ == POSITION_TYPE_BUY:
            return ORDER_TYPE_BUY_STOP if targetPrice > SymbolInfoDouble(self.g_lvSymbol, SYMBOL_ASK) else ORDER_TYPE_BUY_LIMIT
        return ORDER_TYPE_SELL_STOP if targetPrice < SymbolInfoDouble(self.g_lvSymbol, SYMBOL_BID) else ORDER_TYPE_SELL_LIMIT

    def LV_PositionExists(self, ticket):
        return self.g_lvPos.SelectByTicket(ticket)

    def LV_OrderExists(self, ticket):
        for i in range(OrdersTotal()):
            if self.g_lvOrd.SelectByIndex(i) and self.g_lvOrd.Ticket() == ticket:
                return True
        return False

    def LV_ModifySL(self, ticket, newSL):
        for attempt in range(self.InpLV_MaxRetry):
            if not self.g_lvPos.SelectByTicket(ticket):
                return False
            if abs(self.g_lvPos.StopLoss() - newSL) < self.g_lvPoint:
                return True
            if self.g_lvPos.Volume() <= 0:
                return False
            ResetLastError()
            if self.g_lvTrade.PositionModify(ticket, newSL, 0):
                return True
            err = GetLastError()
            if err in (4753, 4108, 4756):
                return False
            if attempt < self.InpLV_MaxRetry - 1:
                Sleep(self.InpLV_RetryDelayMs)
        return False

    def LV_UpdateAllChainSL(self, idx, newSL):
        ch = self.g_lvChains[idx]
        for i in range(ch.currentLevel + 1):
            if ch.positionActive[i]:
                if not self.LV_ModifySL(ch.tickets[i], newSL) and not self.LV_PositionExists(ch.tickets[i]):
                    ch.positionActive[i] = False
        for i in range(ch.recoveryCount):
            if ch.recoveryActive[i]:
                if not self.LV_ModifySL(ch.recoveryTickets[i], newSL) and not self.LV_PositionExists(ch.recoveryTickets[i]):
                    ch.recoveryActive[i] = False
        ch.currentSL = newSL

    def LV_PlacePendingOrder(self, idx, price, sl):
        price = NormalizeDouble(price, self.g_lvDigits)
        sl = NormalizeDouble(sl, self.g_lvDigits)
        ch = self.g_lvChains[idx]
        dir_ = ch.direction
        comment = "CASCADE_" + IntegerToString(ch.chainID) + "_L" + IntegerToString(ch.currentLevel + 1)
        lot = ch.chainLot
        for attempt in range(self.InpLV_MaxRetry):
            ot = self.LV_GetPendingOrderType(dir_, price)
            ok = False
            ResetLastError()
            if ot == ORDER_TYPE_BUY_STOP:
                ok = self.g_lvTrade.BuyStop(lot, price, self.g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment)
            elif ot == ORDER_TYPE_BUY_LIMIT:
                ok = self.g_lvTrade.BuyLimit(lot, price, self.g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment)
            elif ot == ORDER_TYPE_SELL_STOP:
                ok = self.g_lvTrade.SellStop(lot, price, self.g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment)
            elif ot == ORDER_TYPE_SELL_LIMIT:
                ok = self.g_lvTrade.SellLimit(lot, price, self.g_lvSymbol, sl, 0, ORDER_TIME_GTC, 0, comment)
            if ok:
                ch.pendingTicket = self.g_lvTrade.ResultOrder()
                ch.pendingPrice = price
                if idx not in self._lv_live:
                    self._lv_live.append(idx)
                    self._lv_live.sort()
                return True
            err = GetLastError()
            if err in (4753, 4756):
                return False
            if attempt < self.InpLV_MaxRetry - 1:
                Sleep(self.InpLV_RetryDelayMs)
        return False

    def LV_PlaceMarketOrder(self, isBuy, lot, comment):
        for attempt in range(self.InpLV_MaxRetry):
            ResetLastError()
            if isBuy:
                ok = self.g_lvTrade.Buy(lot, self.g_lvSymbol, SymbolInfoDouble(self.g_lvSymbol, SYMBOL_ASK), 0, 0, comment)
            else:
                ok = self.g_lvTrade.Sell(lot, self.g_lvSymbol, SymbolInfoDouble(self.g_lvSymbol, SYMBOL_BID), 0, 0, comment)
            if ok:
                return True
            err = GetLastError()
            if err in (4753, 4756):
                return False
            if attempt < self.InpLV_MaxRetry - 1:
                Sleep(self.InpLV_RetryDelayMs)
        return False

    def LV_ClosePositionRetry(self, ticket):
        for attempt in range(self.InpLV_MaxRetry):
            if not self.LV_PositionExists(ticket):
                return True
            ResetLastError()
            if self.g_lvTrade.PositionClose(ticket):
                return True
            err = GetLastError()
            if err in (4753, 4756):
                return False
            if attempt < self.InpLV_MaxRetry - 1:
                Sleep(self.InpLV_RetryDelayMs)
        return False

    def LV_DeleteOrderRetry(self, ticket):
        for attempt in range(self.InpLV_MaxRetry):
            if not self.LV_OrderExists(ticket):
                return True
            ResetLastError()
            if self.g_lvTrade.OrderDelete(ticket):
                return True
            err = GetLastError()
            if err in (4753, 4756):
                return False
            if attempt < self.InpLV_MaxRetry - 1:
                Sleep(self.InpLV_RetryDelayMs)
        return False

    def LV_IsTicketInAnyChain(self, ticket):
        for c in self._lv_live_idx():
            ch = self.g_lvChains[c]
            if not ch.isActive:
                continue
            if ticket in ch.tickets:
                return True
            if ticket in ch.recoveryTickets:
                return True
            if ch.pendingTicket == ticket:
                return True
        return False

    @staticmethod
    def LV_IsCascadeComment(comment):
        return comment.find("CASCADE_") == 0 or comment.find("RECOVERY_") == 0

    # ── chain initializer ─────────────────────────────────────────────
    def LV_InitializeChain(self, ticket):
        if not self.g_lvPos.SelectByTicket(ticket):
            return
        if self.LV_IsCascadeComment(self.g_lvPos.Comment()):
            return
        if self.LV_IsTicketInAnyChain(ticket):
            return
        if self.g_lvPos.Magic() != self.InpLV_MagicNumber:
            return
        if self.g_lvHaveEntryCtx:
            tfIdx = self.g_lvEntryTFIdx
            atrUsed = self.g_lvEntryATR
            initM, finalM, tpM = self.g_lvEntryInitM, self.g_lvEntryFinalM, self.g_lvEntryTPM
            lotUsed = self.g_lvEntryLot
            self.g_lvHaveEntryCtx = False
        else:
            tfIdx = self.g_lvAnchorIdx
            atrUsed = self.LV_AnchorATR()
            if atrUsed <= 0:
                atrUsed = self.g_lvSig[self.g_lvAnchorIdx].currentATR
            self.LV_UpdateTFAutocorrelation(self.g_lvAnchorIdx)
            initM, finalM, tpM = self.LV_MultsFromAC(self.g_lvSig[self.g_lvAnchorIdx].smoothedAC)
            lotUsed = self.g_lvPos.Volume()
        if atrUsed <= 0:
            return

        idx = self.g_lvTotalChains
        self.g_lvTotalChains += 1
        ch = LV_CascadeChain()
        self.g_lvChains.append(ch)
        self._lv_live.append(idx)

        ch.chainID = ticket
        ch.isActive = True
        ch.direction = self.g_lvPos.PositionType()
        ch.startTime = TimeCurrent()
        ch.chainTFIndex = tfIdx
        ch.chainATR = atrUsed
        ch.chainLot = lotUsed
        ch.currentLevel = 0
        ch.pendingTicket = 0
        ch.needsSLSync = False
        ch.chainInitSLMult = initM
        ch.chainFinalSLMult = finalM
        ch.chainTPMult = tpM
        ch.recoveryCount = 0
        ch.isRecovered = False
        ch.tickets = [ticket]
        ch.entryPrices = [self.g_lvPos.PriceOpen()]
        ch.positionActive = [True]
        ch.levelEntryPrices = [0.0]
        ch.levelThresholdPrices = [0.0]
        ch.levelBreakevenSLs = [0.0]
        ch.levelBETriggered = [False]
        ch.recoveryTickets = []
        ch.recoveryActive = []

        atr = self.LV_GetChainATR(idx)
        entry = ch.entryPrices[0]
        dir_ = ch.direction
        initialSL = self.LV_CalcSLPrice(dir_, entry, atr, ch.chainInitSLMult)
        ch.currentSL = initialSL
        if self.InpLV_OverwriteSLTP or self.g_lvPos.StopLoss() == 0:
            self.LV_ModifySL(ticket, initialSL)

        slDist = abs(entry - initialSL)
        if self.g_lvAnchorRiskMoney > 0:
            ch.initialRiskMoney = self.g_lvAnchorRiskMoney
        else:
            tickValue = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_TRADE_TICK_VALUE)
            tickSize = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_TRADE_TICK_SIZE)
            ch.initialRiskMoney = (slDist / tickSize) * tickValue * ch.chainLot if tickSize > 0 else 10.0
        if ch.initialRiskMoney <= 0:
            ch.initialRiskMoney = 10.0

        ch.recoveryGapPrice = slDist * (self.InpLV_RecoveryGapPct / 100.0)
        ch.nextRecoveryPrice = entry - ch.recoveryGapPrice if dir_ == POSITION_TYPE_BUY else entry + ch.recoveryGapPrice

        nextPrice = self.LV_CalcNextCascadePrice(dir_, entry, atr, ch.chainTPMult)
        buf = SymbolInfoInteger(self.g_lvSymbol, SYMBOL_TRADE_STOPS_LEVEL) * self.g_lvPoint
        ch.levelEntryPrices[0] = entry
        ch.levelThresholdPrices[0] = self.LV_CalcBreakevenTriggerPrice(dir_, entry, nextPrice, self.InpLV_BEThresholdPct)
        ch.levelBreakevenSLs[0] = NormalizeDouble(entry + buf if dir_ == POSITION_TYPE_BUY else entry - buf, self.g_lvDigits)

        pendingSL = self.LV_CalcSLPrice(dir_, nextPrice, atr, ch.chainFinalSLMult)
        ch.pendingOrderSL = pendingSL
        self.LV_PlacePendingOrder(idx, nextPrice, pendingSL)

    # ── recovery + breakeven + trail + cascade fill ───────────────────
    def LV_CloseEntireChain(self, idx):
        ch = self.g_lvChains[idx]
        allClosed = True
        for i in range(ch.currentLevel + 1):
            if ch.positionActive[i]:
                if self.LV_ClosePositionRetry(ch.tickets[i]):
                    ch.positionActive[i] = False
                else:
                    allClosed = False
        for i in range(ch.recoveryCount):
            if ch.recoveryActive[i]:
                if self.LV_ClosePositionRetry(ch.recoveryTickets[i]):
                    ch.recoveryActive[i] = False
                else:
                    allClosed = False
        if ch.pendingTicket > 0:
            if not self.LV_DeleteOrderRetry(ch.pendingTicket):
                allClosed = False
            ch.pendingTicket = 0
        return allClosed

    def LV_ProcessRecovery(self, idx):
        ch = self.g_lvChains[idx]
        if not ch.isActive:
            return
        totalPnL = 0.0
        activeCount = 0
        pos = self.g_lvPos
        for i in range(ch.currentLevel + 1):
            if ch.positionActive[i] and pos.SelectByTicket(ch.tickets[i]):
                totalPnL += pos.Profit() + pos.Swap() + pos.Commission()
                activeCount += 1
        for i in range(ch.recoveryCount):
            if ch.recoveryActive[i] and pos.SelectByTicket(ch.recoveryTickets[i]):
                totalPnL += pos.Profit() + pos.Swap() + pos.Commission()
                activeCount += 1
        if activeCount == 0:
            return
        if totalPnL <= -ch.initialRiskMoney:
            self.LV_CloseEntireChain(idx)
            return
        if not self.g_lvRecoveryEnabled:
            return
        if not ch.isRecovered and ch.recoveryCount > 0 and totalPnL >= ch.initialRiskMoney:
            ch.isRecovered = True
            dir_ = ch.direction
            atr = self.LV_GetChainATR(idx)
            if ch.pendingTicket > 0:
                self.LV_DeleteOrderRetry(ch.pendingTicket)
                ch.pendingTicket = 0
            refPrice = ch.entryPrices[ch.currentLevel]
            nextPrice = self.LV_CalcNextCascadePrice(dir_, refPrice, atr, ch.chainTPMult)
            pendingSL = self.LV_CalcSLPrice(dir_, nextPrice, atr, ch.chainFinalSLMult)
            ch.pendingOrderSL = pendingSL
            self.LV_PlacePendingOrder(idx, nextPrice, pendingSL)
            return
        if not ch.isRecovered:
            dir_ = ch.direction
            price = self.LV_GetExitPrice(dir_)
            triggered = price <= ch.nextRecoveryPrice if dir_ == POSITION_TYPE_BUY else price >= ch.nextRecoveryPrice
            withinSL = price > ch.currentSL if dir_ == POSITION_TYPE_BUY else price < ch.currentSL
            if triggered and withinSL:
                comment = "RECOVERY_" + IntegerToString(ch.chainID) + "_R" + IntegerToString(ch.recoveryCount + 1)
                ok = False
                for attempt in range(self.InpLV_MaxRetry):
                    if dir_ == POSITION_TYPE_BUY:
                        ok = self.g_lvTrade.Buy(ch.chainLot, self.g_lvSymbol, SymbolInfoDouble(self.g_lvSymbol, SYMBOL_ASK),
                                                ch.currentSL, 0, comment)
                    else:
                        ok = self.g_lvTrade.Sell(ch.chainLot, self.g_lvSymbol, SymbolInfoDouble(self.g_lvSymbol, SYMBOL_BID),
                                                 ch.currentSL, 0, comment)
                    if ok:
                        break
                    Sleep(self.InpLV_RetryDelayMs)
                if ok:
                    ch.recoveryCount += 1
                    ch.recoveryTickets.append(self.g_lvTrade.ResultOrder())
                    ch.recoveryActive.append(True)
                    ch.nextRecoveryPrice += -ch.recoveryGapPrice if dir_ == POSITION_TYPE_BUY else ch.recoveryGapPrice

    def LV_UpdatePendingOrderSL(self, idx, newSL):
        ch = self.g_lvChains[idx]
        if ch.pendingTicket == 0:
            return
        if not self.LV_OrderExists(ch.pendingTicket):
            ch.pendingTicket = 0
            return
        dir_ = ch.direction
        needsUpdate = newSL > ch.pendingOrderSL if dir_ == POSITION_TYPE_BUY else newSL < ch.pendingOrderSL
        if not needsUpdate:
            return
        oldTicket = ch.pendingTicket
        orderPrice = ch.pendingPrice
        if not self.LV_DeleteOrderRetry(oldTicket):
            return
        ch.pendingTicket = 0
        ch.pendingOrderSL = newSL
        self.LV_PlacePendingOrder(idx, orderPrice, newSL)

    def LV_ProcessBreakeven(self, idx):
        if not self.InpLV_EnableFirstBE and not self.InpLV_EnableEveryCascadeBE:
            return
        ch = self.g_lvChains[idx]
        if ch.pendingTicket == 0:
            return
        level = ch.currentLevel if self.InpLV_EnableEveryCascadeBE else 0
        if ch.levelBETriggered[level]:
            return
        if not ch.positionActive[level]:
            return
        if not self.LV_PositionExists(ch.tickets[level]):
            ch.positionActive[level] = False
            return
        dir_ = ch.direction
        if self.LV_HasReachedBreakevenTrigger(dir_, self.LV_GetExitPrice(dir_), ch.levelThresholdPrices[level]):
            beSL = ch.levelBreakevenSLs[level]
            self.LV_UpdateAllChainSL(idx, beSL)
            ch.levelBETriggered[level] = True
            self.LV_UpdatePendingOrderSL(idx, beSL)

    def LV_ManageTrailingStop(self, idx):
        ch = self.g_lvChains[idx]
        if not self.InpLV_EnableTrail or not ch.isActive:
            return
        dir_ = ch.direction
        currentPrice = self.LV_GetExitPrice(dir_)
        trailStep = self.LV_GetChainATR(idx) * ch.chainFinalSLMult
        if dir_ == POSITION_TYPE_BUY:
            newSL = NormalizeDouble(currentPrice - trailStep, self.g_lvDigits)
            if newSL > ch.currentSL + self.g_lvPoint:
                self.LV_UpdateAllChainSL(idx, newSL)
        else:
            newSL = NormalizeDouble(currentPrice + trailStep, self.g_lvDigits)
            if newSL < ch.currentSL - self.g_lvPoint or ch.currentSL == 0:
                self.LV_UpdateAllChainSL(idx, newSL)

    def LV_ProcessCascadeFill(self, idx):
        ch = self.g_lvChains[idx]
        if ch.pendingTicket == 0:
            return
        pt = ch.pendingTicket
        if self.LV_PositionExists(pt):
            newLevel = ch.currentLevel + 1
            for arr, fill in ((ch.tickets, 0), (ch.entryPrices, 0.0), (ch.positionActive, False),
                              (ch.levelEntryPrices, 0.0), (ch.levelThresholdPrices, 0.0),
                              (ch.levelBreakevenSLs, 0.0), (ch.levelBETriggered, False)):
                _resize(arr, newLevel + 1, fill)
            self.g_lvPos.SelectByTicket(pt)
            newEntry = self.g_lvPos.PriceOpen()
            ch.tickets[newLevel] = pt
            ch.entryPrices[newLevel] = newEntry
            ch.positionActive[newLevel] = True
            ch.currentLevel = newLevel
            ch.pendingTicket = 0
            ch.needsSLSync = True
            ch.levelBETriggered[newLevel] = False

            atr = self.LV_GetChainATR(idx)
            dir_ = ch.direction
            newSL = self.LV_CalcSLPrice(dir_, newEntry, atr, ch.chainFinalSLMult)
            self.LV_UpdateAllChainSL(idx, newSL)

            nextPrice = self.LV_CalcNextCascadePrice(dir_, newEntry, atr, ch.chainTPMult)
            buf = SymbolInfoInteger(self.g_lvSymbol, SYMBOL_TRADE_STOPS_LEVEL) * self.g_lvPoint
            ch.levelEntryPrices[newLevel] = newEntry
            ch.levelThresholdPrices[newLevel] = self.LV_CalcBreakevenTriggerPrice(dir_, newEntry, nextPrice,
                                                                                   self.InpLV_BEThresholdPct)
            ch.levelBreakevenSLs[newLevel] = NormalizeDouble(newEntry + buf if dir_ == POSITION_TYPE_BUY
                                                             else newEntry - buf, self.g_lvDigits)
            pendingSL = self.LV_CalcSLPrice(dir_, nextPrice, atr, ch.chainFinalSLMult)
            ch.pendingOrderSL = pendingSL
            self.LV_PlacePendingOrder(idx, nextPrice, pendingSL)
        elif not self.LV_OrderExists(pt):
            ch.pendingTicket = 0
            ch.pendingOrderSL = 0.0

    def LV_SyncNewCascadeSL(self, idx):
        ch = self.g_lvChains[idx]
        if not ch.needsSLSync:
            return
        ch.needsSLSync = False
        ticket = ch.tickets[ch.currentLevel]
        if not self.LV_PositionExists(ticket):
            return
        if abs(self.g_lvPos.StopLoss() - ch.currentSL) > self.g_lvPoint:
            self.LV_ModifySL(ticket, ch.currentSL)

    def LV_ProcessChainTermination(self, idx):
        ch = self.g_lvChains[idx]
        active = closed = 0
        for i in range(ch.currentLevel + 1):
            if ch.positionActive[i]:
                if self.LV_PositionExists(ch.tickets[i]):
                    active += 1
                else:
                    ch.positionActive[i] = False
                    closed += 1
        for i in range(ch.recoveryCount):
            if ch.recoveryActive[i]:
                if self.LV_PositionExists(ch.recoveryTickets[i]):
                    active += 1
                else:
                    ch.recoveryActive[i] = False
                    closed += 1
        if closed > 0 and active > 0:
            if self.LV_CloseEntireChain(idx):
                ch.isActive = False
        elif active == 0:
            if ch.pendingTicket > 0:
                if self.LV_DeleteOrderRetry(ch.pendingTicket):
                    ch.pendingTicket = 0
            ch.isActive = False

    def LV_ManageChains(self):
        for c in self._lv_live_idx():
            if not self.g_lvChains[c].isActive:
                continue
            self.LV_ProcessRecovery(c)
            self.LV_ProcessCascadeFill(c)
            self.LV_SyncNewCascadeSL(c)
            self.LV_ProcessBreakeven(c)
            self.LV_ManageTrailingStop(c)
            self.LV_ProcessChainTermination(c)

    # ── system state helpers ──────────────────────────────────────────
    def LV_PurgeOrphanedPendingOrders(self):
        for c in self._lv_live_idx():
            ch = self.g_lvChains[c]
            if ch.pendingTicket == 0:
                continue
            active = 0
            for i in range(ch.currentLevel + 1):
                if ch.positionActive[i] and self.LV_PositionExists(ch.tickets[i]):
                    active += 1
            for i in range(ch.recoveryCount):
                if ch.recoveryActive[i] and self.LV_PositionExists(ch.recoveryTickets[i]):
                    active += 1
            if active == 0:
                if self.LV_DeleteOrderRetry(ch.pendingTicket):
                    ch.pendingTicket = 0
                ch.isActive = False

    def LV_IsSystemFlat(self):
        if self.LV_CountMyPositions() > 0:
            return False
        self.LV_PurgeOrphanedPendingOrders()
        for i in range(OrdersTotal()):
            if (self.g_lvOrd.SelectByIndex(i) and self.g_lvOrd.Magic() == self.InpLV_MagicNumber
                    and self.g_lvOrd.Symbol() == self.g_lvSymbol):
                return False
        for c in self._lv_live_idx():
            self.g_lvChains[c].isActive = False
        return True

    def LV_CleanFlatState(self):
        for i in range(OrdersTotal() - 1, -1, -1):
            if (self.g_lvOrd.SelectByIndex(i) and self.g_lvOrd.Symbol() == self.g_lvSymbol
                    and self.g_lvOrd.Magic() == self.InpLV_MagicNumber):
                self.LV_DeleteOrderRetry(self.g_lvOrd.Ticket())
        for c in self._lv_live_idx():
            self.g_lvChains[c].pendingTicket = 0
            self.g_lvChains[c].isActive = False

    def LV_ScanForNewTrades(self):
        pos = self.g_lvPos
        for i in range(PositionsTotal() - 1, -1, -1):
            if not pos.SelectByIndex(i):
                continue
            if pos.Symbol() != self.g_lvSymbol or pos.Magic() != self.InpLV_MagicNumber:
                continue
            ticket = pos.Ticket()
            if self.LV_IsTicketInAnyChain(ticket) or self.LV_IsCascadeComment(pos.Comment()):
                continue
            existingIdx = -1
            for c in self._lv_live_idx():
                if self.g_lvChains[c].isActive and self.g_lvChains[c].direction == pos.PositionType():
                    existingIdx = c
                    break
            if existingIdx >= 0:
                ch = self.g_lvChains[existingIdx]
                ch.recoveryCount += 1
                ch.recoveryTickets.append(ticket)
                ch.recoveryActive.append(True)
                if self.InpLV_OverwriteSLTP or pos.StopLoss() == 0:
                    self.LV_ModifySL(ticket, ch.currentSL)
            else:
                self.LV_InitializeChain(ticket)

    # ── signal → entry decision ───────────────────────────────────────
    def LV_EvaluateSignals(self):
        flat = self.LV_IsSystemFlat()
        placedThisTick = False
        for i in range(self.g_lvTfCount):
            fired, buy, sell = self.LV_DetectTFSignal(i)
            if not fired or placedThisTick:
                continue
            if not flat:
                continue
            if self.g_lvAwaitingFirstTrade and i != self.g_lvAnchorIdx:
                continue
            atr = self.g_lvSig[i].currentATR
            if atr <= 0:
                continue
            initM, finalM, tpM = self.LV_MultsFromAC(self.g_lvSig[i].smoothedAC)
            slDist = atr * initM
            if self.g_lvAwaitingFirstTrade:
                riskMoney = self.LV_FirstTradeRiskMoney()
            else:
                riskMoney = self.g_lvAnchorRiskMoney if self.g_lvAnchorRiskMoney > 0 else self.LV_FirstTradeRiskMoney()
            lot = self.LV_LotForSL(slDist, riskMoney)

            self.g_lvHaveEntryCtx = True
            self.g_lvEntryTFIdx = i
            self.g_lvEntryATR = atr
            self.g_lvEntryInitM = initM
            self.g_lvEntryFinalM = finalM
            self.g_lvEntryTPM = tpM
            self.g_lvEntryLot = lot

            self.LV_CleanFlatState()
            ok = self.LV_PlaceMarketOrder(buy, lot, self.InpLV_Comment + "|TF" + IntegerToString(self.g_lvSig[i].minutes))
            if ok:
                if self.g_lvAwaitingFirstTrade:
                    self.g_lvAnchorRiskMoney = riskMoney
                    self.LV_SaveAnchor()
                    self.g_lvAwaitingFirstTrade = False
                self.LV_ScanForNewTrades()
                self.g_lvLastPositionCount = self.LV_CountMyPositions()
                placedThisTick = True
                flat = False
            else:
                self.g_lvHaveEntryCtx = False

    # ── init / deinit / one pass ──────────────────────────────────────
    def LV_Init(self):
        self.g_lvPoint = SymbolInfoDouble(self.g_lvSymbol, SYMBOL_POINT)
        self.g_lvDigits = SymbolInfoInteger(self.g_lvSymbol, SYMBOL_DIGITS)
        if self.g_lvPoint <= 0:
            self.MixFail("[LeVanDo] cannot read symbol properties for '" + self.g_lvSymbol + "'.")
            return False
        self.g_lvTrade.SetExpertMagicNumber(self.InpLV_MagicNumber)
        self.g_lvTrade.SetDeviationInPoints(10)
        self.g_lvTrade.SetTypeFilling(ORDER_FILLING_RETURN)
        self.g_lvTrade.SetAsyncMode(False)
        self.g_lvRecoveryEnabled = (self.InpLV_RecoveryGapPct > 0.0)
        if not self.LV_ParseTimeframes():
            self.MixFail('[LeVanDo] timeframes input parsed to zero valid timeframes — e.g. "30,60,120,240"')
            return False
        for i in range(self.g_lvTfCount):
            self.g_lvSig[i].atrHandle = iATR(self.g_lvSymbol, self.g_lvSig[i].tf, self.InpLV_ATRPeriod)
            if self.g_lvSig[i].atrHandle == INVALID_HANDLE:
                self.MixFail("[LeVanDo] iATR handle failed for " + TFToText(self.g_lvSig[i].tf))
                return False
        Sleep(100)
        self.LV_RefreshAllATR()
        for i in range(self.g_lvTfCount):
            self.g_lvSig[i].lastBarTime = iTime(self.g_lvSymbol, self.g_lvSig[i].tf, 0)
            self.LV_UpdateTFAutocorrelation(i)
        self.g_lvAnchorFilePath = self.InpLV_FileName + "_" + self.g_lvSymbol + ".csv"
        if self.InpLV_ResetAnchor:
            FileDelete(self.g_lvAnchorFilePath)
        self.g_lvAnchorRiskMoney = self.LV_LoadAnchor()
        self.g_lvLastPositionCount = self.LV_CountMyPositions()
        self.LV_ScanForNewTrades()
        if self.LV_IsSystemFlat():
            self.g_lvAwaitingFirstTrade = True
        else:
            self.g_lvAwaitingFirstTrade = False
            if self.g_lvAnchorRiskMoney <= 0:
                self.g_lvAnchorRiskMoney = self.LV_FirstTradeRiskMoney()
                self.LV_SaveAnchor()
        self.LV_UpdateDashboard()
        tfTxt = ",".join(TFToText(s.tf) for s in self.g_lvSig)
        Print("ENGINE B: LeVanDo Multi-TF v4.10 ready. Asset: ", self.g_lvSymbol, " | Timeframes: ", tfTxt,
              " | Anchor TF: ", TFToText(self.g_lvSig[self.g_lvAnchorIdx].tf),
              " | Anchor risk $: ", DoubleToString(self.g_lvAnchorRiskMoney, 2),
              " | Recovery: ", "ON" if self.g_lvRecoveryEnabled else "OFF", " | Magic=", self.InpLV_MagicNumber)
        return True

    def LV_Deinit(self):
        for i in range(self.g_lvTfCount):
            if self.g_lvSig[i].atrHandle != INVALID_HANDLE:
                IndicatorRelease(self.g_lvSig[i].atrHandle)
                self.g_lvSig[i].atrHandle = INVALID_HANDLE
        self.LV_CleanDashboard()

    def LV_Process(self):
        self.g_lvTickCounter += 1
        self.LV_RefreshAllATR()
        currentPositions = self.LV_CountMyPositions()
        if currentPositions != self.g_lvLastPositionCount:
            if currentPositions < self.g_lvLastPositionCount:
                self.LV_PurgeOrphanedPendingOrders()
            self.g_lvLastPositionCount = currentPositions
            self.LV_ScanForNewTrades()
        self.LV_EvaluateSignals()
        self.LV_ManageChains()
        if self.g_lvTickCounter % 5 == 0:
            self.LV_UpdateDashboard()

    # ╔═══════════════════════════════════════════════════════════════╗
    # ║                     EXPERT EVENT HANDLERS                     ║
    # ╚═══════════════════════════════════════════════════════════════╝
    def OnInit(self):
        if not self.InpGZ_Enable and not self.InpLV_Enable:
            self.MixFail("both engines are disabled — enable at least one.")
            return INIT_PARAMETERS_INCORRECT
        if self.InpGZ_Enable:
            ok, self.g_gzSymbol = self.ResolveSymbol(self.InpGZ_Symbol, "GridZ")
            if not ok:
                return INIT_PARAMETERS_INCORRECT
        if self.InpLV_Enable:
            ok, self.g_lvSymbol = self.ResolveSymbol(self.InpLV_Symbol, "LeVanDo")
            if not ok:
                return INIT_PARAMETERS_INCORRECT
        if self.InpGZ_Enable and self.InpLV_Enable and self.g_gzSymbol == self.g_lvSymbol:
            if self.InpGZ_Magic == self.InpLV_MagicNumber:
                self.MixFail("both engines trade " + self.g_gzSymbol + " with the SAME magic number. " +
                             "Give each engine its own magic so they cannot touch each other's trades.")
                return INIT_PARAMETERS_INCORRECT
            if AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING:
                Print("Zscore and Levando MIX WARNING: this is not a hedging account.")
        if self.InpGZ_Enable and not self.GZ_Init():
            return INIT_FAILED
        if self.InpLV_Enable and not self.LV_Init():
            return INIT_FAILED
        self.g_gzOnTimer = (self.InpGZ_Enable and self.g_gzSymbol != Symbol())
        self.g_lvOnTimer = (self.InpLV_Enable and self.g_lvSymbol != Symbol())
        if self.g_gzOnTimer or self.g_lvOnTimer:
            EventSetMillisecondTimer(200)
        Print("Zscore and Levando MIX ready | Engine A (GridZ): ",
              (self.g_gzSymbol + " " + TFToText(self.g_gzTF) + (" [timer]" if self.g_gzOnTimer else " [chart ticks]"))
              if self.InpGZ_Enable else "OFF",
              " | Engine B (LeVanDo): ",
              (self.g_lvSymbol + " " + self.InpLV_Timeframes + (" [timer]" if self.g_lvOnTimer else " [chart ticks]"))
              if self.InpLV_Enable else "OFF")
        return INIT_SUCCEEDED

    def OnDeinit(self, reason):
        EventKillTimer()
        self.GZ_Deinit()
        self.LV_Deinit()

    def OnTick(self):
        if self.InpGZ_Enable and not self.g_gzOnTimer:
            self.GZ_Process()
        if self.InpLV_Enable and not self.g_lvOnTimer:
            self.LV_Process()

    def OnTimer(self):
        if self.InpGZ_Enable and self.g_gzOnTimer and self.IsNewQuote(self.g_gzSymbol, "gz"):
            self.GZ_Process()
        if self.InpLV_Enable and self.g_lvOnTimer and self.IsNewQuote(self.g_lvSymbol, "lv"):
            self.LV_Process()

    def OnTester(self):
        profit = TesterStatistics(STAT_PROFIT)
        dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT)
        if dd < 0.01:
            dd = 0.01
        return profit / dd
