"""MQL5 -> Python DRAFT transpiler for new strategies (``python -m ubt port``).

Turns an Expert Advisor into a :class:`ubt.strategy.Strategy` subclass that
calls the emulated MQL5 API, so a new strategy starts from a near-complete
port instead of a blank file. It handles the procedural MQL5 that EAs are
usually written in:

* enums / #define / const -> module constants; structs -> classes;
  globals -> ``self.`` attributes (inputs come from the .mq5 automatically);
* if / else if / else, while, do-while, for (-> ``range`` when possible),
  switch/case, ternaries, casts, ``&&``/``||``/``!``, ``++``/``--``;
* int/int division -> ``//`` when both sides are int-typed;
* scalar reference (``&``) parameters -> returned as a tuple and assigned
  at the call sites (statement-level calls);
* in-place string functions (StringToUpper, StringTrim*, StringReplace).

Every generated function is syntax-checked; anything it cannot convert
becomes a stub that raises NotImplementedError with the original MQL5 code
beside it and a ``TODO`` marker. Always review the draft (and compare it with
the MT5 tester using ``python -m ubt mt5test --parity-with``) before trusting it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .mq5 import parse_mq5, _parse_enums

INT_TYPES = {"int", "uint", "long", "ulong", "short", "ushort", "char", "uchar", "datetime", "color", "bool_int"}
FLOAT_TYPES = {"double", "float"}
BASE_TYPES = INT_TYPES | FLOAT_TYPES | {"bool", "string", "void"}
API_CLASSES = {"CTrade", "CPositionInfo", "COrderInfo", "CSymbolInfo", "MqlTick", "MqlRates",
               "MqlTradeRequest", "MqlTradeResult"}
CONTROL = ("if", "while", "for", "switch")


def _default_for(t: str, structs: set, is_array: bool, size: Optional[str] = None) -> str:
    if is_array:
        if size:
            return f"[{_default_for(t, structs, False)} for _ in range({size})]"
        return "[]"
    if t in FLOAT_TYPES:
        return "0.0"
    if t == "bool":
        return "False"
    if t == "string":
        return '""'
    if t in structs or t in API_CLASSES:
        return f"{t}()"
    return "0"


# ---------------------------------------------------------------------- low level text helpers
def _strip_block_comments(src: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)


def _match(s: str, i: int, open_c: str, close_c: str) -> int:
    """Index of the bracket closing the one at s[i] (string-literal aware)."""
    depth = 0
    j = i
    in_str = None
    while j < len(s):
        c = s[j]
        if in_str:
            if c == "\\":
                j += 2
                continue
            if c == in_str:
                in_str = None
        elif c == "/" and s.startswith("//", j):
            k = s.find("\n", j)
            j = len(s) if k < 0 else k
            continue
        elif c in "\"'":
            in_str = c
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(s) - 1


def _split_top(s: str, sep: str = ",") -> List[str]:
    parts, depth, cur, in_str = [], 0, [], None
    i = 0
    while i < len(s):
        c = s[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < len(s):
                cur.append(s[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'":
            in_str = c
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts]


# ---------------------------------------------------------------------- units (statement tokens)
def _units(body: str) -> List[Tuple[str, str]]:
    out, cur = [], []
    i, depth = 0, 0
    in_str = None

    def flush():
        t = "".join(cur).strip()
        if t:
            out.append(("stmt", t))
        cur.clear()

    while i < len(body):
        c = body[i]
        if in_str:
            cur.append(c)
            if c == "\\" and i + 1 < len(body):
                cur.append(body[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "\"'":
            in_str = c
            cur.append(c)
        elif body.startswith("//", i):
            j = body.find("\n", i)
            j = len(body) if j < 0 else j
            if not "".join(cur).strip():
                out.append(("comment", body[i + 2:j].strip()))
            i = j
            continue
        elif c == "(":
            depth += 1
            cur.append(c)
        elif c == ")":
            depth -= 1
            cur.append(c)
        elif c == "{" and depth == 0:
            prev = "".join(cur).rstrip()
            if prev.endswith("="):        # aggregate initialiser  x = {..}
                j = _match(body, i, "{", "}")
                cur.append(body[i:j + 1])
                i = j + 1
                continue
            flush()
            out.append(("open", ""))
        elif c == "}" and depth == 0:
            flush()
            out.append(("close", ""))
        elif c == ";" and depth == 0:
            flush()
        elif c == ":" and depth == 0 and re.match(r"^\s*(case\b.*|default)\s*$", "".join(cur), flags=re.S):
            cur.append(c)
            flush()
        else:
            cur.append(c)
        i += 1
    flush()
    return out


class Transpiler:
    def __init__(self, src: str, mq5_path: str):
        self.src = _strip_block_comments(src)
        self.info = parse_mq5(mq5_path)
        self.inputs = {p.name: p.type for p in self.info.inputs}
        self.enums: Dict[str, Dict[str, int]] = {}
        self.defines: List[Tuple[str, str]] = []
        self.consts: List[Tuple[str, str]] = []
        self.structs: Dict[str, List[Tuple[str, str, bool, Optional[str]]]] = {}
        self.globals: Dict[str, Tuple[str, bool, Optional[str], Optional[str]]] = {}   # name -> (type, arr, size, init)
        self.funcs: List[dict] = []
        self.todo: List[str] = []
        self.statics: Dict[str, str] = {}

    # ------------------------------------------------------------------ top level
    def scan(self):
        s = self.src
        i, n = 0, len(s)
        while i < n:
            while i < n and s[i].isspace():
                i += 1
            if i >= n:
                break
            if s.startswith("//", i):
                i = s.find("\n", i)
                i = n if i < 0 else i
                continue
            if s[i] == "#":
                j = s.find("\n", i)
                j = n if j < 0 else j
                line = s[i:j].strip()
                m = re.match(r"#define\s+(\w+)\s+(.+)", line)
                if m:
                    self.defines.append((m.group(1), m.group(2).split("//")[0].strip()))
                i = j
                continue
            # read up to ';' or a '{...}' block at paren depth 0
            j, depth = i, 0
            while j < n:
                c = s[j]
                if c == '"':
                    j = s.find('"', j + 1)
                    while j > 0 and s[j - 1] == "\\":
                        j = s.find('"', j + 1)
                elif s.startswith("//", j):
                    j = s.find("\n", j)
                    j = n if j < 0 else j
                    continue
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                elif c == ";" and depth == 0:
                    self._decl(s[i:j].strip())
                    break
                elif c == "{" and depth == 0:
                    k = _match(s, j, "{", "}")
                    header = s[i:j].strip()
                    block = s[j + 1:k]
                    k2 = k + 1
                    while k2 < n and s[k2].isspace():
                        k2 += 1
                    if k2 < n and s[k2] == ";":
                        k = k2
                    self._block(header, block)
                    j = k
                    break
                j += 1
            i = j + 1

    def _decl(self, text: str):
        text = re.sub(r"//[^\n]*", "", text).strip()
        if not text or re.match(r"^(input|sinput)\b", text):
            return
        m = re.match(r"^(const\s+)?(static\s+)?([\w]+)\s+(.+)$", text, flags=re.S)
        if not m:
            self.todo.append(f"global declaration not understood: {text[:80]}")
            return
        is_const, _, typ, rest = m.groups()
        for part in _split_top(rest):
            mm = re.match(r"^(\w+)\s*(\[\s*(\w*)\s*\])?\s*(?:=\s*(.+))?$", part, flags=re.S)
            if not mm:
                continue
            name, arr, size, init = mm.group(1), bool(mm.group(2)), mm.group(3) or None, mm.group(4)
            if is_const and init is not None:
                self.consts.append((name, init.strip()))
            else:
                self.globals[name] = (typ, arr, size, init.strip() if init else None)

    def _block(self, header: str, block: str):
        header = re.sub(r"//[^\n]*", "", header).strip()
        if header.startswith("enum"):
            self.enums.update(_parse_enums(f"{header}{{{block}}};"))
            return
        m = re.match(r"^(struct|class)\s+(\w+)", header)
        if m:
            fields = []
            for u in _units(block):
                if u[0] != "stmt":
                    continue
                d = re.match(r"^(?:const\s+)?([\w]+)\s+(.+)$", u[1], flags=re.S)
                if not d or "(" in u[1]:
                    if "(" in u[1]:
                        self.todo.append(f"struct {m.group(2)}: methods are not converted ({u[1][:60]})")
                    continue
                for part in _split_top(d.group(2)):
                    mm = re.match(r"^(\w+)\s*(\[\s*(\w*)\s*\])?", part)
                    if mm:
                        fields.append((mm.group(1), d.group(1), bool(mm.group(2)), mm.group(3) or None))
            self.structs[m.group(2)] = fields
            return
        m = re.match(r"^(?:static\s+|virtual\s+)?([\w]+)\s+(\w+)\s*\((.*)\)\s*(const)?$", header, flags=re.S)
        if m:
            self.funcs.append({"ret": m.group(1), "name": m.group(2), "params": m.group(3), "body": block})
            return
        self.todo.append(f"top-level block not understood: {header[:80]}")

    # ------------------------------------------------------------------ type knowledge
    def _known_type(self, t: str) -> bool:
        return (t in BASE_TYPES or t.startswith("ENUM_") or t in self.enums or t in self.structs
                or t in API_CLASSES)

    def _int_names(self, local_types: Dict[str, str]) -> set:
        names = {n for n, (t, arr, _, _) in self.globals.items() if (t in INT_TYPES or t.startswith("ENUM_")
                                                                     or t in self.enums) and not arr}
        names |= {n for n, t in self.inputs.items() if t in INT_TYPES or t.startswith("ENUM_") or t in self.enums}
        names |= {n for n, t in local_types.items() if t in INT_TYPES or t.startswith("ENUM_") or t in self.enums}
        names |= {n for n, v in self.consts if re.fullmatch(r"-?\d+", v)}
        return names

    # ------------------------------------------------------------------ expressions
    def cx(self, e: str, ctx: dict) -> str:
        e = e.strip()
        strings: List[str] = []

        def keep(m):
            strings.append(m.group(0))
            return f"\x00{len(strings) - 1}\x00"

        e = re.sub(r'"(?:\\.|[^"\\])*"', keep, e)
        e = re.sub(r"'(?:\\.|[^'\\])'", lambda m: str(ord(m.group(0)[1:-1].encode().decode("unicode_escape"))), e)
        e = e.replace("::", "")
        e = re.sub(r"\b_Symbol\b", "Symbol()", e)
        e = re.sub(r"\b_Period\b", "Period()", e)
        e = re.sub(r"\b_Point\b", "Point()", e)
        e = re.sub(r"\b_Digits\b", "Digits()", e)
        e = re.sub(r"\b_LastError\b", "GetLastError()", e)
        e = re.sub(r"(\d+\.\d*|\.\d+)[fF]\b", r"\1", e)
        e = self._casts(e)
        e = self._ternary(e)
        e = e.replace("&&", " and ").replace("||", " or ")
        e = re.sub(r"!(?!=)", " not ", e)
        e = re.sub(r"\btrue\b", "True", e)
        e = re.sub(r"\bfalse\b", "False", e)
        e = re.sub(r"\bNULL\b", "None", e)
        e = self._int_div(e, ctx)
        e = self._series_copies(e, ctx)
        e = self._self_names(e, ctx)
        e = re.sub(r"\s+", " ", e).strip()
        e = re.sub(r"\(\s+", "(", e)
        e = re.sub(r"\s+\)", ")", e)
        e = re.sub(r"\x00(\d+)\x00", lambda m: strings[int(m.group(1))], e)
        return e

    def _operand_end(self, s: str, i: int) -> int:
        while i < len(s) and s[i] == " ":
            i += 1
        if i < len(s) and s[i] == "(":
            return _match(s, i, "(", ")") + 1
        if i < len(s) and s[i] in "-+":
            i += 1
        j = i
        while j < len(s):
            if re.match(r"[\w.\x00]", s[j]):
                j += 1
            elif s[j] == "(":
                j = _match(s, j, "(", ")") + 1
            elif s[j] == "[":
                j = _match(s, j, "[", "]") + 1
            else:
                break
        return j

    def _casts(self, e: str) -> str:
        alts = ["int", "uint", "long", "ulong", "short", "ushort", "char", "uchar", "datetime", "color", "double",
                "float", "string", "bool", r"ENUM_\w+"] + [re.escape(n) for n in self.enums if n]
        pat = re.compile(r"\(\s*(" + "|".join(alts) + r")\s*\)")
        while True:
            m = pat.search(e)
            if not m:
                return e
            t = m.group(1)
            end = self._operand_end(e, m.end())
            operand = e[m.end():end].strip()
            if t in FLOAT_TYPES:
                rep = f"float({operand})"
            elif t == "string":
                rep = f"str({operand})"
            elif t == "bool":
                rep = f"bool({operand})"
            elif t in INT_TYPES:
                rep = f"int({operand})"
            else:
                rep = f"({operand})"     # enum cast: value unchanged
            e = e[:m.start()] + rep + e[end:]

    def _ternary(self, e: str) -> str:
        # convert innermost groups first
        out, i = [], 0
        while i < len(e):
            c = e[i]
            if c in "([":
                close = ")" if c == "(" else "]"
                j = _match(e, i, c, close)
                inner = ", ".join(self._ternary(p) for p in _split_top(e[i + 1:j]))
                out.append(c + inner + close)
                i = j + 1
            else:
                out.append(c)
                i += 1
        e = "".join(out)
        depth, q = 0, -1
        for k, c in enumerate(e):
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            elif c == "?" and depth == 0:
                q = k
                break
        if q < 0:
            return e
        depth, nest, col = 0, 0, -1
        for k in range(q + 1, len(e)):
            c = e[k]
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            elif depth == 0 and c == "?":
                nest += 1
            elif depth == 0 and c == ":":
                if nest == 0:
                    col = k
                    break
                nest -= 1
        if col < 0:
            return e
        cond, a, b = e[:q], e[q + 1:col].strip(), e[col + 1:].strip()
        # only an assignment binds looser than ?: - split the condition after the last top-level '='
        depth, cut = 0, 0
        for k, c in enumerate(cond):
            if c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            elif (c == "=" and depth == 0 and cond[k + 1:k + 2] != "=" and
                  (k == 0 or cond[k - 1] not in "=!<>")):
                cut = k + 1
        prefix, cond = cond[:cut], cond[cut:].strip()
        return f"{prefix} ({self._ternary(a)} if {cond} else {self._ternary(b)})".lstrip()

    def _int_div(self, e: str, ctx: dict) -> str:
        ints = ctx["ints"]

        def is_int(tok: str) -> bool:
            tok = tok.strip()
            while tok.startswith("(") and tok.endswith(")") and _match(tok, 0, "(", ")") == len(tok) - 1:
                tok = tok[1:-1].strip()
            if re.fullmatch(r"\d+", tok):
                return True
            if re.fullmatch(r"int\(.*\)", tok):
                return True
            ids = re.findall(r"[A-Za-z_][\w.]*", tok)
            if not ids or re.search(r"\d\.\d|\(", tok.replace("int(", "")):
                return False
            return all(i.split(".")[-1] in ints and "." not in i for i in ids)

        out = e
        pos = 0
        while True:
            k = out.find("/", pos)
            if k < 0:
                return out
            if out[k + 1:k + 2] in ("/", "="):
                pos = k + 2
                continue
            # left operand
            j = k - 1
            while j >= 0 and out[j] == " ":
                j -= 1
            if j >= 0 and out[j] == ")":
                depth, a = 0, j
                while a >= 0:
                    if out[a] == ")":
                        depth += 1
                    elif out[a] == "(":
                        depth -= 1
                        if depth == 0:
                            break
                    a -= 1
                start = a
                while start > 0 and re.match(r"[\w.]", out[start - 1]):
                    start -= 1
            else:
                start = j
                while start > 0 and re.match(r"[\w.]", out[start - 1]):
                    start -= 1
            left = out[start:j + 1]
            rend = self._operand_end(out, k + 1)
            right = out[k + 1:rend]
            if is_int(left) and is_int(right):
                out = out[:k] + "//" + out[k + 1:]
                pos = k + 2
            else:
                pos = k + 1

    def _series_copies(self, e: str, ctx: dict) -> str:
        series = ctx.get("series") or set()
        if not series or "Copy" not in e:
            return e
        out, pos = [], 0
        for m in re.finditer(r"\b(Copy(?:Buffer|Rates|Time|Open|High|Low|Close|TickVolume|RealVolume|Spread))\s*\(", e):
            if m.start() < pos:
                continue
            k = _match(e, m.end() - 1, "(", ")")
            args = _split_top(e[m.end():k])
            if args and args[-1].strip() in series:
                out.append(e[pos:k] + ", as_series=True)")
                pos = k + 1
        out.append(e[pos:])
        return "".join(out)

    def _self_names(self, e: str, ctx: dict) -> str:
        names = ctx["self_names"]
        funcs = ctx["funcs"]
        locals_ = ctx["locals"]

        def rep(m):
            name = m.group(2)
            pre = m.group(1)
            after = e[m.end():m.end() + 2].lstrip()
            if pre.endswith("."):
                return m.group(0)
            if name in locals_:
                return m.group(0)
            if name in funcs and after.startswith("("):
                return f"{pre}self.{name}"
            if name in names:
                return f"{pre}self.{name}"
            return m.group(0)

        return re.sub(r"(^|[^\w.\x00])([A-Za-z_]\w*)", rep, e)

    # ------------------------------------------------------------------ statements
    def stmt(self, s: str, ctx: dict) -> List[str]:
        s = s.strip()
        if not s:
            return []
        m = re.match(r"^return\b\s*(.*)$", s, flags=re.S)
        if m:
            val = self.cx(m.group(1), ctx) if m.group(1).strip() else ""
            outs = ctx["outs"]
            if outs:
                parts = ([val] if val else []) + [o for o in outs]
                parts = [self._self_names(p, ctx) if p in outs else p for p in parts]
                return ["return " + ", ".join(parts)]
            return ["return " + val if val else "return"]
        if s in ("break", "continue"):
            if s == "continue" and ctx["loops"] and ctx["loops"][-1][0] == "for":
                return [*ctx["loops"][-1][1], "continue"]
            if s == "break" and ctx["loops"] and ctx["loops"][-1][0] == "switch":
                return []
            return [s]
        m = re.match(r"^(\+\+|--)\s*([\w.\[\]]+)$", s) or re.match(r"^([\w.\[\]]+)\s*(\+\+|--)$", s)
        if m:
            g = m.groups()
            var, op = (g[1], g[0]) if g[0] in ("++", "--") else (g[0], g[1])
            return [f"{self.cx(var, ctx)} {'+=' if op == '++' else '-='} 1"]
        # x = y++  (post-increment inside an assignment)
        m = re.match(r"^((?:[\w]+\s+)?[\w.\[\]]+)\s*=\s*([\w.\[\]]+)\s*(\+\+|--)$", s)
        if m:
            first = self.stmt(f"{m.group(1)} = {m.group(2)}", ctx)
            return first + [f"{self.cx(m.group(2), ctx)} {'+=' if m.group(3) == '++' else '-='} 1"]
        for fn, py in (("StringToUpper", "{0} = {0}.upper()"), ("StringToLower", "{0} = {0}.lower()"),
                       ("StringTrimLeft", "{0} = {0}.lstrip()"), ("StringTrimRight", "{0} = {0}.rstrip()")):
            m = re.match(rf"^{fn}\s*\((.+)\)$", s)
            if m:
                return [py.format(self.cx(m.group(1), ctx))]
        m = re.match(r"^ArraySetAsSeries\s*\(\s*([\w.\[\]]+)\s*,\s*(true|false)\s*\)$", s)
        if m:
            (ctx["series"].add if m.group(2) == "true" else ctx["series"].discard)(m.group(1))
            return [f"# ArraySetAsSeries({m.group(1)}, {m.group(2)}) -> as_series= on Copy* calls"]
        m = re.match(r"^ArrayResize\s*\((.+)\)$", s, flags=re.S)
        if m:
            a = _split_top(m.group(1))
            last = re.sub(r"\[.*?\]", "", a[0]).split(".")[-1].strip()
            et = self._elem_type(last, ctx)
            if et and len(a) >= 2:
                fill = et if (et in self.structs or et in API_CLASSES) else _default_for(et, set(self.structs), False)
                return [f"ArrayResize({self.cx(a[0], ctx)}, {self.cx(a[1], ctx)}, {fill})"]
        m = re.match(r"^StringReplace\s*\((.+)\)$", s)
        if m:
            a = _split_top(m.group(1))
            if len(a) == 3:
                v = self.cx(a[0], ctx)
                return [f"{v} = {v}.replace({self.cx(a[1], ctx)}, {self.cx(a[2], ctx)})"]
        # declarations
        m = re.match(r"^(?:const\s+)?(static\s+)?([A-Za-z_]\w*)\s+([A-Za-z_].*)$", s, flags=re.S)
        if m and self._known_type(m.group(2)) and not re.match(r"^(return|else|new|delete)\b", s):
            is_static, typ, rest = m.group(1), m.group(2), m.group(3)
            lines = []
            for part in _split_top(rest):
                mm = re.match(r"^&?\s*(\w+)\s*(\[\s*([\w.]*)\s*\])?\s*(?:=\s*(.+))?$", part, flags=re.S)
                if not mm:
                    self.todo.append(f"{ctx['fname']}: declaration not understood: {part[:60]}")
                    lines.append(f"# TODO declaration: {part}")
                    continue
                name, arr, size, init = mm.group(1), bool(mm.group(2)), mm.group(3) or None, mm.group(4)
                ctx["types"][name] = typ
                if is_static:
                    attr = f"_st_{ctx['fname']}_{name}"
                    self.statics[attr] = (self.cx(init, ctx) if init and init.strip() not in ("{}",) else
                                          _default_for(typ, set(self.structs), arr,
                                                       self.cx(size, ctx) if size else None))
                    ctx["static_map"][name] = attr
                    continue
                ctx["locals"].add(name)
                if init is None or init.strip() in ("{}", "{0}"):
                    val = _default_for(typ, set(self.structs), arr, self.cx(size, ctx) if size else None)
                elif init.strip().startswith("{"):
                    val = self._array_init(init, ctx)
                else:
                    oc = re.match(r"^(\w+)\s*\((.*)\)$", init.strip(), flags=re.S)
                    if oc and oc.group(1) in ctx["outfuncs"] and _match(init.strip(), init.strip().index("("),
                                                                         "(", ")") == len(init.strip()) - 1:
                        lines.extend(self.stmt(f"{name} = {init.strip()}", ctx))
                        continue
                    val = self.cx(init, ctx)
                lines.append(f"{name} = {val}")
            return lines
        # out-parameter calls at statement level
        m = re.match(r"^(?:([\w.\[\]]+)\s*=\s*)?(\w+)\s*\((.*)\)$", s, flags=re.S)
        if m and m.group(2) in ctx["outfuncs"]:
            target, fname, args = m.group(1), m.group(2), _split_top(m.group(3)) if m.group(3).strip() else []
            pos = ctx["outfuncs"][fname]
            outs = [self.cx(args[p], ctx) for p in pos if p < len(args)]
            lhs = ([self.cx(target, ctx)] if target else []) + outs
            return [f"{', '.join(lhs)} = self.{fname}({', '.join(self.cx(a, ctx) for a in args)})"]
        return [self.cx(s, ctx)]

    def _array_init(self, init: str, ctx: dict) -> str:
        inner = init.strip()[1:-1]
        return "[" + ", ".join(self.cx(x, ctx) for x in _split_top(inner) if x) + "]"

    def _elem_type(self, name: str, ctx: dict) -> Optional[str]:
        if name in ctx["types"]:
            return ctx["types"][name]
        if name in self.globals:
            return self.globals[name][0]
        for fields in self.structs.values():
            for fname, ftype, arr, _ in fields:
                if fname == name:
                    return ftype
        return None

    # ------------------------------------------------------------------ functions
    def function(self, f: dict, all_funcs: set, outfuncs: Dict[str, List[int]]) -> str:
        params_py, outs, types = [], [], {}
        for k, p in enumerate(_split_top(f["params"]) if f["params"].strip() else []):
            p = re.sub(r"\bconst\b", "", p).strip()
            mm = re.match(r"^([\w]+)\s*(&)?\s*(\w+)\s*(\[\s*\])?\s*(?:=\s*(.+))?$", p)
            if not mm:
                self.todo.append(f"{f['name']}: parameter not understood: {p}")
                params_py.append(f"p{k}")
                continue
            typ, ref, name, arr, default = mm.groups()
            types[name] = typ
            if ref and not arr and typ not in self.structs and typ not in API_CLASSES:
                outs.append(name)
            params_py.append(name if default is None else f"{name}={default.strip()}")
        ctx = {"fname": f["name"], "self_names": set(self.globals) | set(self.inputs) | set(self.statics),
               "funcs": all_funcs, "locals": set(types), "types": types, "outs": outs, "outfuncs": outfuncs,
               "loops": [], "static_map": {}, "ints": set(), "series": set()}
        ctx["ints"] = self._int_names(types)
        lines: List[str] = []
        units = _units(f["body"])
        self._emit(units, 0, len(units), 2, lines, ctx)
        if outs and f["ret"] == "void":
            lines.append("        return " + ", ".join(outs))
        if not any(l.strip() and not l.strip().startswith("#") for l in lines):
            lines.append("        pass")
        for local, attr in ctx["static_map"].items():
            lines = [re.sub(rf"(?<![\w.]){local}\b", f"self.{attr}", l) for l in lines]
        # out-parameter functions used inside expressions cannot be rewritten safely: flag them
        flagged = []
        for l in lines:
            for fn in outfuncs:
                if f"self.{fn}(" in l and not re.match(rf"^\s*[\w.\[\], ]+ = self\.{fn}\(", l):
                    flagged.append(re.match(r"^\s*", l).group(0) +
                                   f"# TODO {fn}() returns its out-parameters as a tuple - unpack them here")
                    self.todo.append(f"{f['name']}: call of {fn}() inside an expression needs manual unpacking")
                    break
            flagged.append(l)
        lines = flagged
        head = f"    def {f['name']}(self{', ' if params_py else ''}{', '.join(params_py)}):"
        doc = []
        if outs:
            doc.append(f'        """MQL out-parameters ({", ".join(outs)}) are returned'
                       f'{" after the return value" if f["ret"] != "void" else ""}."""')
        code = "\n".join([head] + doc + lines)
        try:
            ast.parse("class _X:\n" + code)
            return code
        except SyntaxError as e:
            self.todo.append(f"{f['name']}: could not convert automatically ({e.msg} line {e.lineno})")
            orig = "\n".join("        # " + l for l in (f["ret"] + " " + f["name"] + "(" + f["params"] + ")\n{" +
                                                          f["body"] + "}").splitlines())
            return (f"{head}\n        # TODO port by hand (draft conversion failed: {e.msg}). Original MQL5:\n"
                    f"{orig}\n        raise NotImplementedError('{f['name']}')")

    def _emit(self, units, i, end, ind, lines, ctx):
        pad = "    " * ind
        while i < end:
            kind, text = units[i]
            if kind == "comment":
                lines.append(f"{pad}# {text}")
                i += 1
                continue
            if kind == "open":            # bare block
                j = self._close_of(units, i)
                self._emit(units, i + 1, j, ind, lines, ctx)
                i = j + 1
                continue
            if kind == "close":
                i += 1
                continue
            header, rest = self._split_header(text)
            if header is None:
                for l in self.stmt(text, ctx):
                    lines.append(pad + l)
                i += 1
                continue
            has_block = (not rest) and i + 1 < end and units[i + 1][0] == "open"
            if rest and i + 1 < end and units[i + 1][0] == "open" and self._chain_wants_block(rest):
                # e.g.  for(...) if(cond) { ... }  - the inner header owns the brace block
                j = self._close_of(units, i + 1)
                sub = [("stmt", rest)] + units[i + 1:j + 1]
                self._emit_control(header, "", (0, len(sub)), sub, ind, lines, ctx, len(sub))
                i = j + 1
                continue
            if has_block:
                j = self._close_of(units, i + 1)
                body = (i + 2, j)
                nxt = j + 1
            else:
                body = None
                nxt = i + 1
            nxt = self._emit_control(header, rest, body, units, ind, lines, ctx, nxt)
            i = nxt

    def _chain_wants_block(self, text: str) -> bool:
        header, rest = self._split_header(text)
        if header is None or header[0] == "case":
            return False
        return True if not rest else self._chain_wants_block(rest)

    def _close_of(self, units, i):
        depth = 0
        for k in range(i, len(units)):
            if units[k][0] == "open":
                depth += 1
            elif units[k][0] == "close":
                depth -= 1
                if depth == 0:
                    return k
        return len(units) - 1

    def _split_header(self, text):
        t = text.strip()
        m = re.match(r"^else\s+if\s*\(", t)
        if m:
            k = _match(t, m.end() - 1, "(", ")")
            return ("elif", t[m.end() - 1:k + 1]), t[k + 1:].strip()
        if re.match(r"^else\b", t):
            return ("else", ""), t[4:].strip()
        if t == "do" or re.match(r"^do\b\s*$", t):
            return ("do", ""), ""
        m = re.match(r"^(if|while|for|switch)\s*\(", t)
        if m:
            k = _match(t, m.end() - 1, "(", ")")
            return (m.group(1), t[m.end() - 1:k + 1]), t[k + 1:].strip()
        m = re.match(r"^(case\s+(.+)|default)\s*:\s*(.*)$", t, flags=re.S)
        if m:
            return ("case", m.group(2) or "default"), m.group(3).strip()
        return None, None

    def _body(self, body, rest, units, ind, lines, ctx):
        n0 = len(lines)
        if body:
            self._emit(units, body[0], body[1], ind, lines, ctx)
        elif rest:
            self._emit(_units(rest + ";"), 0, len(_units(rest + ";")), ind, lines, ctx)
        if len(lines) == n0:
            lines.append("    " * ind + "pass")

    def _emit_control(self, header, rest, body, units, ind, lines, ctx, nxt):
        pad = "    " * ind
        kind, cond = header
        if kind in ("if", "elif", "while"):
            lines.append(f"{pad}{kind} {self.cx(cond[1:-1], ctx)}:")
            ctx["loops"].append(("while", [])) if kind == "while" else None
            self._body(body, rest, units, ind + 1, lines, ctx)
            if kind == "while":
                ctx["loops"].pop()
            return nxt
        if kind == "else":
            lines.append(f"{pad}else:")
            self._body(body, rest, units, ind + 1, lines, ctx)
            return nxt
        if kind == "do":
            lines.append(f"{pad}while True:")
            ctx["loops"].append(("while", []))
            self._body(body, rest, units, ind + 1, lines, ctx)
            ctx["loops"].pop()
            if nxt < len(units) and units[nxt][0] == "stmt" and units[nxt][1].startswith("while"):
                c = units[nxt][1][units[nxt][1].index("("):]
                lines.append(f"{pad}    if not ({self.cx(c[1:-1], ctx)}):")
                lines.append(f"{pad}        break")
                return nxt + 1
            return nxt
        if kind == "for":
            parts = _split_top(cond[1:-1], ";")
            init, test, step = (parts + ["", "", ""])[:3]
            rng = self._for_range(init, test, step, ctx)
            if rng:
                var, expr = rng
                lines.append(f"{pad}for {var} in {expr}:")
                ctx["locals"].add(var)
                ctx["types"].setdefault(var, "int")
                ctx["ints"].add(var)
                ctx["loops"].append(("range", []))
                self._body(body, rest, units, ind + 1, lines, ctx)
                ctx["loops"].pop()
                return nxt
            for l in (self.stmt(p, ctx) for p in _split_top(init) if p):
                lines.extend(pad + x for x in l)
            step_lines = [x for p in _split_top(step) if p for x in self.stmt(p, ctx)]
            lines.append(f"{pad}while {self.cx(test, ctx) if test.strip() else 'True'}:")
            ctx["loops"].append(("for", step_lines))
            self._body(body, rest, units, ind + 1, lines, ctx)
            ctx["loops"].pop()
            lines.extend(f"{pad}    {x}" for x in step_lines)
            return nxt
        if kind == "switch":
            var = f"_sw{ind}"
            lines.append(f"{pad}{var} = {self.cx(cond[1:-1], ctx)}")
            ctx["loops"].append(("switch", []))
            first = True
            pending: List[str] = []
            k = body[0] if body else 0
            stop = body[1] if body else 0
            while k < stop:
                u = units[k]
                h, r = self._split_header(u[1]) if u[0] == "stmt" else (None, None)
                if h and h[0] == "case":
                    labels = [h[1]]
                    while not r and k + 1 < stop and units[k + 1][0] == "stmt":
                        h2, r2 = self._split_header(units[k + 1][1])
                        if not (h2 and h2[0] == "case"):
                            break
                        labels.append(h2[1])
                        r = r2
                        k += 1
                    # collect statements until next case label
                    seg_start = k + 1
                    seg_end = seg_start
                    while seg_end < stop:
                        uu = units[seg_end]
                        hh = self._split_header(uu[1])[0] if uu[0] == "stmt" else None
                        if hh and hh[0] == "case":
                            break
                        if uu[0] == "open":
                            seg_end = self._close_of(units, seg_end)
                        seg_end += 1
                    if "default" in labels:
                        lines.append(f"{pad}else:" if not first else f"{pad}if True:")
                    else:
                        vals = ", ".join(self.cx(lbl, ctx) for lbl in labels)
                        test = f"{var} == {vals}" if len(labels) == 1 else f"{var} in ({vals})"
                        lines.append(f"{pad}{'if' if first else 'elif'} {test}:")
                    first = False
                    n0 = len(lines)
                    if r:
                        for l in self.stmt(r, ctx):
                            lines.append(pad + "    " + l)
                    self._emit(units, seg_start, seg_end, ind + 1, lines, ctx)
                    if len(lines) == n0:
                        lines.append(pad + "    pass")
                    k = seg_end
                else:
                    k += 1
            ctx["loops"].pop()
            return nxt
        if kind == "case":
            lines.append(f"{pad}# TODO case outside switch: {cond}")
            return nxt
        return nxt

    def _for_range(self, init, test, step, ctx):
        m = re.match(r"^(?:int|long|uint|ulong|short)?\s*(\w+)\s*=\s*(.+)$", init.strip())
        if not m:
            return None
        var, a = m.group(1), m.group(2)
        t = re.match(rf"^{var}\s*(<=|<|>=|>)\s*(.+)$", test.strip())
        if not t:
            return None
        op, b = t.group(1), t.group(2)
        st = step.strip().replace(" ", "")
        inc = st in (f"{var}++", f"++{var}", f"{var}+=1")
        dec = st in (f"{var}--", f"--{var}", f"{var}-=1")
        a_, b_ = self.cx(a, ctx), self.cx(b, ctx)
        if inc and op == "<":
            return var, f"range({a_}, {b_})" if a_ != "0" else f"range({b_})"
        if inc and op == "<=":
            stop = str(int(b_) + 1) if re.fullmatch(r"-?\d+", b_) else f"{b_} + 1"
            return var, f"range({a_}, {stop})"
        if dec and op == ">=":
            stop = str(int(b_) - 1) if re.fullmatch(r"-?\d+", b_) else f"{b_} - 1"
            return var, f"range({a_}, {stop}, -1)"
        if dec and op == ">":
            return var, f"range({a_}, {b_}, -1)"
        return None

    # ------------------------------------------------------------------ assemble
    def render(self, class_name: str, mq5_rel: str) -> str:
        self.scan()
        all_funcs = {f["name"] for f in self.funcs}
        outfuncs: Dict[str, List[int]] = {}
        for f in self.funcs:
            pos = []
            for k, p in enumerate(_split_top(f["params"]) if f["params"].strip() else []):
                mm = re.match(r"^(?:const\s+)?([\w]+)\s*(&)\s*(\w+)\s*(\[\s*\])?", p.strip())
                if mm and not mm.group(4) and mm.group(1) not in self.structs and mm.group(1) not in API_CLASSES:
                    pos.append(k)
            if pos:
                outfuncs[f["name"]] = pos
        methods = [self.function(f, all_funcs, outfuncs) for f in self.funcs]
        L = ['"""DRAFT Python port generated by `python -m ubt port` - REVIEW EVERY FUNCTION.',
             "",
             "Search for 'TODO'. Compare with the original EA in the MT5 tester:",
             "    python -m ubt mt5test ... --parity-with <python backtest folder>",
             '"""',
             "import math",
             "",
             "from ubt.mql5 import *  # noqa: F401,F403",
             "from ubt.strategy import Strategy",
             ""]
        if self.todo:
            L.append("# TODO list from the transpiler:")
            L.extend(f"#   - {t}" for t in self.todo)
            L.append("")
        for name, opts in self.enums.items():
            L.append(f"# enum {name}")
            L.extend(f"{k} = {v}" for k, v in opts.items())
        ctx0 = {"fname": "_module", "self_names": set(), "funcs": set(), "locals": set(), "types": {},
                "outs": [], "outfuncs": {}, "loops": [], "static_map": {}, "ints": set()}
        for name, val in self.defines + self.consts:
            L.append(f"{name} = {self.cx(val, ctx0)}")
        L.append("")
        for sname, fields in self.structs.items():
            L.append(f"class {sname}:")
            L.append("    def __init__(self):")
            if not fields:
                L.append("        pass")
            for fname, ftype, arr, size in fields:
                L.append(f"        self.{fname} = {_default_for(ftype, set(self.structs), arr, size)}")
            L.append("")
        L.append("")
        L.append(f"class {class_name}(Strategy):")
        L.append(f'    MQ5_FILE = "{mq5_rel}"')
        L.append("")
        L.append("    def __init__(self, inputs=None):")
        L.append("        super().__init__(inputs)")
        ctxg = dict(ctx0, self_names=set(self.globals) | set(self.inputs))
        for name, (typ, arr, size, init) in self.globals.items():
            if init and init.strip().startswith("{") and init.strip() != "{}":
                L.append(f"        self.{name} = {self._array_init(init, ctxg)}")
            elif init and init.strip() not in ("{}",):
                L.append(f"        self.{name} = {self.cx(init, ctxg)}")
            else:
                L.append(f"        self.{name} = {_default_for(typ, set(self.structs), arr, size)}")
        for attr, val in self.statics.items():
            L.append(f"        self.{attr} = {val}")
        L.append("")
        for m in methods:
            L.append(m)
            L.append("")
        return "\n".join(L).rstrip() + "\n"


def transpile_file(mq5_path: str, out_path: str, class_name: Optional[str] = None) -> Path:
    src_raw = Path(mq5_path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            src = src_raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    name = class_name or re.sub(r"[\W_]+", "", Path(mq5_path).stem.title()) or "PortedEA"
    out = Path(out_path)
    try:
        rel = Path(mq5_path).resolve().relative_to(out.resolve().parent.parent)
        rel_s = "../" + rel.as_posix()
    except ValueError:
        rel_s = Path(mq5_path).resolve().as_posix()
    t = Transpiler(src, mq5_path)
    code = t.render(name, rel_s)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(code, encoding="utf-8")
    return out
