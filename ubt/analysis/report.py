"""Self-contained HTML reports (tables + embedded PNG charts)."""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .metrics import KEY_METRICS

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _HAVE_MPL = True
except Exception:   # charts are optional
    _HAVE_MPL = False

_CSS = """
:root{--bg:#ffffff;--fg:#1d2330;--muted:#5d6779;--line:#d9dee7;--card:#f6f8fb;--good:#1a7f4b;--bad:#b42318}
@media (prefers-color-scheme: dark){:root{--bg:#12151c;--fg:#e6e9ef;--muted:#9aa3b2;--line:#2b313d;--card:#1a1f29;
--good:#4cc38a;--bad:#f97066}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;
padding:24px 16px;max-width:1200px;margin:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:8px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.kpi b{display:block;font-size:17px;font-variant-numeric:tabular-nums}.kpi span{font-size:12px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums;display:block;overflow-x:auto}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{background:var(--card);position:sticky;top:0}
img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px;background:#fff}
.good{color:var(--good)}.bad{color:var(--bad)}
"""


def _img(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return f'<img alt="chart" src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}">'


def _fmt(v):
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return str(v)
        return f"{v:,.2f}" if abs(v) >= 100 else f"{v:,.4f}"
    return html.escape(str(v))


def _table(df: pd.DataFrame, max_rows: int = 60) -> str:
    if df is None or len(df) == 0:
        return "<p class='muted'>no rows</p>"
    df = df.head(max_rows)
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = "".join("<tr>" + "".join(f"<td>{_fmt(v)}</td>" for v in row) + "</tr>"
                   for row in df.itertuples(index=False))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _kpis(m: dict, keys=None) -> str:
    keys = keys or [k for k in KEY_METRICS if k in m]
    cells = []
    for k in keys:
        v = m.get(k)
        cls = ""
        if k in ("net_profit", "net_profit_pct") and isinstance(v, (int, float)):
            cls = "good" if v > 0 else "bad"
        cells.append(f"<div class='kpi'><span>{html.escape(k)}</span><b class='{cls}'>{_fmt(v)}</b></div>")
    return "<div class='grid'>" + "".join(cells) + "</div>"


def _page(title: str, sub: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{html.escape(title)}</title><style>{_CSS}</style></head><body>"
            f"<h1>{html.escape(title)}</h1><div class='muted'>{html.escape(sub)}</div>{body}</body></html>")


# ---------------------------------------------------------------------- backtest
def backtest_section(res) -> str:
    m = res.metrics
    out = [_kpis(m)]
    if _HAVE_MPL and len(res.equity) > 1:
        eq = res.equity
        t = pd.to_datetime(eq["time"], unit="s")
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        a1.plot(t, eq["equity"], lw=1, label="equity", color="#2f6fde")
        a1.plot(t, eq["balance"], lw=1.2, label="balance", color="#1a7f4b")
        a1.legend(loc="upper left", frameon=False)
        a1.set_ylabel("account")
        peak = eq["equity"].cummax()
        dd = (peak - eq["equity_min"]) / peak * 100
        a2.fill_between(t, 0, -dd, color="#b42318", alpha=0.5, lw=0)
        a2.set_ylabel("DD %")
        for a in (a1, a2):
            a.grid(alpha=0.25)
            a.spines[["top", "right"]].set_visible(False)
        out.append("<h2>Equity and drawdown</h2>" + _img(fig))
    out.append("<h2>All metrics</h2>" + _table(pd.DataFrame(
        [(k, v) for k, v in m.items() if not isinstance(v, (dict, list))], columns=["metric", "value"]), 200))
    if len(res.trades):
        out.append("<h2>Trades (first 60)</h2>" + _table(res.trades))
    out.append("<h2>Inputs</h2>" + _table(pd.DataFrame(list(res.inputs.items()), columns=["input", "value"]), 200))
    return "".join(out)


def backtest_report(res, path: str | Path, title: str = "Backtest report") -> Path:
    cfg = res.config
    sub = (f"{cfg['symbol']} {cfg['timeframe']} | {cfg['start']} → {cfg['end']} | model {cfg['model']} | "
           f"{res.ticks:,} ticks in {res.seconds:.1f}s")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(_page(title, sub, backtest_section(res)), encoding="utf-8")
    return Path(path)


# ---------------------------------------------------------------------- optimisation
def optimization_section(opt) -> str:
    out = ["<h2>Optimisation summary</h2>", _kpis(opt.summary, [k for k in opt.summary if not isinstance(opt.summary[k], dict)])]
    out.append("<h2>Best settings vs robust-best settings</h2>")
    rows = [(k, opt.best.get(k), opt.robust_best.get(k)) for k in opt.space.names]
    out.append(_table(pd.DataFrame(rows, columns=["parameter", "best", "robust best (plateau)"]), 200))
    if opt.importance:
        out.append("<h2>Parameter importance (share of objective variance)</h2>")
        imp = pd.DataFrame(list(opt.importance.items()), columns=["parameter", "importance"])
        if _HAVE_MPL:
            fig, ax = plt.subplots(figsize=(8, 0.35 * len(imp) + 1))
            ax.barh(imp["parameter"][::-1], imp["importance"][::-1], color="#2f6fde")
            ax.spines[["top", "right"]].set_visible(False)
            out.append(_img(fig))
        out.append(_table(imp))
        top = [p for p in list(opt.importance)[:2]]
        if _HAVE_MPL and len(top) == 2:
            pv = opt.table.pivot_table(index=top[0], columns=top[1], values="objective", aggfunc="mean")
            pv = pv.replace([np.inf, -np.inf], np.nan)
            fig, ax = plt.subplots(figsize=(7.5, 5))
            im = ax.imshow(pv.values, aspect="auto", origin="lower", cmap="RdYlGn")
            ax.set_xticks(range(len(pv.columns)), [str(c) for c in pv.columns], rotation=45)
            ax.set_yticks(range(len(pv.index)), [str(i) for i in pv.index])
            ax.set_xlabel(top[1])
            ax.set_ylabel(top[0])
            fig.colorbar(im, ax=ax, label="mean objective")
            out.append(f"<h2>Heatmap: {html.escape(top[0])} × {html.escape(top[1])}</h2>" + _img(fig))
    cols = list(opt.space.names) + [c for c in ("objective", "net_profit", "profit_factor", "trades",
                                                "equity_dd_rel_pct", "nbr_mean", "nbr_survival_pct", "passed")
                                    if c in opt.table.columns]
    out.append("<h2>Top results</h2>" + _table(opt.table[cols], 40))
    return "".join(out)


# ---------------------------------------------------------------------- sensitivity
def sensitivity_section(sens) -> str:
    s = sens.summary
    out = ["<h2>Robustness / survival summary</h2>",
           _kpis(s, [k for k in s if not isinstance(s[k], (list, dict))])]
    if len(sens.oat_summary):
        out.append("<h2>One-at-a-time sensitivity</h2>" + _table(sens.oat_summary))
        if _HAVE_MPL:
            params = list(sens.oat_summary["param"])
            n = len(params)
            cols = 3
            rows = int(np.ceil(n / cols))
            fig, axs = plt.subplots(rows, cols, figsize=(12, 2.6 * rows), squeeze=False)
            for k, p in enumerate(params):
                ax = axs[k // cols][k % cols]
                g = sens.oat[sens.oat["param"] == p]
                x = [str(v) for v in g["value"]]
                ax.plot(x, g["objective"].replace([np.inf, -np.inf], np.nan), marker="o", color="#2f6fde")
                bv = str(sens.base.get(p))
                if bv in x:
                    ax.axvline(x.index(bv), color="#b42318", lw=1, ls="--")
                ax.set_title(p, fontsize=9)
                ax.tick_params(labelsize=7)
                ax.spines[["top", "right"]].set_visible(False)
            for k in range(n, rows * cols):
                axs[k // cols][k % cols].axis("off")
            fig.tight_layout()
            out.append(_img(fig))
    if len(sens.neighborhood_summary):
        out.append("<h2>Neighbourhood survival (all parameters perturbed together)</h2>" +
                   _table(sens.neighborhood_summary))
    if len(sens.costs):
        cols = [c for c in ("spread_multiplier", "slippage_points", "commission_per_lot", "net_profit",
                            "profit_factor", "equity_dd_rel_pct", "objective", "profitable") if c in sens.costs]
        out.append("<h2>Cost stress</h2>" + _table(sens.costs[cols]))
    if len(sens.periods):
        cols = [c for c in ("period", "net_profit", "profit_factor", "trades", "equity_dd_rel_pct", "profitable")
                if c in sens.periods]
        out.append("<h2>Sub-period stability</h2>" + _table(sens.periods[cols]))
    out.append("<h2>Parameters tested</h2>" + _table(pd.DataFrame(list(sens.base.items()), columns=["input", "value"])))
    return "".join(out)


def walkforward_section(wf) -> str:
    return ("<h2>Walk-forward</h2>" + _kpis(wf.summary, [k for k in wf.summary if not isinstance(wf.summary[k], dict)])
            + _table(wf.windows))


def montecarlo_section(mc: dict) -> str:
    rows = []
    for k in ("shuffle", "bootstrap", "skip"):
        if k in mc:
            rows.append({"scheme": k, **mc[k]})
    head = {k: v for k, v in mc.items() if not isinstance(v, dict)}
    return "<h2>Monte Carlo</h2>" + _kpis(head) + _table(pd.DataFrame(rows))


def full_report(path: str | Path, title: str, sub: str = "", backtest=None, opt=None, sens=None, wf=None,
                mc: Optional[dict] = None) -> Path:
    parts = []
    if opt is not None:
        parts.append(optimization_section(opt))
    if sens is not None:
        parts.append(sensitivity_section(sens))
    if wf is not None:
        parts.append(walkforward_section(wf))
    if mc is not None:
        parts.append(montecarlo_section(mc))
    if backtest is not None:
        parts.append("<h2>Backtest of the selected settings</h2>" + backtest_section(backtest))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(_page(title, sub, "".join(parts)), encoding="utf-8")
    return Path(path)
