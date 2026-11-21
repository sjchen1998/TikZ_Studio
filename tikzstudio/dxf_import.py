import math
import os
import re
from collections import Counter
from io import BytesIO

import ezdxf
from ezdxf import recover
from ezdxf.colors import aci2rgb
from ezdxf.path import Command, from_hatch, make_path

# DXF $INSUNITS → 厘米。TikZ 默认单位就是厘米。
# 0 = 未标明：按 AutoCAD 常用习惯当作毫米。
_TO_CM = {
    0: 0.1, 1: 2.54, 2: 30.48, 3: 160934.4, 4: 0.1, 5: 1.0, 6: 100.0, 7: 100000.0,
    8: 2.54e-6, 9: 0.00254, 10: 91.44, 13: 1e-4, 14: 10.0, 15: 1000.0, 16: 10000.0,
}
_UNIT_NAME = {
    0: "未标明单位，数值按毫米",
    1: "英寸", 2: "英尺", 3: "英里", 4: "毫米", 5: "厘米", 6: "米", 7: "千米",
    10: "码", 14: "分米",
}
_NAMED = {1: "red", 2: "yellow", 3: "green", 4: "cyan", 5: "blue", 6: "magenta", 7: "black"}
_MAX = 80000
# ISO A0（cm）。超出时按工程制图常用比例缩小，取能装下的最大比例。
_A0 = (84.1, 118.9)
_SCALE_N = (1, 2, 4, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)


def _sheet_scale(span_x, span_y):
    """Return (sc, N) for drawing scale 1:N. Prefer largest scale that fits A0."""
    sx = max(float(span_x), 1e-9)
    sy = max(float(span_y), 1e-9)
    aw, ah = _A0
    for n in _SCALE_N:
        sc = 1.0 / n
        w, h = sx * sc, sy * sc
        if (w <= aw + 1e-9 and h <= ah + 1e-9) or (w <= ah + 1e-9 and h <= aw + 1e-9):
            return sc, n
    n = _SCALE_N[-1]
    return 1.0 / n, n


def _is_cae_vis_layer(layer: str) -> bool:
    u = (layer or "").upper()
    return u.startswith("CAE_VIS") or u.startswith("CAE_LOAD_VIS") or u == "CAE_LOAD_VIS"


_SHELL_TYPES = ("REGION", "SURFACE", "3DSOLID", "3DFACE", "MESH")


def sniff_dxf_import_mode(data: bytes) -> str | None:
    """Suggest satopdf mode for shell / CAE DXFs; None → keep plain geometry import.

    REGION / SURFACE / 3DFACE / MESH → struct3d (equation faces via satopdf).
    CAE_VIS_* / MY_CAE_* without shells → struct2d, or struct3d if Z span is large.
    """
    if not data:
        return None
    try:
        doc = _read(data)
    except Exception:
        return None
    msp = doc.modelspace()
    kinds: Counter[str] = Counter()
    has_cae_layer = False
    has_cae_xdata = False
    zmin = zmax = None
    for e in msp:
        kinds[e.dxftype()] += 1
        layer = (e.dxf.layer or "").upper()
        if layer.startswith("CAE_"):
            has_cae_layer = True
        try:
            xd = e.xdata
            if xd is not None:
                for app in xd.keys():
                    if str(app).upper().startswith("MY_CAE"):
                        has_cae_xdata = True
                        break
        except Exception:
            pass
        if e.dxftype() == "LINE":
            for z in (float(e.dxf.start.z), float(e.dxf.end.z)):
                zmin = z if zmin is None else min(zmin, z)
                zmax = z if zmax is None else max(zmax, z)

    shell_n = sum(kinds[t] for t in _SHELL_TYPES)
    if shell_n > 0:
        return "struct3d"
    if has_cae_layer or has_cae_xdata:
        if zmin is not None and zmax is not None and (zmax - zmin) > 1.0:
            return "struct3d"
        return "struct2d"
    return None


def dxf_to_tikz(data: bytes, name: str = "drawing.dxf", lang: str = "zh", *, skip_cae: bool = True):
    """Geometry import (line / arc / spline / …). skip_cae drops CAE_VIS_* BC/load blocks."""
    if not data:
        raise ValueError("文件是空的")
    doc = _read(data)
    ins = int(doc.header.get("$INSUNITS", 0) or 0)
    unit = _TO_CM.get(ins, 0.1)
    items, skipped, truncated = [], {}, False
    skipped_cae = 0
    for e in _walk(doc.modelspace(), skip_cae=skip_cae):
        if len(items) >= _MAX:
            truncated = True
            break
        if e.dxf.hasattr("invisible") and e.dxf.invisible:
            continue
        layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
        if skip_cae and _is_cae_vis_layer(layer):
            skipped_cae += 1
            continue
        kind = e.dxftype()
        try:
            got = _convert(e, doc, unit)
        except Exception:
            got = None
        if got:
            items.append(got)
        elif kind not in ("INSERT",):
            skipped[kind] = skipped.get(kind, 0) + 1
    if not items:
        raise ValueError("没有可转换的直线、圆、弧、样条或文字")
    code, note = _emit(items, skipped, truncated, ins, _safe_name(name), "en" if lang == "en" else "zh")
    if skipped_cae:
        if lang == "en":
            note += f"; skipped {skipped_cae} CAE VIS entities"
        else:
            note += f"；已跳过 {skipped_cae} 个载荷/约束图元"
    return code, note


def _read(data):
    try:
        return ezdxf.read(BytesIO(data))
    except Exception:
        try:
            doc, _auditor = recover.read(BytesIO(data))
            return doc
        except Exception as ex:
            raise ValueError("无法读取这个 DXF") from ex


def _walk(entities, depth=0, skip_cae=True):
    for e in entities:
        layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
        if skip_cae and _is_cae_vis_layer(layer):
            # Do not explode CAE VIS inserts into decorative lines/circles/text
            continue
        if e.dxftype() == "INSERT" and depth < 6:
            try:
                yield from _walk(e.virtual_entities(), depth + 1, skip_cae=skip_cae)
                continue
            except Exception:
                pass
        yield e


def _convert(e, doc, unit):
    kind = e.dxftype()
    color = _color(e, doc)
    layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
    if kind in ("TEXT", "ATTRIB", "ATTDEF"):
        return _text_item(e, color, layer, unit, mtext=False)
    if kind == "MTEXT":
        return _text_item(e, color, layer, unit, mtext=True)
    if kind == "POINT":
        return ("point", color, layer, _xyz(e.dxf.location, unit))
    if kind == "LINE":
        a, b = _xyz(e.dxf.start, unit), _xyz(e.dxf.end, unit)
        if _near(a, b):
            return None
        return ("line", color, layer, a, b)
    if kind in ("CIRCLE", "ARC") and _z_up(e):
        c = _xyz(e.dxf.center, unit)
        r = float(e.dxf.radius) * unit
        if r <= 1e-9:
            return None
        a0 = 0.0 if kind == "CIRCLE" else float(e.dxf.start_angle)
        a1 = 360.0 if kind == "CIRCLE" else float(e.dxf.end_angle)
        if a1 <= a0:
            a1 += 360.0
        return ("arc", color, layer, c, r, a0, a1)
    if kind == "HATCH":
        subs = []
        for path in from_hatch(e):
            subs.extend(_capture(path, unit))
        return ("path", color, layer, subs) if subs else None
    subs = _capture(make_path(e), unit)
    return ("path", color, layer, subs) if subs else None


def _text_item(e, color, layer, unit, mtext):
    if mtext:
        raw = e.plain_text()
        p = e.dxf.insert
        height = float(e.dxf.char_height) if e.dxf.hasattr("char_height") else 0.0
        attach = int(e.dxf.attachment_point) if e.dxf.hasattr("attachment_point") else 1
        anchor = {1: "north west", 2: "north", 3: "north east", 4: "west", 5: "center",
                  6: "east", 7: "south west", 8: "south", 9: "south east"}.get(attach, "north west")
    else:
        raw = e.dxf.text if e.dxf.hasattr("text") else ""
        h = int(e.dxf.halign) if e.dxf.hasattr("halign") else 0
        v = int(e.dxf.valign) if e.dxf.hasattr("valign") else 0
        p = e.dxf.align_point if (h or v) and e.dxf.hasattr("align_point") else e.dxf.insert
        height = float(e.dxf.height) if e.dxf.hasattr("height") else 0.0
        anchor = _text_anchor(h, v)
    text = _plain(raw)
    if not text.strip():
        return None
    rot = float(e.dxf.rotation) if e.dxf.hasattr("rotation") else 0.0
    return ("text", color, layer, _xyz(p, unit), text, height * unit, rot, anchor)


def _text_anchor(h, v):
    if h == 4 or (h == 1 and v == 2):
        return "center"
    hs = {0: "west", 1: "", 2: "east", 5: "west"}.get(h, "")
    vs = {0: "base", 1: "south", 2: "mid", 3: "north"}.get(v, "base")
    return (vs + " " + hs).strip() or "base west"


def _capture(path, unit):
    subs = list(path.sub_paths()) if path.has_sub_paths else [path]
    out = []
    for sub in subs:
        cmds, cur = [], _xyz(sub.start, unit)
        for c in sub:
            if c.type == Command.LINE_TO:
                end = _xyz(c.end, unit)
                cmds.append(("L", end))
                cur = end
            elif c.type == Command.CURVE4_TO:
                end = _xyz(c.end, unit)
                cmds.append(("C", _xyz(c.ctrl1, unit), _xyz(c.ctrl2, unit), end))
                cur = end
            elif c.type == Command.CURVE3_TO:
                end = _xyz(c.end, unit)
                c1, c2 = _quad(cur, _xyz(c.ctrl, unit), end)
                cmds.append(("C", c1, c2, end))
                cur = end
        if cmds:
            out.append((_xyz(sub.start, unit), cmds, bool(sub.is_closed)))
    return out


def _quad(p0, ctrl, p1):
    def mix(a, b):
        return tuple(a[i] + (2.0 / 3.0) * (b[i] - a[i]) for i in range(3))
    return mix(p0, ctrl), mix(p1, ctrl)


def _emit(items, skipped, truncated, ins, name, lang="zh"):
    pts = []
    for it in items:
        pts.extend(_item_points(it))
    if not pts:
        raise ValueError("没有可转换的直线、圆、弧或文字")
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    minz = min(p[2] for p in pts)
    span_x = max(p[0] for p in pts) - minx
    span_y = max(p[1] for p in pts) - miny
    span = max(span_x, span_y, 1e-9)
    sc, scale_n = _sheet_scale(span_x, span_y)
    zspan = (max(p[2] for p in pts) - minz) * sc
    zmode = zspan > 0.02

    def T(p):
        return ((p[0] - minx) * sc, (p[1] - miny) * sc, (p[2] - minz) * sc)

    note = _note(ins, minx, miny, minz, span, sc, scale_n, lang)
    if lang == "en":
        lines = ["% imported from " + name, "% " + note]
        if truncated:
            lines.append("% many entities; only the first " + str(_MAX) + " were converted")
        if skipped:
            lines.append("% not converted: " + ", ".join(k + " " + str(v) for k, v in sorted(skipped.items())))
    else:
        lines = ["% 从 " + name + " 导入", "% " + note]
        if truncated:
            lines.append("% 图元很多，只转换了前 " + str(_MAX) + " 个")
        if skipped:
            lines.append("% 未转换：" + "、".join(k + " " + str(v) + " 个" for k, v in sorted(skipped.items())))
    lines.append("\\begin{tikzpicture}[line cap=round,line join=round]")
    layer = None
    for it in items:
        if it[2] != layer:
            layer = it[2]
            if layer and layer != "0":
                lines.append(("% layer " if lang == "en" else "% 图层 ") + layer.replace("%", ""))
        row = _emit_item(it, T, sc, zmode)
        if row:
            lines.append(row)
    lines.append("\\end{tikzpicture}")
    counts = _counts(items, lang)
    summary = ("Imported " + ", ".join(counts)) if lang == "en" else ("已导入 " + "、".join(counts))
    return "\n".join(lines) + "\n", summary


def _emit_item(it, T, sc, zmode):
    kind, color = it[0], it[1]
    opt = "[" + color + "]" if color and color != "black" else ""
    if kind == "line":
        return "\\draw" + opt + " " + _xy(T(it[3]), zmode) + " -- " + _xy(T(it[4]), zmode) + ";"
    if kind == "arc":
        c, r, a0, a1 = T(it[3]), it[4] * sc, it[5], it[6]
        if r < 5e-4:
            return None
        rad = math.radians(a0)
        start = (c[0] + r * math.cos(rad), c[1] + r * math.sin(rad), c[2])
        return "\\draw" + opt + " " + _xy(start, zmode) + " arc (" + _af(a0) + ":" + _af(a1) + ":" + _f(r) + ");"
    if kind == "point":
        return "\\fill" + opt + " " + _xy(T(it[3]), zmode) + " circle (1.2pt);"
    if kind == "text":
        return _emit_text(it, T, sc, zmode, opt)
    parts = []
    for start, cmds, closed in it[3]:
        seg = _emit_sub(T(start), [(c[0],) + tuple(T(p) for p in c[1:]) for c in cmds], closed, zmode)
        if seg:
            parts.append(seg)
    if not parts:
        return None
    return "\\draw" + opt + " " + " ".join(parts) + ";"


def _emit_sub(start, cmds, closed, zmode):
    cur, segs = start, []
    for c in cmds:
        if c[0] == "L":
            segs.append(("L", c[1]))
            cur = c[1]
        else:
            segs.append(("C", c[1], c[2], c[3]))
            cur = c[3]
    cycle = False
    if closed and segs and segs[-1][0] == "L" and _near(segs[-1][1], start):
        segs.pop()
        cycle = True
    elif closed and not _near(cur, start):
        cycle = True
    if not segs and not cycle:
        return None
    body = _xy(start, zmode)
    for s in segs:
        if s[0] == "L":
            body += " -- " + _xy(s[1], zmode)
        else:
            body += " .. controls " + _xy(s[1], zmode) + " and " + _xy(s[2], zmode) + " .. " + _xy(s[3], zmode)
    if cycle:
        body += " -- cycle"
    return body


def _emit_text(it, T, sc, zmode, opt):
    p, text, height, rot, anchor = T(it[3]), it[4], it[5] * sc, it[6], it[7]
    opts = ["anchor=" + anchor, "inner sep=1pt"]
    if "\n" in text:
        opts.append("align=left")
    pt = height * 28.4527
    if pt >= 2:
        opts.append("font=\\fontsize{" + _f(pt) + "}{" + _f(pt * 1.2) + "}\\selectfont")
    if abs(rot) > 0.05:
        opts.append("rotate=" + _af(rot))
    if opt:
        opts.append(opt[1:-1])
    shown = _tex(text).replace("\n", "\\\\")
    return "\\node[" + ",".join(opts) + "] at " + _xy(p, zmode) + " {" + shown + "};"


def _item_points(it):
    kind = it[0]
    if kind == "line":
        return [it[3], it[4]]
    if kind == "point":
        return [it[3]]
    if kind in ("text",):
        return [it[3]]
    if kind == "arc":
        c, r, a0, a1 = it[3], it[4], it[5], it[6]
        n = max(4, int(abs(a1 - a0) / 15) + 1)
        pts = []
        for i in range(n + 1):
            a = math.radians(a0 + (a1 - a0) * i / n)
            pts.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a), c[2]))
        return pts
    pts = []
    for start, cmds, _closed in it[3]:
        pts.append(start)
        for c in cmds:
            pts.extend(c[1:])
    return pts


def _counts(items, lang="zh"):
    n = {"line": 0, "arc": 0, "path": 0, "text": 0, "point": 0}
    for it in items:
        n[it[0]] = n.get(it[0], 0) + 1
    label = {"line": " lines", "arc": " arcs or circles", "path": " curves", "text": " text items", "point": " points"} if lang == "en" else {"line": "条线", "arc": "段圆或弧", "path": "条曲线", "text": "处文字", "point": "个点"}
    return [str(n[k]) + label[k] for k in ("line", "arc", "path", "text", "point") if n[k]]


_UNIT_EN = {
    0: "unit not set, numbers treated as millimeters",
    1: "inches", 2: "feet", 3: "miles", 4: "millimeters", 5: "centimeters", 6: "meters", 7: "kilometers",
    10: "yards", 14: "decimeters",
}


def _note(ins, minx, miny, minz, span, sc, scale_n, lang="zh"):
    moved = abs(minx) > 1e-4 or abs(miny) > 1e-4 or abs(minz) > 1e-4
    if lang == "en":
        parts = ["Unit: " + _UNIT_EN.get(ins, "another unit")]
        if moved:
            parts.append("lower-left moved to the origin")
        if scale_n == 1:
            parts.append("drawing scale 1:1, fits on A0")
        else:
            parts.append(
                "drawing scale 1:" + str(scale_n)
                + " (longest side " + _f(span) + " cm → " + _f(span * sc) + " cm on A0)"
            )
        return ". ".join(parts) + "."
    parts = ["单位：" + _UNIT_NAME.get(ins, "其他单位")]
    if moved:
        parts.append("左下角已移到原点")
    if scale_n == 1:
        parts.append("出图比例 1:1，可放入 A0")
    else:
        parts.append(
            "出图比例 1:" + str(scale_n)
            + "（最大边 " + _f(span) + " cm → " + _f(span * sc) + " cm，按 A0 取能装下的最大比例）"
        )
    return "。".join(parts) + "。"


def _color(e, doc):
    if e.dxf.hasattr("true_color"):
        return _rgb(int(e.dxf.true_color) & 0xFFFFFF)
    c = int(e.dxf.color) if e.dxf.hasattr("color") else 256
    if c in (0, 256):
        try:
            c = int(doc.layers.get(e.dxf.layer).dxf.color)
        except Exception:
            c = 7
    if c in _NAMED:
        return _NAMED[c]
    try:
        rgb = aci2rgb(c)
    except Exception:
        return "black"
    return _rgb((int(rgb.r) << 16) | (int(rgb.g) << 8) | int(rgb.b))


def _rgb(tc):
    r, g, b = (tc >> 16) & 255, (tc >> 8) & 255, tc & 255
    if r > 245 and g > 245 and b > 245:
        return "black"
    if r < 8 and g < 8 and b < 8:
        return "black"
    return "{rgb,255:red," + str(r) + ";green," + str(g) + ";blue," + str(b) + "}"


def _z_up(e):
    if not e.dxf.hasattr("extrusion"):
        return True
    v = e.dxf.extrusion
    return abs(v.x) < 1e-8 and abs(v.y) < 1e-8 and v.z > 0.9


def _xyz(v, unit):
    z = float(v[2]) if len(v) > 2 else 0.0
    return (float(v[0]) * unit, float(v[1]) * unit, z * unit)


def _near(a, b):
    return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6 and abs(a[2] - b[2]) < 1e-6


def _xy(p, zmode):
    if zmode:
        return "(" + _f(p[0]) + "," + _f(p[1]) + "," + _f(p[2]) + ")"
    return "(" + _f(p[0]) + "," + _f(p[1]) + ")"


def _f(v):
    v = round(float(v), 3)
    if abs(v) < 5e-4:
        return "0"
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _af(v):
    v = round(float(v), 2)
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _plain(s):
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s or "")
    return s.replace("%%c", "⌀").replace("%%d", "°").replace("%%p", "±").replace("\r", "")


def _tex(s):
    s = s.replace("\\", "\\textbackslash{}")
    for ch, rep in (("&", "\\&"), ("%", "\\%"), ("$", "\\$"), ("#", "\\#"),
                    ("_", "\\_"), ("{", "\\{"), ("}", "\\}"), ("~", "\\textasciitilde{}"),
                    ("^", "\\textasciicircum{}")):
        s = s.replace(ch, rep)
    return s


def _safe_name(name):
    base = os.path.basename(name or "drawing.dxf").replace("%", "").replace("\n", " ").strip()
    return base or "drawing.dxf"
