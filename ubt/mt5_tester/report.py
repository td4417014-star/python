"""Parse MT5 Strategy Tester reports (single test .htm, optimisation .xml)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List

import pandas as pd


def _read_text(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: List[List[str]] = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _num(s: str):
    s = s.strip().replace("\xa0", " ")
    m = re.match(r"^\s*(-?[\d\s]+(?:[.,]\d+)?)", s)
    if not m:
        return s
    try:
        return float(m.group(1).replace(" ", "").replace(",", "."))
    except ValueError:
        return s


STAT_MAP = {
    "Initial Deposit": "initial_deposit", "Total Net Profit": "net_profit", "Gross Profit": "gross_profit",
    "Gross Loss": "gross_loss", "Profit Factor": "profit_factor", "Expected Payoff": "expected_payoff",
    "Recovery Factor": "recovery_factor", "Sharpe Ratio": "sharpe_ratio", "Total Trades": "trades",
    "Total Deals": "deals", "Balance Drawdown Maximal": "balance_dd_max", "Equity Drawdown Maximal": "equity_dd_max",
    "Balance Drawdown Relative": "balance_dd_rel_pct", "Equity Drawdown Relative": "equity_dd_rel_pct",
    "Balance Drawdown Absolute": "balance_dd_abs", "Equity Drawdown Absolute": "equity_dd_abs",
    "OnTester result": "ontester", "History Quality": "history_quality", "Bars": "bars", "Ticks": "ticks",
}


def parse_html_report(path: str | Path) -> Dict[str, object]:
    """Returns {'metrics': {...}, 'deals': DataFrame, 'orders': DataFrame}."""
    p = _Rows()
    p.feed(_read_text(path))
    metrics: Dict[str, object] = {}
    for row in p.rows:
        for i in range(0, len(row) - 1):
            label = row[i].rstrip(":").strip()
            if label in STAT_MAP and i + 1 < len(row):
                val = row[i + 1]
                key = STAT_MAP[label]
                if key.endswith("_rel_pct"):           # "12.34% (1 234.00)"
                    metrics[key] = _num(val.split("%")[0])
                    m = re.search(r"\(([-\d\s.,]+)\)", val)
                    if m:
                        metrics[key.replace("_rel_pct", "_rel_money")] = _num(m.group(1))
                elif key.endswith("_dd_max"):          # "1 234.00 (12.34%)"
                    metrics[key] = _num(val)
                    m = re.search(r"\(([-\d\s.,]+)%\)", val)
                    if m:
                        metrics[key + "_pct"] = _num(m.group(1))
                else:
                    metrics[key] = _num(val)
    deals = _section_table(p.rows, "Deals")
    orders = _section_table(p.rows, "Orders")
    return {"metrics": metrics, "deals": deals, "orders": orders}


def _section_table(rows: List[List[str]], title: str) -> pd.DataFrame:
    start = None
    for i, r in enumerate(rows):
        if len(r) == 1 and r[0].strip() == title:
            start = i
            break
    if start is None:
        return pd.DataFrame()
    header = rows[start + 1]
    out = []
    for r in rows[start + 2:]:
        if len(r) == 1 and r[0].strip():          # next section title
            break
        if len(r) != len(header):
            continue
        out.append(r)
    df = pd.DataFrame(out, columns=[h.strip().lower().replace(" / ", "_").replace(" ", "_") for h in header])
    for c in df.columns:
        if c not in ("time", "symbol", "type", "direction", "comment", "state"):
            conv = pd.to_numeric(df[c].str.replace(" ", "", regex=False), errors="coerce")
            if conv.notna().mean() > 0.8:
                df[c] = conv
    return df


def parse_optimization_xml(path: str | Path) -> pd.DataFrame:
    """MT5 optimisation report (Excel 2003 XML) -> DataFrame (one row per pass)."""
    txt = re.sub(r"^\s*<\?xml[^>]*\?>", "", _read_text(path))
    root = ET.fromstring(txt)
    ns = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}
    rows = []
    for row in root.iter("{urn:schemas-microsoft-com:office:spreadsheet}Row"):
        cells = [c.findtext("ss:Data", default="", namespaces=ns) for c in
                 row.findall("ss:Cell", ns)]
        rows.append(cells)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows[1:], columns=rows[0])
    for c in df.columns:
        conv = pd.to_numeric(df[c], errors="coerce")
        if conv.notna().mean() > 0.8:
            df[c] = conv
    return df
