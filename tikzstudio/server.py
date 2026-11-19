import math, os, re, subprocess, pymupdf, uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

app = FastAPI()
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB = os.path.join(_ROOT, "web")
_VSCODE = os.path.join(_ROOT, ".vscode")
_EDITORCONFIG = os.path.join(_VSCODE, ".editorconfig")
_EDITORCONFIG_DEFAULT = (
    "root = true\n"
    "\n"
    "[*]\n"
    "indent_style = space\n"
    "indent_size = 4\n"
    "tab_width = 4\n"
    "insert_final_newline = true\n"
    "trim_trailing_whitespace = true\n"
    "\n"
    "[*.{js,css,html,py,md,json}]\n"
    "indent_style = space\n"
    "indent_size = 4\n"
    "tab_width = 4\n"
)

def ensure_editorconfig():
    """Keep canonical config in .vscode/.editorconfig; expose a root link/copy for discovery."""
    os.makedirs(_VSCODE, exist_ok=True)
    if not os.path.isfile(_EDITORCONFIG):
        with open(_EDITORCONFIG, "w", encoding="utf-8", newline="\n") as f:
            f.write(_EDITORCONFIG_DEFAULT)
    root_ec = os.path.join(_ROOT, ".editorconfig")
    try:
        src_real = os.path.normcase(os.path.realpath(_EDITORCONFIG))
        if os.path.islink(root_ec) or os.path.isfile(root_ec):
            try:
                if os.path.normcase(os.path.realpath(root_ec)) == src_real:
                    return _EDITORCONFIG
            except OSError:
                pass
            try:
                os.remove(root_ec)
            except OSError:
                pass
        rel = os.path.relpath(_EDITORCONFIG, _ROOT)
        try:
            os.symlink(rel, root_ec)
        except OSError:
            with open(_EDITORCONFIG, encoding="utf-8") as f:
                text = f.read()
            with open(root_ec, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    except OSError:
        pass
    return _EDITORCONFIG

def read_editorconfig():
    path = ensure_editorconfig()
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = _EDITORCONFIG_DEFAULT
    indent_size, tab_width = 4, 4
    for m in re.finditer(r"^\s*(indent_size|tab_width)\s*=\s*(\d+)\s*$", text, re.M):
        if m.group(1) == "indent_size":
            indent_size = int(m.group(2))
        else:
            tab_width = int(m.group(2))
    return {
        "ok": True,
        "path": ".vscode/.editorconfig",
        "indent_size": indent_size,
        "tab_width": tab_width or indent_size,
        "text": text,
    }

ensure_editorconfig()

class Req(BaseModel):
    code: str
    compiler: str = "xelatex"
    fmt: str = "pdf"
    pick: bool = True  # False: skip all coordinate probes (FEA / large drawings)

PREAMBLE = (
    "\\documentclass[border=4mm]{standalone}\n"
    "\\usepackage{ctex,amsmath,amssymb,tikz}\n"
    "\\usepackage{tikz-3dplot}\n"
    "\\usepackage[outline]{contour}\n"
    "\\usepackage[siunitx]{circuitikz}\n"
    "\\usepackage{satopdf}\n"
    "\\usepackage{pgfplots}\n"
    "\\pgfplotsset{compat=1.18}\n"
    "\\usepgfplotslibrary{fillbetween}\n"
    "\\usetikzlibrary{arrows.meta,bending,3d,positioning,calc,shapes,"
    "decorations.pathreplacing,decorations.pathmorphing,patterns}\n"
    "\\tikzset{udim/.style={>=stealth,thin,"
    "ext line/.style={thin,black!65},"
    "dim in/.style={<->,thin,black},"
    "dim out/.style={->,thin,black},"
    "dim bridge/.style={thin,black},"
    "dim text/.style={fill=white,inner sep=1.5pt,font=\\small,text=black}}}\n"
    "\\begin{document}\n"
)

_UNIT = {"cm": 1.0, "mm": 0.1, "pt": 2.54 / 72.27, "in": 2.54, "em": 0.3515, "ex": 0.151}
_U = r"cm|mm|pt|in|em|ex"

def _uscale(unit):
    return _UNIT.get(unit or "", 1.0)

def _line_table(code):
    spans, off = [], 0
    for ln, line in enumerate(code.splitlines(True), 1):
        cut, i = len(line), 0
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                cut = i
                break
            i += 1
        spans.append((off, off + len(line), ln, cut))
        off += len(line)
    return spans

def _at(spans, pos):
    for a, b, ln, cut in spans:
        if a <= pos < b:
            return ln, pos - a, cut
    return None

def _commented(spans, pos):
    info = _at(spans, pos)
    return (not info) or info[1] >= info[2]

def _read_bracket(code, i):
    while i < len(code) and code[i].isspace():
        i += 1
    if i >= len(code) or code[i] != "[":
        return "", i
    depth, j = 0, i
    while j < len(code):
        if code[j] == "[":
            depth += 1
        elif code[j] == "]":
            depth -= 1
            if depth == 0:
                return code[i + 1:j], j + 1
        j += 1
    return code[i + 1:], len(code)

def _ops_from(opt):
    ops = []
    for m in re.finditer(rf'(rotate|xscale|yscale|scale)\s*=\s*([-+]?\d*\.?\d+)', opt):
        k, v = m.group(1), float(m.group(2))
        if k == "rotate":
            ops.append(["r", v])
        elif k == "scale":
            ops.append(["s", v, v])
        elif k == "xscale":
            ops.append(["s", v, 1.0])
        else:
            ops.append(["s", 1.0, v])
    return ops

def _scope_table(code):
    ranges, stack, i = [], [], 0
    while True:
        b, e = code.find(r"\begin{scope}", i), code.find(r"\end{scope}", i)
        if b < 0 and e < 0:
            break
        if e >= 0 and (b < 0 or e < b):
            if stack:
                start, _opt, ops = stack.pop()
                ranges.append((start, e, ops))
            i = e + 11
        else:
            opt, _n = _read_bracket(code, b + len(r"\begin{scope}"))
            stack.append((b, opt, _ops_from(opt)))
            i = b + len(r"\begin{scope}")
    return ranges

def _xf_at(ranges, pos):
    owned = sorted((a, ops) for a, b, ops in ranges if a < pos < b)
    out = []
    for _a, ops in owned:
        out.extend(ops)
    return out

def _inject_at(code, pos):
    best = None
    for a, b, _ops in _scope_table(code):
        if a < pos < b and (best is None or a > best[0]):
            best = (a, b)
    if best:
        return best[1]
    for env in (r"\end{circuitikz}", r"\end{tikzpicture}"):
        i = code.rfind(env)
        if i >= 0:
            return i
    return len(code)

def _picture_end(code):
    for env in (r"\end{circuitikz}", r"\end{tikzpicture}"):
        i = code.rfind(env)
        if i >= 0:
            return i
    return len(code)

def _num_pair(text):
    m = re.fullmatch(rf'\s*([-+]?\d*\.?\d+)\s*({_U})?\s*,\s*([-+]?\d*\.?\d+)\s*({_U})?\s*', text)
    if not m:
        return None
    return m

def _center_expr(inner, dx, dy):
    raw = inner.strip()
    m = re.fullmatch(r'\(\s*([+-]?\d*\.?\d+)\s*,\s*([+-]?\d*\.?\d+)\s*(?:,\s*([+-]?\d*\.?\d+))?\s*\)', raw)
    if m:
        x, y = float(m.group(1)) + dx, float(m.group(2)) + dy
        if m.group(3) is None:
            return f"({x:.4f},{y:.4f})"
        return f"({x:.4f},{y:.4f},{m.group(3)})"
    return f"($({_as_probe(raw)})+({dx:.4f},{dy:.4f})$)"

def _as_probe(inner):
    t = inner.strip()
    if t.startswith("($") and t.endswith("$)"):
        return t[2:-2]
    if t.startswith("(") and t.endswith(")") and not re.search(r'\)\s*[+-]', t):
        return t[1:-1]
    if t.startswith("$") and t.endswith("$"):
        return t
    return f"${t}$"

def _decl_name(prefix):
    return re.search(r'(?:\\node|\\coordinate|(?<![\\A-Za-z])node|(?<![\\A-Za-z])coordinate)\s*(?:\[[^\]]*\])?\s*$', prefix) is not None

_TOK = re.compile(
    r'\(\$[^$\n]*\$\)'
    rf'|(?<!\+)\+\+?\s*\(\s*[-+]?\d*\.?\d+\s*(?:{_U})?\s*,\s*[-+]?\d*\.?\d+\s*(?:{_U})?\s*\)'
    rf'|(?<!\+)\+\+?\s*\(\s*[-+]?\d*\.?\d+\s*:\s*[-+]?\d*\.?\d+\s*(?:{_U})?\s*\)'
    rf'|(?<![+\w.=:])\(\s*[-+]?\d*\.?\d+\s*(?:{_U})?\s*,\s*[-+]?\d*\.?\d+\s*(?:{_U})?(?:\s*,\s*[-+]?\d*\.?\d+\s*(?:{_U})?)?\s*\)'
    rf'|(?<![+\w.=])\(\s*[-+]?\d*\.?\d+\s*:\s*[-+]?\d*\.?\d+\s*(?:{_U})?\s*\)'
    r'|(?<![+\w.$!])\(\s*[A-Za-z][A-Za-z0-9_.+\-]*(?:\s+(?:east|west))?(?:\s*(?:\|-|-\|)\s*[A-Za-z][A-Za-z0-9_.+\-]*)?\s*\)'
)

def _last_current(code, start, end, resolved):
    cands = [tm for tm in _TOK.finditer(code, start, end)]
    while cands:
        tm = cands.pop()
        raw = tm.group(0).lstrip()
        if raw.startswith("+") and not raw.startswith("++"):
            continue
        if raw.startswith("++"):
            return resolved.get(tm.end())
        return raw if raw.startswith("(") else tm.group(0).strip()
    return None

def _put(probes, pts, expr, at, pt, ranges):
    pid = len(probes)
    probes.append((pid, expr, at))
    pt["pid"] = pid
    xf = _xf_at(ranges, at)
    if xf:
        pt["xf"] = xf
    pts.append(pt)
    return pid

def _inside_calc(code, pos):
    line_at = code.rfind("\n", 0, pos) + 1
    depth = 0
    i = pos - 1
    while i >= line_at:
        ch = code[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            depth = max(0, depth - 1)
        elif ch == "$" and depth == 0:
            j = i + 1
            while j < pos and code[j] in " \t":
                j += 1
            return j < pos and code[j] == "("
        i -= 1
    return False

def add_steps(code, pts, probes, used, spans, ranges):
    """++ updates the current point; a single + does not. Both can carry units or be polar."""
    cart = re.compile(rf'(?<!\+)\+\+?\s*\(\s*([-+]?\d*\.?\d+)\s*({_U})?\s*,\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\)')
    polar = re.compile(rf'(?<!\+)\+\+?\s*\(\s*([-+]?\d*\.?\d+)\s*:\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\)')
    resolved = {}
    hits = []
    for m in cart.finditer(code):
        hits.append((m.start(), "xy", m))
    for m in polar.finditer(code):
        hits.append((m.start(), "pol", m))
    for _pos, kind, m in sorted(hits, key=lambda t: t[0]):
        if _commented(spans, m.start()):
            continue
        if _inside_calc(code, m.start()):
            continue
        info = _at(spans, m.start())
        if not info:
            continue
        ln = info[0]
        raw = m.group(0).lstrip()
        plus = raw.startswith("+") and not raw.startswith("++")
        lp = m.group(0).find("(")
        s, e = m.start() + lp, m.end()
        semi = code.rfind(";", 0, m.start())
        inner = _last_current(code, semi + 1, m.start(), resolved)
        if inner is None and resolved:
            inner = resolved[max(k for k in resolved if k <= m.start())] if any(k <= m.start() for k in resolved) else None
        if kind == "xy":
            step = f"+({m.group(1)}{m.group(2) or ''},{m.group(3)}{m.group(4) or ''})"
        else:
            rad, unit = m.group(2), m.group(3) or ""
            step = f"+({{{rad}{unit}*cos({m.group(1)})}},{{{rad}{unit}*sin({m.group(1)})}})"
        if s in used:
            if inner and not plus:
                resolved[e] = inner + step
            continue
        if not inner:
            continue
        if not plus:
            resolved[e] = inner + step
        if kind == "xy":
            pt = {"kind": "rel", "label": "+step" if plus else "++step", "base": "", "x": float(m.group(1)), "y": float(m.group(3)), "s": s, "e": e, "l": ln}
            if m.group(2):
                pt["ux"], pt["xs"] = m.group(2), _uscale(m.group(2))
            if m.group(4):
                pt["uy"], pt["ys"] = m.group(4), _uscale(m.group(4))
            _put(probes, pts, f"${inner}{step}$", s, pt, ranges)
        else:
            bpid = len(probes)
            probes.append((bpid, _as_probe(inner), s))
            pt = {"kind": "polar", "label": "+polar" if plus else "++polar", "base": "", "x": float(m.group(1)), "y": float(m.group(2)), "s": s, "e": e, "l": ln, "bpid": bpid, "a0": float(m.group(1))}
            if m.group(3):
                pt["uy"], pt["ys"] = m.group(3), _uscale(m.group(3))
            _put(probes, pts, f"${inner}{step}$", s, pt, ranges)
        for k in range(s, e):
            used.add(k)
    return resolved

def _brace_end(code, open_paren):
    depth, i = 0, open_paren
    while i < len(code):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None

def _open_paren(code, close_paren):
    depth, i = 0, close_paren
    while i >= 0:
        if code[i] == ")":
            depth += 1
        elif code[i] == "(":
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return None

def _end_spec(body, base):
    got = _num_pair(body)
    if not got:
        return None
    x_s = base + got.start(1)
    x_e = base + got.end(1)
    y_s = base + got.start(3)
    y_e = base + got.end(3)
    return {"s": base, "e": base + len(body) + 2 if False else None, "x": float(got.group(1)), "y": float(got.group(3)),
            "ux": got.group(2) or "", "uy": got.group(4) or "", "xs": _uscale(got.group(2)), "ys": _uscale(got.group(4)),
            "xs0": x_s, "xs1": x_e, "ys0": y_s, "ys1": y_e}

def add_paths(code, pts, probes, used, spans, ranges, resolved):
    # Component midpoint, including a to[] split across lines.
    p_to = re.compile(r'\(\s*([^()]+?)\s*\)\s*to\s*(\[[^\]]*\])\s*\(\s*([^()]+?)\s*\)', re.S)
    for m in p_to.finditer(code):
        if _commented(spans, m.start(2)) or ";" in m.group(1):
            continue
        b0 = m.start(2)
        if b0 in used:
            continue
        info = _at(spans, b0)
        a, b = m.group(1).strip(), m.group(3).strip()
        if "\\" in a or "\\" in b:
            continue
        ends = []
        for body, origin in ((m.group(1), m.start(1)), (m.group(3), m.start(3))):
            spec = _end_spec(body, origin)
            if spec:
                spec["s"] = origin - 1
                spec["e"] = origin + len(body)
                # origin is the first char inside the parens; the '(' is origin-1 if the match includes it
                ends.append(spec)
        # Fix spans: group 1 starts at the first char inside '(' because of \s* after '('.
        # Recompute from the full match so replacement covers '(...)'.
        ends = []
        for g in (1, 3):
            open_i = code.rfind("(", m.start(g) - 1, m.start(g) + 1)
            close_i = code.find(")", m.end(g) - 1, m.end(g) + 1)
            spec = _end_spec(m.group(g), m.start(g))
            if spec and open_i >= 0 and close_i > open_i:
                spec["s"], spec["e"] = open_i, close_i + 1
                ends.append({"s": spec["s"], "e": spec["e"], "x": spec["x"], "y": spec["y"], "ux": spec["ux"], "uy": spec["uy"], "xs": spec["xs"], "ys": spec["ys"]})
        pt = {"kind": "mid", "label": "元件中点", "x": 0.0, "y": 0.0, "s": b0, "e": m.end(2), "l": info[0] if info else 1, "ends": ends}
        _put(probes, pts, f"$({a})!0.5!({b})$", b0, pt, ranges)
        for k in range(b0, m.end(2)):
            used.add(k)
    # Path corners. (a) -| (b) turns at x of b and y of a. (a) |- (b) is the other way.
    p_corner = re.compile(r'\)\s*(-\||\|-)\s*\(')
    for m in p_corner.finditer(code):
        if _commented(spans, m.start()):
            continue
        close_a = code.rfind(")", 0, m.start() + 1)
        open_a = _open_paren(code, close_a)
        open_b = m.end() - 1
        close_b = _brace_end(code, open_b)
        if open_a is None or close_b is None:
            continue
        body_a, body_b = code[open_a + 1:close_a], code[open_b + 1:close_b]
        if "\\" in body_a or "\\" in body_b or ";" in body_a:
            continue
        op = m.group(1)
        if op == "-|":
            expr = f"perpendicular cs:horizontal line through={{({body_a})}},vertical line through={{({body_b})}}"
        else:
            expr = f"perpendicular cs:horizontal line through={{({body_b})}},vertical line through={{({body_a})}}"
        sa, sb = _end_spec(body_a, open_a + 1), _end_spec(body_b, open_b + 1)
        # -| corner x comes from B, y from A. |- corner x comes from A, y from B.
        hx_src, vy_src = (sb, sa) if op == "-|" else (sa, sb)
        pt = {"kind": "corner", "label": op, "x": 0.0, "y": 0.0, "s": open_a, "e": close_b + 1, "l": _at(spans, m.start())[0]}
        if hx_src:
            pt["hx"] = {"s": hx_src["xs0"], "e": hx_src["xs1"], "v": hx_src["x"], "u": hx_src["ux"], "xs": hx_src["xs"]}
            pt["x"] = hx_src["x"]
        if vy_src:
            pt["vy"] = {"s": vy_src["ys0"], "e": vy_src["ys1"], "v": vy_src["y"], "u": vy_src["uy"], "xs": vy_src["ys"]}
            pt["y"] = vy_src["y"]
        _put(probes, pts, expr, m.start(), pt, ranges)
    # Arc end, and circle / ellipse radius. Skip the junction dots written as circle (1pt).
    p_arc = re.compile(rf'arc\s*\(\s*([-+]?\d*\.?\d+)\s*:\s*([-+]?\d*\.?\d+)\s*:\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\)')
    for m in p_arc.finditer(code):
        if _commented(spans, m.start()):
            continue
        semi = code.rfind(";", 0, m.start())
        inner = _last_current(code, semi + 1, m.start(), resolved)
        if not inner:
            continue
        a0, a1, rad, unit = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        rr = float(rad) * _uscale(unit)
        ang = math.radians(float(a0))
        rtxt = rad + unit
        arm0 = f"+({{-{rtxt}*cos({a0})}},{{-{rtxt}*sin({a0})}})"
        arm1 = f"+({{{rtxt}*cos({a1})}},{{{rtxt}*sin({a1})}})"
        end = f"${inner}{arm0}{arm1}$"
        cpid = len(probes)
        cen_expr = f"${inner}{arm0}$"
        probes.append((cpid, cen_expr, m.start()))
        lp, rp = m.group(0).find("("), m.end()
        s = m.start() + lp
        pt = {"kind": "arc", "label": "弧端", "x": float(a1), "y": float(rad), "a0": float(a0), "rr": rr, "cen": _center_expr(inner, -rr * math.cos(ang), -rr * math.sin(ang)), "s": s, "e": rp, "l": _at(spans, m.start())[0], "cpid": cpid}
        if unit:
            pt["uy"], pt["ys"] = unit, _uscale(unit)
        _put(probes, pts, end, m.start(), pt, ranges)
    p_circ = re.compile(rf'circle\s*(?:\(\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\)|\[\s*radius\s*=\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\])')
    for m in p_circ.finditer(code):
        if _commented(spans, m.start()):
            continue
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if _uscale(unit) * float(num) < 0.08:
            continue
        semi = code.rfind(";", 0, m.start())
        inner = _last_current(code, semi + 1, m.start(), resolved)
        if not inner:
            continue
        ns = m.start(1) if m.group(1) else m.start(3)
        ne = m.end(2) if m.group(1) and m.group(2) else (m.end(1) if m.group(1) else (m.end(4) if m.group(4) else m.end(3)))
        cpid = len(probes)
        probes.append((cpid, _as_probe(inner), m.start()))
        step = f"+({num}{unit or ''},0)"
        pt = {"kind": "rad", "label": "半径", "axis": "x", "x": float(num), "y": 0.0, "rr": float(num) * _uscale(unit), "cen": inner.strip() if inner.strip().startswith("(") else "(" + inner.strip() + ")", "s": ns, "e": ne, "l": _at(spans, m.start())[0], "cpid": cpid}
        if unit:
            pt["ux"], pt["xs"] = unit, _uscale(unit)
        _put(probes, pts, f"${inner}{step}$", m.start(), pt, ranges)
    def _ell_put(inner, rx, ry, ux, uy, sx, sy, ex, ey, rot, at, line):
        cpid = len(probes)
        probes.append((cpid, _as_probe(inner), at))
        th = float(rot or 0.0)
        th_r = math.radians(th)
        for axis, val, s0, e0, unit in (
            ("x", rx, sx, ex, ux),
            ("y", ry, sy, ey, uy),
        ):
            r_cm = float(val) * _uscale(unit)
            if abs(th) > 1e-9:
                if axis == "x":
                    step = f"+({r_cm * math.cos(th_r):.4f},{r_cm * math.sin(th_r):.4f})"
                else:
                    step = f"+({-r_cm * math.sin(th_r):.4f},{r_cm * math.cos(th_r):.4f})"
            else:
                step = f"+({val}{unit or ''},0)" if axis == "x" else f"+(0,{val}{unit or ''})"
            pt = {
                "kind": "rad",
                "label": "X半径" if axis == "x" else "Y半径",
                "axis": axis,
                "x": float(val),
                "y": 0.0,
                "rr": r_cm,
                "rot": th,
                "cen": inner.strip() if inner.strip().startswith("(") else "(" + inner.strip() + ")",
                "s": s0,
                "e": e0,
                "l": line,
                "cpid": cpid,
            }
            if unit:
                pt["ux"], pt["xs"] = unit, _uscale(unit)
            _put(probes, pts, f"${inner}{step}$", at, pt, ranges)

    p_ell = re.compile(rf'ellipse\s*\(\s*([-+]?\d*\.?\d+)\s*({_U})?\s+and\s+([-+]?\d*\.?\d+)\s*({_U})?\s*\)')
    for m in p_ell.finditer(code):
        if _commented(spans, m.start()):
            continue
        semi = code.rfind(";", 0, m.start())
        inner = _last_current(code, semi + 1, m.start(), resolved)
        if not inner:
            continue
        st = code.rfind("\n", 0, m.start()) + 1
        ed = code.find(";", m.start())
        head = code[st:m.start()]
        rot_m = re.search(r'rotate\s*=\s*([-+]?\d*\.?\d+)', head)
        if not rot_m:
            rot_m = re.search(r'rotate\s+around\s*=\s*\{\s*([-+]?\d*\.?\d+)\s*:', head)
        rot = float(rot_m.group(1)) if rot_m else 0.0
        _ell_put(
            inner,
            m.group(1), m.group(3), m.group(2), m.group(4),
            m.start(1), m.start(3),
            m.end(2) if m.group(2) else m.end(1),
            m.end(4) if m.group(4) else m.end(3),
            rot, m.start(), _at(spans, m.start())[0],
        )
    p_ell_br = re.compile(
        rf'ellipse\s*\[\s*x\s+radius\s*=\s*([-+]?\d*\.?\d+)\s*({_U})?\s*,\s*y\s+radius\s*=\s*([-+]?\d*\.?\d+)\s*({_U})?'
        rf'(?:\s*,\s*rotate\s*=\s*([-+]?\d*\.?\d+))?\s*\]',
        re.I,
    )
    for m in p_ell_br.finditer(code):
        if _commented(spans, m.start()):
            continue
        semi = code.rfind(";", 0, m.start())
        inner = _last_current(code, semi + 1, m.start(), resolved)
        if not inner:
            continue
        rot = float(m.group(5) or 0.0)
        _ell_put(
            inner,
            m.group(1), m.group(3), m.group(2), m.group(4),
            m.start(1), m.start(3),
            m.end(2) if m.group(2) else m.end(1),
            m.end(4) if m.group(4) else m.end(3),
            rot, m.start(), _at(spans, m.start())[0],
        )

def parse_points(code):
    pts, probes, used = [], [], set()
    p_calc = re.compile(r'\$\s*\(\s*([^()$]+?)\s*\)\s*\+\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\)\s*\$')
    p_lerp = re.compile(r'\$\s*\(\s*([^()$]+?)\s*\)\s*!\s*([-+]?\d*\.?\d+)\s*!\s*\(\s*([^()$]+?)\s*\)\s*(?:\+\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\))?\s*\$')
    p_rel = re.compile(r'\(\s*([a-zA-Z0-9_.-]+)\s*\)\s*(?:--)?\s*\+\+\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\)')
    p_pol = re.compile(rf'(?<![+\w.=])\s*\(\s*([-+]?\d*\.?\d+)\s*:\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\)')
    p_xyz = re.compile(rf'(?<![+\w.=:])\s*\(\s*([-+]?\d*\.?\d+)\s*({_U})?\s*,\s*([-+]?\d*\.?\d+)\s*({_U})?\s*,\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\)')
    p_abs = re.compile(rf'(?<![+\w.=:])\s*\(\s*([-+]?\d*\.?\d+)\s*({_U})?\s*,\s*([-+]?\d*\.?\d+)\s*({_U})?\s*\)')
    p_anc = re.compile(r'(?<![+\w.$!])\s*\(\s*([A-Za-z][A-Za-z0-9_]*(?:\.(?:[+\-]|[A-Za-z0-9_]+|north east|north west|south east|south west))?(?:\s*(?:\|-|-\|)\s*[A-Za-z][A-Za-z0-9_.+\-]*)?)\s*\)')
    p_scope = re.compile(r'\\begin\{scope\}\s*\[[^\]]*?shift\s*=\s*\{\s*\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*(?:,\s*([-+]?\d*\.?\d+)\s*)?\)\s*\}[^\]]*\]')
    ranges, spans = _scope_table(code), _line_table(code)
    lines = code.splitlines(True)
    off, sx_off, sy_off, in_fe, fe_xs = 0, 0.0, 0.0, False, []
    for ln, line in enumerate(lines, 1):
        if line.lstrip().startswith('%'): off += len(line); continue
        sm = p_scope.search(line)
        if sm:
            sx_off, sy_off = float(sm.group(1)), float(sm.group(2))
            for k in range(off + sm.start(), off + sm.end()): used.add(k)
        if r'\end{scope}' in line: sx_off, sy_off = 0.0, 0.0
        if r'\foreach' in line:
            in_fe, fe_xs = True, []
            bm = re.search(r'\{([^}]+)\}', line)
            if bm:
                for item in bm.group(1).split(','):
                    nm = re.match(r'\s*([-+]?\d*\.?\d+)', item)
                    if nm:
                        xv = float(nm.group(1)); fe_xs.append(xv)
                        pts.append({"kind":"lerp","label":"循环X","base":"","x":xv,"y":0.0,"wx":xv,"wy":0.0,"s":off+bm.start(1)+item.find(nm.group(1)),"e":off+bm.start(1)+item.find(nm.group(1))+len(nm.group(1)),"l":ln,"pid":-1})
        if in_fe:
            for ym in re.finditer(r'\(\s*\\[a-zA-Z]+\s*,\s*([-+]?\d*\.?\d+)\s*\)', line):
                yv = float(ym.group(1)); lp = line.find(',', ym.start()) + 1; rp = line.find(')', lp)
                for xv in (fe_xs or [0.0]): pts.append({"kind":"lerp","label":"循环Y","base":"","x":yv,"y":0.0,"wx":xv,"wy":yv,"s":off+lp,"e":off+rp,"l":ln,"pid":-1})
                for pt in pts:
                    if pt["label"] == "循环X" and pt["wy"] == 0.0: pt["wy"] = yv
            if '}' in line and not line.strip().endswith('{'): in_fe = False
            off += len(line); continue
        for m in p_calc.finditer(line):
            if line[:m.start()].count("$") % 2 == 1: continue
            base, dx, dy = m.group(1).strip(), float(m.group(2)), float(m.group(3))
            if '\\' in base or '!' in base: continue
            lp = line.find('(', line.find('+', m.start())); rp = line.find(')', lp) + 1
            s, e, pid = off + lp, off + rp, len(probes)
            probes.append((pid, f"$({base})+({dx},{dy})$", s))
            pts.append({"kind":"offset","label":f"{base}+offset","base":base,"x":dx,"y":dy,"s":s,"e":e,"l":ln,"pid":pid})
            for k in range(off + m.start(), off + m.end()): used.add(k)
        for m in p_lerp.finditer(line):
            a, tval, b = m.group(1).strip(), float(m.group(2)), m.group(3).strip()
            if '\\' in a or '\\' in b: continue
            b1 = line.find('!', m.start()); b2 = line.find('!', b1 + 1) + 1; s, e = off + b1, off + b2
            if s in used: continue
            ex = f"+({m.group(4)},{m.group(5)})" if m.group(4) else ""; pid = len(probes)
            probes.append((pid, f"$({a})!{tval}!({b}){ex}$", s))
            pts.append({"kind":"lerp","label":f"{a}..{b}比例","base":f"{a}|{b}","x":tval,"y":0.0,"s":s,"e":e,"l":ln,"pid":pid})
            for k in range(off + m.start(), off + m.end()): used.add(k)
        for m in p_rel.finditer(line):
            base, dx, dy = m.group(1).strip(), float(m.group(2)), float(m.group(3))
            lp = line.find('(', line.find('++', m.start())); rp = line.find(')', lp) + 1; s, e = off + lp, off + rp
            if s in used: continue
            pid = len(probes); probes.append((pid, f"$({base})+({dx},{dy})$", s))
            pts.append({"kind":"rel","label":f"{base}++step","base":base,"x":dx,"y":dy,"s":s,"e":e,"l":ln,"pid":pid})
            for k in range(s, e): used.add(k)
        for m in p_pol.finditer(line):
            lp = line.find('(', m.start(), m.end()); s, e = off + lp, off + m.end()
            if s in used: continue
            pid = len(probes); probes.append((pid, line[lp + 1:m.end() - 1].strip(), s))
            bpid = len(probes); probes.append((bpid, "0,0", s))
            pt = {"kind":"polar","label":"极坐标","base":"","x":float(m.group(1)),"y":float(m.group(2)),"s":s,"e":e,"l":ln,"pid":pid,"bpid":bpid}
            if m.group(3): pt["uy"], pt["ys"] = m.group(3), _uscale(m.group(3))
            pts.append(pt)
            for k in range(s, e): used.add(k)
        for m in p_xyz.finditer(line):
            lp = line.find('(', m.start(), m.end()); s, e = off + lp, off + m.end()
            if s in used: continue
            pid = len(probes); probes.append((pid, line[lp + 1:m.end() - 1].strip(), s))
            pt = {"kind":"xyz","label":"三维","base":"","x":float(m.group(1)),"y":float(m.group(3)),"z":float(m.group(5)),"s":s,"e":e,"l":ln,"pid":pid,"uzx":-0.385,"uzy":-0.385}
            if m.group(2): pt["ux"], pt["xs"] = m.group(2), _uscale(m.group(2))
            if m.group(4): pt["uy"], pt["ys"] = m.group(4), _uscale(m.group(4))
            if m.group(6): pt["uz"], pt["zs"] = m.group(6), _uscale(m.group(6))
            pts.append(pt)
            for k in range(s, e): used.add(k)
        # satopdf: \stpNode{name}{x,y}  — brace coords (CAE / mm models)
        for m in re.finditer(
            r'\\stpNode\s*\{([A-Za-z][A-Za-z0-9_]*)\}\s*\{\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\}',
            line,
        ):
            xs, xe = m.start(2), m.end(3)
            s, e = off + xs, off + xe
            if s in used: continue
            xv, yv = float(m.group(2)), float(m.group(3))
            pid = len(probes)
            probes.append((pid, f"{m.group(2).strip()},{m.group(3).strip()}", s))
            pts.append({
                "kind": "abs", "stp": "node", "label": m.group(1), "base": m.group(1),
                "x": xv, "y": yv, "sx": sx_off, "sy": sy_off, "s": s, "e": e, "l": ln, "pid": pid,
            })
            for k in range(off + m.start(), off + m.end()): used.add(k)
        # satopdf: \stpPoint{name}{x}{y}
        for m in re.finditer(
            r'\\stpPoint\s*\{([A-Za-z][A-Za-z0-9_]*)\}\s*\{\s*([-+]?\d*\.?\d+)\s*\}\s*\{\s*([-+]?\d*\.?\d+)\s*\}',
            line,
        ):
            xs, xe = m.start(2), m.end(3)
            s, e = off + xs, off + xe
            if s in used: continue
            xv, yv = float(m.group(2)), float(m.group(3))
            pid = len(probes)
            probes.append((pid, f"{m.group(2).strip()},{m.group(3).strip()}", s))
            pts.append({
                "kind": "abs", "stp": "point", "label": m.group(1), "base": m.group(1),
                "x": xv, "y": yv, "sx": sx_off, "sy": sy_off, "s": s, "e": e, "l": ln, "pid": pid,
            })
            for k in range(off + m.start(), off + m.end()): used.add(k)
        for m in p_abs.finditer(line):
            lp = line.find('(', m.start(), m.end()); s, e = off + lp, off + m.end()
            if s in used: continue
            pid = len(probes); probes.append((pid, line[lp + 1:m.end() - 1].strip(), s))
            pt = {"kind":"abs","label":"绝对坐标","base":"","x":float(m.group(1)),"y":float(m.group(3)),"sx":sx_off,"sy":sy_off,"s":s,"e":e,"l":ln,"pid":pid}
            if m.group(2): pt["ux"], pt["xs"] = m.group(2), _uscale(m.group(2))
            if m.group(4): pt["uy"], pt["ys"] = m.group(4), _uscale(m.group(4))
            pts.append(pt)
            for k in range(s, e): used.add(k)
        for m in p_anc.finditer(line):
            lp = line.find('(', m.start(), m.end()); s, e = off + lp, off + m.end()
            if s in used: continue
            base = re.sub(r'\s+', ' ', m.group(1).strip())
            if not re.match(r'^[a-zA-Z]', base) or base.split('.')[0] in ('right','left','above','below','north','south','east','west','center','short','open','circ','ocirc','ground','and'): continue
            if _decl_name(line[:m.start()]): continue
            pid = len(probes); probes.append((pid, base, s))
            pts.append({"kind":"anchor","label":base,"base":base,"x":0.0,"y":0.0,"s":s,"e":e,"l":ln,"pid":pid})
            for k in range(s, e): used.add(k)
        off += len(line)
    resolved = add_steps(code, pts, probes, used, spans, ranges)
    add_paths(code, pts, probes, used, spans, ranges, resolved)
    for pt in pts:
        if pt.get("xf") or pt.get("s") is None: continue
        xf = _xf_at(ranges, pt["s"])
        if xf: pt["xf"] = xf
    ports = []
    seen = set()
    compass = ("center", "north", "south", "east", "west", "north east", "north west", "south east", "south west")
    for m in re.finditer(r'\\node\s*(\[[^\]]*\])?\s*\(([^)]+)\)', code):
        opt, name = m.group(1) or "", m.group(2).strip()
        if not re.match(r'^[A-Za-z][A-Za-z0-9_]*$', name) or name in seen: continue
        if re.search(r'\b(circ|ground|ocirc)\b', opt) and "draw" not in opt and "minimum" not in opt: continue
        seen.add(name)
        for anc in compass:
            pid = len(probes)
            ref = f"{name}.{anc}"
            probes.append((pid, ref, m.start()))
            ports.append({"name": name, "anchor": anc, "ref": ref, "pid": pid})
    return pts, probes, ports

def _env_body_empty(code):
    m = re.search(r'\\begin\s*\{(tikzpicture|circuitikz)\}(?:\s*\[[^\]]*\])?(.*?)\\end\s*\{\1\}', code, re.S)
    if not m:
        return False
    kept = []
    for line in m.group(2).splitlines():
        cut = len(line)
        for i, ch in enumerate(line):
            if ch == '%' and (i == 0 or line[i - 1] != '\\'):
                cut = i
                break
        kept.append(line[:cut])
    return not "".join(kept).strip()

def _cal_span(pts):
    """TikZ-unit span for calibration markers. Unit=1 fails when x=0.14mm (1 unit ≈ 0.4pt)."""
    m = 0.0
    for pt in pts or []:
        if pt.get("kind") in ("abs", "xyz"):
            m = max(m, abs(float(pt.get("x", 0) or 0)), abs(float(pt.get("y", 0) or 0)))
            if pt.get("z") is not None:
                m = max(m, abs(float(pt["z"] or 0)))
    if m <= 20:
        return 1.0
    return float(max(50.0, round(m * 0.1, 1)))

def prep(raw, probes=None, with_cal=True, cal_span=1.0):
    is_doc = (r"\documentclass" in raw or r"\begin{document}" in raw)
    buckets = {}
    for pid, expr, at in (probes or []):
        g, b = (pid // 200) + 10, (pid % 200) + 10
        frag = f"\\definecolor{{cp{pid}}}{{RGB}}{{200,{g},{b}}}\\fill[cp{pid},opacity=0.05]({expr})circle(0.6pt);\n"
        buckets.setdefault(_inject_at(raw, at), []).append(frag)
    end = _picture_end(raw)
    if end < len(raw):
        if _env_body_empty(raw):
            buckets.setdefault(end, []).append("\\path (-4,-3) rectangle (5,5);\n")
        if with_cal:
            s = f"{cal_span:g}"
            cal = ("\\definecolor{ca}{RGB}{254,1,253}\\definecolor{cb}{RGB}{1,254,252}"
                   "\\definecolor{cc}{RGB}{254,80,1}\\definecolor{cd}{RGB}{1,80,254}"
                   f"\\fill[ca,opacity=0.05](0,0)circle(0.6pt);\\fill[cb,opacity=0.05]({s},{s})circle(0.6pt);"
                   f"\\fill[cc,opacity=0.05]({s},0)circle(0.6pt);\\fill[cd,opacity=0.05](0,{s})circle(0.6pt);\n")
            buckets.setdefault(end, []).append(cal)
    text = raw
    for pos in sorted(buckets, reverse=True):
        text = text[:pos] + "".join(buckets[pos]) + text[pos:]
    body = text.strip()
    return body if is_doc else PREAMBLE + body + "\n\\end{document}\n"

def _tex_env():
    """Prefer project-bundled sty files (texmf/tex/latex/local) before the system tree."""
    env = os.environ.copy()
    local = os.path.join(_ROOT, "texmf", "tex", "latex", "local").replace("\\", "/")
    sep = ";" if os.name == "nt" else ":"
    env["TEXINPUTS"] = local + "//" + sep + env.get("TEXINPUTS", "")
    return env

def build_pdf(tex_str, compiler):
    d = os.path.join(_ROOT, ".tikz_cache"); os.makedirs(d, exist_ok=True)
    tf, pf = os.path.join(d, "m.tex"), os.path.join(d, "m.pdf")
    if os.path.exists(pf):
        try: os.remove(pf)
        except OSError: pass
    with open(tf, "w", encoding="utf-8") as f: f.write(tex_str)
    comp = compiler if compiler in ("xelatex", "pdflatex") else "xelatex"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run([comp, "-interaction=nonstopmode", "-halt-on-error", "m.tex"], cwd=d, env=_tex_env(), capture_output=True, text=True, creationflags=flags)
    if not os.path.exists(pf):
        errs = [x for x in p.stdout.splitlines() if x.startswith('!') or 'Error' in x]
        return None, ("\n".join(errs[-10:]) or p.stdout[-800:])
    with open(pf, "rb") as f: return f.read(), None

def _rgb_near(fl, r, g, b):
    return abs(fl[0] - r) <= 2 and abs(fl[1] - g) <= 2 and abs(fl[2] - b) <= 2

def _basis(p0, px, py):
    xx, xy = px[0] - p0[0], px[1] - p0[1]
    yx, yy = py[0] - p0[0], py[1] - p0[1]
    if abs(xx * yy - yx * xy) <= 1: return None
    return {"ox": p0[0], "oy": p0[1], "xx": xx, "xy": xy, "yx": yx, "yy": yy}

def _to_tikz(cal, px, py):
    dx, dy = px - cal["ox"], py - cal["oy"]
    det = cal["xx"] * cal["yy"] - cal["yx"] * cal["xy"]
    x = (cal["yy"] * dx - cal["yx"] * dy) / det
    y = (-cal["xy"] * dx + cal["xx"] * dy) / det
    return round(x, 3), round(y, 3)

def extract_pos(pg):
    p0, p1, px, py, pm = None, None, None, None, {}
    for d in pg.get_drawings():
        fl = d.get("fill")
        if not fl or len(fl) < 3: continue
        rgb = [round(c * 255) for c in fl[:3]]; rc = d["rect"]
        cx, cy = (rc.x0 + rc.x1) / 2.0, (rc.y0 + rc.y1) / 2.0
        if _rgb_near(rgb, 254, 1, 253): p0 = (cx, cy)
        elif _rgb_near(rgb, 1, 254, 252): p1 = (cx, cy)
        elif _rgb_near(rgb, 254, 80, 1): px = (cx, cy)
        elif _rgb_near(rgb, 1, 80, 254): py = (cx, cy)
        elif abs(rgb[0] - 200) <= 2 and 10 <= rgb[1] <= 210 and 10 <= rgb[2] <= 210:
            pm[(rgb[1] - 10) * 200 + (rgb[2] - 10)] = (cx, cy)
    cal = _basis(p0, px, py) if p0 and px and py else None
    if not cal and p0 and p1:
        sx, sy = p1[0] - p0[0], p1[1] - p0[1]
        if abs(sx) > 1 and abs(sy) > 1:
            cal = {"ox": p0[0], "oy": p0[1], "xx": sx, "xy": 0.0, "yx": 0.0, "yy": sy}
    return cal, pm

@app.post("/api/dxf")
async def import_dxf(file: UploadFile = File(...), lang: str = Form("zh")):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        return {"ok": False, "err": "文件超过 20MB"}
    try:
        from .dxf_import import dxf_to_tikz
        code, note = dxf_to_tikz(data, file.filename or "drawing.dxf", "en" if lang == "en" else "zh")
    except Exception as ex:
        return {"ok": False, "err": str(ex) or "无法读取这个 DXF"}
    return {"ok": True, "code": code, "note": note}

@app.post("/api/compile")
def run_tex(req: Req):
    if req.pick:
        pts, probes, ports = parse_points(req.code)
    else:
        pts, probes, ports = [], [], []
    span = _cal_span(pts) if req.pick else 1.0
    pb, err = build_pdf(prep(req.code, probes if req.pick else None, with_cal=req.pick, cal_span=span), req.compiler)
    if err: return {"ok": False, "err": err}
    doc = pymupdf.open(stream=pb, filetype="pdf"); pg = next(iter(doc))
    svg, r = pg.get_svg_image(matrix=pymupdf.Identity), pg.rect
    if not req.pick:
        doc.close()
        return {"ok": True, "svg": svg, "w": r.width, "h": r.height, "coords": [], "ports": [], "cal": None}
    cal, pm = extract_pos(pg); doc.close()
    if cal and span != 1.0:
        for k in ("xx", "xy", "yx", "yy"):
            cal[k] /= span
    if cal:
        for pt in pts:
            if pt.get("pid", -1) == -1:
                if "wx" not in pt: pt["wx"] = pt["x"] + pt.get("sx", 0.0); pt["wy"] = pt["y"] + pt.get("sy", 0.0)
            elif pt["pid"] in pm:
                pt["wx"], pt["wy"] = _to_tikz(cal, *pm[pt["pid"]])
            elif pt.get("kind") in ("abs", "xyz"):
                # probe color missed — numeric TikZ coords still place the handle
                pt["wx"] = pt["x"] + pt.get("sx", 0.0)
                pt["wy"] = pt["y"] + pt.get("sy", 0.0)
            for key, pidk in (("c", "cpid"), ("b", "bpid")):
                if pt.get(pidk) in pm:
                    pt[key + "x"], pt[key + "y"] = _to_tikz(cal, *pm[pt[pidk]])
        for port in ports:
            if port["pid"] in pm:
                port["wx"], port["wy"] = _to_tikz(cal, *pm[port["pid"]])
    ports = [p for p in ports if "wx" in p]
    for p in ports: p.pop("pid", None)
    return {"ok": True, "svg": svg, "w": r.width, "h": r.height, "coords": pts, "ports": ports, "cal": cal}

def render_export(code, compiler, fmt):
    fmt = (fmt or "pdf").lower()
    names = {"pdf": "tikz.pdf", "png": "tikz_600dpi.png", "svg": "tikz.svg"}
    if fmt not in names:
        return None, "未知格式", ""
    pb, err = build_pdf(prep(code, None), compiler or "xelatex")
    if err:
        return None, err, ""
    if fmt == "pdf":
        return pb, None, names[fmt]
    doc = pymupdf.open(stream=pb, filetype="pdf")
    try:
        pg = next(iter(doc))
        data = pg.get_svg_image(matrix=pymupdf.Identity).encode("utf-8") if fmt == "svg" else pg.get_pixmap(dpi=600, alpha=False).tobytes("png")
    finally:
        doc.close()
    return data, None, names[fmt]

@app.post("/api/export")
def export_fig(req: Req):
    data, err, name = render_export(req.code, req.compiler, req.fmt)
    if err:
        return Response(content=err, status_code=400, media_type="text/plain")
    media = {"pdf": "application/pdf", "png": "image/png", "svg": "image/svg+xml"}[req.fmt.lower()]
    return Response(content=data, media_type=media, headers={"Content-Disposition": f"attachment; filename={name}"})

_FRESH = {"Cache-Control": "no-cache"}

@app.get("/api/editorconfig")
def editorconfig_api():
    return read_editorconfig()

@app.get("/{fn}")
def static_f(fn: str):
    if fn in ("style.css", "i18n.js", "data.js", "app.js"):
        return FileResponse(os.path.join(_WEB, fn), headers=_FRESH)

@app.get("/")
def home():
    ensure_editorconfig()
    return FileResponse(os.path.join(_WEB, "index.html"), headers=_FRESH)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765)
