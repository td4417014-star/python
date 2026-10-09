"""Read EA inputs straight from the .mq5 source and MT5 .set files.

This removes the per-strategy manual work of re-typing parameters:

* :func:`parse_mq5` returns every ``input``/``sinput`` (name, type, default,
  comment, group, enum options) plus the EA's own ``enum`` declarations.
* :func:`auto_space` derives a sensible optimisation range for each tunable
  input (technical inputs like magic numbers or comments are skipped).
* :func:`read_set` / :func:`write_set` read and write MT5 ``.set`` files,
  including optimisation ranges (``name=value||start||step||stop||Y``), so a
  range set up in the MT5 tester can be reused here and vice versa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .mql5 import constants as C

_NUM_TYPES = {"int", "uint", "long", "ulong", "short", "ushort", "char", "uchar", "double", "float"}
_INT_TYPES = {"int", "uint", "long", "ulong", "short", "ushort", "char", "uchar"}

BUILTIN_ENUMS: Dict[str, Dict[str, int]] = {
    "ENUM_TIMEFRAMES": {k: v for k, v in vars(C).items() if k.startswith("PERIOD_")},
    "ENUM_MA_METHOD": {"MODE_SMA": 0, "MODE_EMA": 1, "MODE_SMMA": 2, "MODE_LWMA": 3},
    "ENUM_APPLIED_PRICE": {"PRICE_CLOSE": 1, "PRICE_OPEN": 2, "PRICE_HIGH": 3, "PRICE_LOW": 4,
                           "PRICE_MEDIAN": 5, "PRICE_TYPICAL": 6, "PRICE_WEIGHTED": 7},
    "ENUM_ORDER_TYPE_FILLING": {"ORDER_FILLING_FOK": 0, "ORDER_FILLING_IOC": 1, "ORDER_FILLING_RETURN": 2},
}

# inputs that never make sense to optimise
TECHNICAL_RE = re.compile(r"(magic|comment|slippage|deviation|show|dashboard|file|retry|delay|color|colour|"
                          r"font|enable$|reset|symbol|debug|log|verbose)", re.I)


@dataclass
class InputParam:
    name: str
    type: str
    default: object
    comment: str = ""
    group: str = ""
    enum: Optional[str] = None
    options: Dict[str, int] = field(default_factory=dict)
    static: bool = False            # sinput: not optimisable in MT5

    @property
    def kind(self) -> str:
        if self.type == "bool":
            return "bool"
        if self.enum:
            return "enum"
        if self.type in _INT_TYPES:
            return "int"
        if self.type in _NUM_TYPES:
            return "float"
        if self.type == "datetime":
            return "int"
        return "str"


@dataclass
class Mq5Info:
    path: str
    inputs: List[InputParam]
    enums: Dict[str, Dict[str, int]]

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.inputs}

    def by_name(self) -> Dict[str, InputParam]:
        return {p.name: p for p in self.inputs}

    def symbols(self) -> List[str]:
        """Assets 'marked' in the EA inputs (string inputs whose name mentions Symbol/Asset)."""
        out = []
        for p in self.inputs:
            if p.kind == "str" and re.search(r"symbol|asset|instrument|pair", p.name, re.I):
                v = str(p.default).strip()
                if v and v not in out:
                    out.append(v)
        return out

    def timeframes(self) -> List[int]:
        """Timeframes referenced by inputs (ENUM_TIMEFRAMES inputs + minute lists like "30,60,240")."""
        out = []
        for p in self.inputs:
            if p.enum == "ENUM_TIMEFRAMES" and p.default:
                out.append(int(p.default))
            elif p.kind == "str" and re.search(r"timeframe|tf", p.name, re.I):
                for part in str(p.default).split(","):
                    part = part.strip()
                    if part.isdigit():
                        out.append(minutes_to_tf(int(part)))
                    elif part.upper() in C.TIMEFRAME_BY_NAME:
                        out.append(C.TIMEFRAME_BY_NAME[part.upper()])
        seen = []
        for t in out:
            if t and t not in seen:
                seen.append(t)
        return seen


def minutes_to_tf(m: int) -> int:
    best, bd = C.PERIOD_M1, 10 ** 9
    for tf, sec in C.TIMEFRAME_SECONDS.items():
        if sec // 60 == m:
            return tf
        d = abs(sec // 60 - m)
        if d < bd:
            best, bd = tf, d
    return best


def _strip_comments(src: str) -> str:
    return re.sub(r"/\*.*?\*/", "", src, flags=re.S)


def _parse_enums(src: str) -> Dict[str, Dict[str, int]]:
    enums = {}
    for m in re.finditer(r"\benum\s+(\w+)\s*\{(.*?)\}\s*;", src, flags=re.S):
        name, body = m.group(1), m.group(2)
        body = re.sub(r"//[^\n]*", "", body)
        val = -1
        opts = {}
        for item in body.split(","):
            item = item.strip()
            if not item:
                continue
            if "=" in item:
                k, v = item.split("=", 1)
                k = k.strip()
                v = v.strip()
                try:
                    val = int(v, 0)
                except ValueError:
                    val = opts.get(v, val + 1)
            else:
                k = item
                val += 1
            opts[k] = val
        enums[name] = opts
    return enums


def _convert(raw: str, ptype: str, enum_opts: Dict[str, int]):
    raw = raw.strip()
    if ptype == "string":
        m = re.match(r'^"(.*)"$', raw, flags=re.S)
        return m.group(1) if m else raw
    if ptype == "bool":
        return raw.lower() in ("true", "1")
    if enum_opts:
        if raw in enum_opts:
            return enum_opts[raw]
        try:
            return int(raw)
        except ValueError:
            return raw
    if ptype in _INT_TYPES or ptype == "datetime":
        try:
            return int(float(raw))
        except ValueError:
            return raw
    if ptype in _NUM_TYPES:
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def parse_mq5(path: str | Path) -> Mq5Info:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            src = raw.decode(enc)
            if "input" in src:
                break
        except UnicodeDecodeError:
            continue
    src = _strip_comments(src)
    enums = dict(BUILTIN_ENUMS)
    enums.update(_parse_enums(src))
    inputs: List[InputParam] = []
    group = ""
    line_re = re.compile(r'^\s*(sinput|input)\s+(?:const\s+)?(\w+)\s+(\w+)\s*=\s*(.+?)\s*;\s*(?://\s*(.*))?$')
    group_re = re.compile(r'^\s*input\s+group\s+"(.*)"')
    for line in src.splitlines():
        g = group_re.match(line)
        if g:
            group = g.group(1).strip()
            continue
        m = line_re.match(line)
        if not m:
            continue
        kw, ptype, name, val, comment = m.groups()
        opts = enums.get(ptype, {})
        inputs.append(InputParam(name=name, type=ptype, default=_convert(val, ptype, opts),
                                 comment=(comment or "").strip(), group=group,
                                 enum=ptype if ptype in enums else None, options=dict(opts),
                                 static=(kw == "sinput")))
    return Mq5Info(str(path), inputs, enums)


# ---------------------------------------------------------------------- ranges
def auto_space(info: Mq5Info, include: Optional[List[str]] = None, exclude: Optional[List[str]] = None,
               spread: float = 0.5, points: int = 5) -> Dict[str, dict]:
    """Optimisation space from the EA's own defaults.

    numeric: default*(1-spread) .. default*(1+spread) in ``points`` steps (ints rounded, >=1)
    bool: [False, True]; enum: all options. Technical inputs are skipped unless listed in ``include``.
    """
    space = {}
    for p in info.inputs:
        if include and p.name not in include:
            continue
        if exclude and p.name in exclude:
            continue
        if p.static or (not include and TECHNICAL_RE.search(p.name)):
            continue
        k = p.kind
        if k == "bool":
            space[p.name] = {"type": "bool", "values": [False, True]}
        elif k == "enum":
            if p.enum == "ENUM_TIMEFRAMES":
                continue
            space[p.name] = {"type": "enum", "values": sorted(set(p.options.values()))}
        elif k in ("int", "float"):
            d = float(p.default)
            if d == 0:
                lo, hi = 0.0, 1.0
            else:
                lo, hi = sorted((d * (1 - spread), d * (1 + spread)))
            if k == "int":
                lo, hi = int(round(lo)), int(round(hi))
                if d > 0:
                    lo = max(1, lo)
                step = max(1, int(round((hi - lo) / max(points - 1, 1))))
                space[p.name] = {"type": "int", "low": lo, "high": hi, "step": step}
            else:
                step = (hi - lo) / max(points - 1, 1)
                space[p.name] = {"type": "float", "low": round(lo, 10), "high": round(hi, 10),
                                 "step": round(step, 10)}
    return space


# ---------------------------------------------------------------------- .set files
def read_set(path: str | Path) -> tuple[dict, Dict[str, dict]]:
    """Return (values, optimisation_space) from an MT5 .set file."""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        txt = raw.decode("utf-16")
    else:
        try:
            txt = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            txt = raw.decode("cp1252")
    values, space = {}, {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        parts = v.split("||")
        values[k.strip()] = _auto_val(parts[0])
        if len(parts) >= 5 and parts[4].strip().upper() == "Y":
            start, step, stop = (_auto_val(x) for x in parts[1:4])
            is_int = all(isinstance(x, int) for x in (start, step, stop))
            space[k.strip()] = {"type": "int" if is_int else "float", "low": start, "high": stop, "step": step}
    return values, space


def _auto_val(s: str):
    s = s.strip()
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        if re.fullmatch(r"[-+]?\d+", s):
            return int(s)
        return float(s)
    except ValueError:
        return s


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def set_lines(values: dict, space: Optional[Dict[str, dict]] = None, info: Optional[Mq5Info] = None) -> List[str]:
    space = space or {}
    names = [p.name for p in info.inputs] if info else list(values)
    for k in values:
        if k not in names:
            names.append(k)
    lines = []
    for name in names:
        if name not in values:
            continue
        v = values[name]
        if name in space:
            sp = space[name]
            if sp.get("type") in ("bool",):
                lines.append(f"{name}={_fmt(v)}||false||0||true||Y")
            elif "values" in sp:
                vals = sp["values"]
                lines.append(f"{name}={_fmt(v)}||{_fmt(min(vals))}||1||{_fmt(max(vals))}||Y")
            else:
                lines.append(f"{name}={_fmt(v)}||{_fmt(sp['low'])}||{_fmt(sp['step'])}||{_fmt(sp['high'])}||Y")
        elif isinstance(v, str):
            lines.append(f"{name}={v}")
        else:
            lines.append(f"{name}={_fmt(v)}||{_fmt(v)}||{_fmt(1 if isinstance(v, int) else 0.0)}||{_fmt(v)}||N")
    return lines


def write_set(path: str | Path, values: dict, space: Optional[Dict[str, dict]] = None,
              info: Optional[Mq5Info] = None, encoding: str = "utf-16"):
    txt = "\r\n".join(set_lines(values, space, info)) + "\r\n"
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(txt.encode(encoding))
