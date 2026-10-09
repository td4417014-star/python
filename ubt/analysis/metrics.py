"""Performance metrics: everything the MT5 tester report shows plus common
risk-adjusted statistics (Sharpe, Sortino, Calmar, CAGR, SQN, Ulcer, ...)."""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from ..mql5 import constants as C


def trades_from_deals(deals: pd.DataFrame) -> pd.DataFrame:
    """One row per closing deal (MT5 'trade'), with the entry commission allocated by volume."""
    if deals.empty:
        return pd.DataFrame(columns=["position_id", "symbol", "direction", "volume", "open_time", "close_time",
                                     "open_price", "close_price", "profit", "swap", "commission", "net",
                                     "reason", "magic", "comment"])
    d = deals[deals["type"].isin([C.DEAL_TYPE_BUY, C.DEAL_TYPE_SELL])]
    ins = d[d["entry"] == C.DEAL_ENTRY_IN].set_index("position_id")
    outs = d[d["entry"].isin([C.DEAL_ENTRY_OUT, C.DEAL_ENTRY_OUT_BY, C.DEAL_ENTRY_INOUT])]
    rows = []
    for _, o in outs.iterrows():
        pid = o["position_id"]
        if pid in ins.index:
            i = ins.loc[pid]
            if isinstance(i, pd.DataFrame):
                i = i.iloc[0]
            share = o["volume"] / i["volume"] if i["volume"] else 1.0
            in_comm = i["commission"] * share
            open_time, open_price = i["time"], i["price"]
            direction = "buy" if i["type"] == C.DEAL_TYPE_BUY else "sell"
            in_magic, in_comment = i["magic"], i["comment"]
        else:
            in_comm, open_time, open_price = 0.0, o["time"], o["price"]
            direction = "sell" if o["type"] == C.DEAL_TYPE_BUY else "buy"
            in_magic, in_comment = o["magic"], o["comment"]
        comm = o["commission"] + in_comm
        rows.append({"position_id": pid, "symbol": o["symbol"], "direction": direction, "volume": o["volume"],
                     "open_time": open_time, "close_time": o["time"], "open_price": open_price,
                     "close_price": o["price"], "profit": o["profit"], "swap": o["swap"], "commission": comm,
                     "net": o["profit"] + o["swap"] + comm, "reason": o["reason"], "magic": in_magic,
                     "comment": in_comment, "close_comment": o["comment"]})
    return pd.DataFrame(rows)


def _max_consecutive(x: np.ndarray, win: bool):
    best_n = best_sum = cur_n = cur_sum = 0
    for v in x:
        if (v > 0) == win and v != 0:
            cur_n += 1
            cur_sum += v
            if cur_n > best_n or (cur_n == best_n and abs(cur_sum) > abs(best_sum)):
                best_n, best_sum = cur_n, cur_sum
        else:
            cur_n = cur_sum = 0
    return best_n, best_sum


def _dd(series: np.ndarray):
    """max money DD, % at that moment, max relative % DD."""
    if len(series) == 0:
        return 0.0, 0.0, 0.0
    peak = np.maximum.accumulate(series)
    dd = peak - series
    i = int(np.argmax(dd))
    money = float(dd[i])
    pct_at = float(dd[i] / peak[i] * 100) if peak[i] > 0 else 0.0
    rel = dd / np.where(peak > 0, peak, np.nan) * 100
    return money, pct_at, float(np.nanmax(rel)) if len(rel) else 0.0


def compute_metrics(deals: pd.DataFrame, equity: pd.DataFrame, deposit: float,
                    start: int, end: int, broker_stats: Optional[dict] = None) -> dict:
    tr = trades_from_deals(deals)
    m: dict = {}
    m[C.STAT_INITIAL_DEPOSIT] = deposit
    net = tr["net"].to_numpy(float) if len(tr) else np.array([])
    n = len(net)
    final_balance = deposit + float(net.sum()) if n else deposit
    if broker_stats and "final_balance" in broker_stats:
        final_balance = broker_stats["final_balance"]
    m["final_balance"] = final_balance
    m[C.STAT_PROFIT] = final_balance - deposit
    m["net_profit_pct"] = (final_balance - deposit) / deposit * 100 if deposit else 0.0
    wins = net[net > 0]
    losses = net[net < 0]
    m[C.STAT_GROSS_PROFIT] = float(wins.sum())
    m[C.STAT_GROSS_LOSS] = float(losses.sum())
    m[C.STAT_PROFIT_FACTOR] = (float(wins.sum() / -losses.sum()) if losses.sum() < 0
                               else (float("inf") if wins.sum() > 0 else 0.0))
    m[C.STAT_TRADES] = n
    m[C.STAT_DEALS] = int((deals["type"] != C.DEAL_TYPE_BALANCE).sum()) if len(deals) else 0
    m[C.STAT_PROFIT_TRADES] = int((net > 0).sum())
    m[C.STAT_LOSS_TRADES] = int((net < 0).sum())
    m["win_rate"] = m[C.STAT_PROFIT_TRADES] / n * 100 if n else 0.0
    m[C.STAT_EXPECTED_PAYOFF] = float(net.mean()) if n else 0.0
    m[C.STAT_MAX_PROFITTRADE] = float(net.max()) if n else 0.0
    m[C.STAT_MAX_LOSSTRADE] = float(net.min()) if n else 0.0
    m["avg_win"] = float(wins.mean()) if len(wins) else 0.0
    m["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
    m["payoff_ratio"] = m["avg_win"] / -m["avg_loss"] if m["avg_loss"] < 0 else 0.0
    if n:
        longs = tr["direction"] == "buy"
        m[C.STAT_LONG_TRADES] = int(longs.sum())
        m[C.STAT_SHORT_TRADES] = int((~longs).sum())
        m[C.STAT_PROFIT_LONGTRADES] = int(((tr["net"] > 0) & longs).sum())
        m[C.STAT_PROFIT_SHORTTRADES] = int(((tr["net"] > 0) & ~longs).sum())
    else:
        m[C.STAT_LONG_TRADES] = m[C.STAT_SHORT_TRADES] = 0
        m[C.STAT_PROFIT_LONGTRADES] = m[C.STAT_PROFIT_SHORTTRADES] = 0
    m[C.STAT_MAX_CONWINS], m["max_consecutive_profit"] = _max_consecutive(net, True)
    m[C.STAT_MAX_CONLOSSES], m["max_consecutive_loss"] = _max_consecutive(net, False)

    # balance curve after each closing deal
    bal = np.concatenate([[deposit], deposit + np.cumsum(net)]) if n else np.array([deposit])
    m[C.STAT_BALANCEMIN] = float(bal.min())
    m[C.STAT_BALANCE_DD], m[C.STAT_BALANCEDD_PERCENT], m[C.STAT_BALANCE_DDREL_PERCENT] = _dd(bal)

    # equity drawdown: tick-level values from the broker when available
    if broker_stats:
        m[C.STAT_EQUITY_DD] = broker_stats.get("max_dd_money", 0.0)
        m[C.STAT_EQUITYDD_PERCENT] = broker_stats.get("max_dd_money_pct", 0.0)
        m[C.STAT_EQUITY_DDREL_PERCENT] = broker_stats.get("max_dd_rel_pct", 0.0)
        m[C.STAT_EQUITYMIN] = broker_stats.get("min_equity", deposit)
        m[C.STAT_MIN_MARGINLEVEL] = broker_stats.get("min_margin_level", 0.0)
        m["stopped_out"] = bool(broker_stats.get("stopped_out", False))
        m["blown"] = bool(broker_stats.get("blown", False))
    elif len(equity):
        e = equity["equity_min"].to_numpy(float) if "equity_min" in equity else equity["equity"].to_numpy(float)
        m[C.STAT_EQUITY_DD], m[C.STAT_EQUITYDD_PERCENT], m[C.STAT_EQUITY_DDREL_PERCENT] = _dd(e)
        m[C.STAT_EQUITYMIN] = float(e.min())
    m["equity_dd_abs"] = max(0.0, deposit - m.get(C.STAT_EQUITYMIN, deposit))
    m[C.STAT_RECOVERY_FACTOR] = (m[C.STAT_PROFIT] / m[C.STAT_EQUITY_DD]) if m.get(C.STAT_EQUITY_DD, 0) > 0 else 0.0

    # trade-based ratios (MT5 style)
    if n:
        before = bal[:-1]
        hpr = np.where(before > 0, bal[1:] / before, 1.0)
        r = hpr - 1.0
        m["ahpr"] = float(hpr.mean())
        m["ghpr"] = float(np.exp(np.log(np.clip(hpr, 1e-12, None)).mean()))
        m[C.STAT_SHARPE_RATIO] = float(r.mean() / r.std(ddof=1)) if n > 1 and r.std(ddof=1) > 0 else 0.0
        m["sqn"] = float(math.sqrt(min(n, 100)) * net.mean() / net.std(ddof=1)) if n > 1 and net.std(ddof=1) > 0 else 0.0
        if n > 2:
            x = np.arange(len(bal))
            coef = np.polyfit(x, bal, 1)
            fit = np.polyval(coef, x)
            m["lr_correlation"] = float(np.corrcoef(x, bal)[0, 1]) if bal.std() > 0 else 0.0
            m["lr_std_error"] = float(np.sqrt(((bal - fit) ** 2).sum() / max(len(bal) - 2, 1)))
        else:
            m["lr_correlation"] = m["lr_std_error"] = 0.0
        w = (net > 0).astype(int)
        W, L = int(w.sum()), int(n - w.sum())
        runs = 1 + int((np.diff(w) != 0).sum())
        X = 2.0 * W * L
        if n > 1 and X > 0 and X != n:
            m["z_score"] = float((n * (runs - 0.5) - X) / math.sqrt(X * (X - n) / (n - 1)))
        else:
            m["z_score"] = 0.0
        hold = (tr["close_time"] - tr["open_time"]).to_numpy(float)
        m["avg_holding_hours"] = float(hold.mean() / 3600)
    else:
        for k in ("ahpr", "ghpr", C.STAT_SHARPE_RATIO, "sqn", "lr_correlation", "lr_std_error", "z_score",
                  "avg_holding_hours"):
            m[k] = 0.0

    # time-based statistics from the equity curve
    years = max((end - start) / (365.25 * 86400), 1e-9)
    m["years"] = years
    fb = max(final_balance, 1e-9)
    m["cagr_pct"] = ((fb / deposit) ** (1 / years) - 1) * 100 if deposit > 0 and years > 0.01 else 0.0
    m["calmar"] = m["cagr_pct"] / m[C.STAT_EQUITY_DDREL_PERCENT] if m.get(C.STAT_EQUITY_DDREL_PERCENT, 0) > 0 else 0.0
    m["return_dd_ratio"] = m["net_profit_pct"] / m[C.STAT_EQUITY_DDREL_PERCENT] if m.get(C.STAT_EQUITY_DDREL_PERCENT, 0) > 0 else 0.0
    m["trades_per_month"] = n / (years * 12) if years > 0 else 0.0
    if len(equity) > 2:
        eq = equity.set_index(pd.to_datetime(equity["time"], unit="s"))["equity"]
        daily = eq.resample("1D").last().dropna()
        dr = daily.pct_change().dropna()
        if len(dr) > 2 and dr.std() > 0:
            m["sharpe_annual"] = float(dr.mean() / dr.std() * math.sqrt(365))
            neg = dr[dr < 0]
            dn = math.sqrt((neg ** 2).sum() / len(dr)) if len(neg) else 0.0
            m["sortino_annual"] = float(dr.mean() / dn * math.sqrt(365)) if dn > 0 else 0.0
        else:
            m["sharpe_annual"] = m["sortino_annual"] = 0.0
        peak = daily.cummax()
        ddp = (peak - daily) / peak * 100
        m["ulcer_index"] = float(np.sqrt((ddp ** 2).mean())) if len(ddp) else 0.0
        monthly = eq.resample("ME").last().dropna()
        mret = monthly.pct_change().dropna() if len(monthly) > 1 else pd.Series(dtype=float)
        if len(monthly):
            first = (monthly.iloc[0] / deposit - 1) if deposit else 0.0
            mret = pd.concat([pd.Series([first], index=[monthly.index[0]]), mret])
        m["profitable_months_pct"] = float((mret > 0).mean() * 100) if len(mret) else 0.0
        m["best_month_pct"] = float(mret.max() * 100) if len(mret) else 0.0
        m["worst_month_pct"] = float(mret.min() * 100) if len(mret) else 0.0
        if "in_market" in equity:
            m["exposure_pct"] = float(equity["in_market"].mean() * 100)
    else:
        for k in ("sharpe_annual", "sortino_annual", "ulcer_index", "profitable_months_pct",
                  "best_month_pct", "worst_month_pct"):
            m[k] = 0.0
    return m


KEY_METRICS = [C.STAT_PROFIT, "net_profit_pct", C.STAT_PROFIT_FACTOR, C.STAT_EXPECTED_PAYOFF, C.STAT_TRADES,
               "win_rate", C.STAT_EQUITY_DDREL_PERCENT, C.STAT_EQUITY_DD, C.STAT_RECOVERY_FACTOR,
               C.STAT_SHARPE_RATIO, "sharpe_annual", "sortino_annual", "cagr_pct", "calmar", "sqn",
               "ulcer_index", "profitable_months_pct", "ontester", "stopped_out", "blown"]


def format_metrics(m: dict, keys=None) -> str:
    keys = keys or [k for k in KEY_METRICS if k in m]
    w = max(len(k) for k in keys)
    out = []
    for k in keys:
        v = m.get(k)
        if isinstance(v, float):
            v = f"{v:,.4f}" if abs(v) < 100 else f"{v:,.2f}"
        out.append(f"{k:<{w}}  {v}")
    return "\n".join(out)
