"""Convert CAE 2D DXF (LoadXData VIS blocks) → satopdf TikZ fragment."""
from __future__ import annotations

import math
import re
from io import BytesIO
from pathlib import Path

import ezdxf
from ezdxf import recover


def _k(p, tol=1e-4):
    return (round(float(p[0]) / tol) * tol, round(float(p[1]) / tol) * tol)


def _read(data: bytes | None = None, path: str | Path | None = None):
    if path is not None:
        return ezdxf.readfile(str(path))
    try:
        return ezdxf.read(BytesIO(data))
    except Exception:
        doc, _ = recover.read(BytesIO(data or b""))
        return doc


def _parse_bc(txt: str):
    # BC[START]:GLOBAL[111111]  or  BC[END]:SLIDE[011000]
    m = re.search(r"(?:GLOBAL|MASK|PLANE|SLIDE|ROTAXIS)\[([01]{6})\]", txt or "", re.I)
    if m:
        return m.group(1)
    m = re.search(r"\[([01]{6})\]", txt or "")
    return m.group(1) if m else None


def _parse_q(txt: str):
    m = re.search(
        r"q\s*=\s*([-+0-9.eE]+)\s*(\S*)\s*\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)",
        txt or "",
    )
    if not m:
        return None
    return float(m.group(1)), (float(m.group(3)), float(m.group(4)), float(m.group(5)))


def _parse_F(txt: str):
    m = re.search(r"F\[[^\]]*\]\s*=\s*([-+0-9.eE]+)", txt or "")
    return float(m.group(1)) if m else None


def _parse_M(txt: str):
    m = re.search(r"M\[[^\]]*\]\s*=\s*([-+0-9.eE]+)", txt or "")
    return float(m.group(1)) if m else None


def _parse_K(txt: str):
    m = re.search(r"K\[[^\]]*\]\s*=", txt or "")
    return bool(m)


def _split_at_nodes(members, nodes):
    node_list = list(nodes)
    out = []
    for a, b in members:
        ax, ay = a
        bx, by = b
        ab = (bx - ax, by - ay)
        ab2 = ab[0] * ab[0] + ab[1] * ab[1]
        if ab2 < 1e-12:
            continue
        hits = []
        for p in node_list:
            if p in (a, b):
                continue
            ap = (p[0] - ax, p[1] - ay)
            cross = ab[0] * ap[1] - ab[1] * ap[0]
            if abs(cross) > 1e-2:
                continue
            t = (ab[0] * ap[0] + ab[1] * ap[1]) / ab2
            if 1e-6 < t < 1 - 1e-6:
                hits.append((t, p))
        hits.sort()
        chain = [a] + [p for _, p in hits] + [b]
        for i in range(len(chain) - 1):
            out.append((chain[i], chain[i + 1]))
    uniq, seen = [], set()
    for a, b in out:
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((a, b))
    return uniq


def _nearest(nodes, p):
    return min(nodes, key=lambda q: (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2)


def _unit_scale(span: float) -> str:
    # Keep drawings ~12–16 cm wide
    if span <= 1e-9:
        return "1cm"
    mm = 140.0 / span  # target ~140 mm
    if 0.05 <= mm <= 2.0:
        return f"{mm:.3g}mm"
    return "0.14mm"


def dxf_to_satopdf2d(
    data: bytes | None = None,
    *,
    path: str | Path | None = None,
    name: str = "drawing.dxf",
) -> tuple[str, str]:
    doc = _read(data, path)
    msp = doc.modelspace()
    src = Path(path).name if path else name

    nodes: dict[tuple, tuple] = {}
    raw_members: list[tuple] = []
    for e in msp:
        if e.dxftype() != "LINE":
            continue
        layer = (e.dxf.layer or "").upper()
        if layer.startswith("CAE_VIS") or layer.startswith("CAE_LOAD"):
            continue
        a, b = _k(e.dxf.start), _k(e.dxf.end)
        if a == b:
            continue
        nodes[a] = a
        nodes[b] = b
        raw_members.append((a, b))

    bcs: list[tuple] = []
    springs: list[tuple] = []
    qloads: list[dict] = []
    moments: list[tuple] = []
    forces: list[tuple] = []

    for e in msp:
        if e.dxftype() != "INSERT":
            continue
        layer = (e.dxf.layer or "").upper()
        origin = _k(e.dxf.insert)
        blk = doc.blocks.get(e.dxf.name)
        if blk is None:
            continue
        texts = []
        for be in blk:
            if be.dxftype() == "TEXT":
                texts.append(be.dxf.text or "")
            elif be.dxftype() == "MTEXT":
                texts.append(be.text or "")
        blob = "\n".join(texts)

        if "CAE_VIS_BC" in layer:
            if _parse_K(blob):
                springs.append(origin)
                nodes[origin] = origin
                continue
            mask = None
            for t in texts:
                mask = _parse_bc(t) or mask
            if mask:
                bcs.append((origin, mask))
                nodes[origin] = origin
            continue

        if "CAE_VIS_LOAD" not in layer:
            continue

        q = None
        for t in texts:
            q = _parse_q(t) or q
        if q:
            mag, direction = q
            circles = []
            for be in blk:
                if be.dxftype() == "CIRCLE":
                    c = be.dxf.center
                    circles.append(_k((origin[0] + c.x, origin[1] + c.y)))
            if len(circles) >= 2:
                a, b = circles[0], circles[-1]
            else:
                a = b = origin
            nodes[a] = a
            nodes[b] = b
            qloads.append({"a": a, "b": b, "mag": mag, "dir": direction})
            continue

        mval = None
        for t in texts:
            mval = _parse_M(t) or mval
        if mval is not None:
            moments.append((origin, mval))
            nodes[origin] = origin
            continue

        fval = None
        for t in texts:
            fval = _parse_F(t) or fval
        if fval is not None:
            forces.append((origin, fval))
            nodes[origin] = origin

    members = _split_at_nodes(raw_members, nodes.keys())
    ordered = sorted(nodes.keys(), key=lambda t: (t[0], t[1]))
    nid = {p: f"N{i}" for i, p in enumerate(ordered)}

    xs = [p[0] for p in ordered] or [0.0]
    ys = [p[1] for p in ordered] or [0.0]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    u = _unit_scale(span)

    L: list[str] = [
        f"% Auto-generated from {src}",
        f"\\begin{{tikzpicture}}[x={u},y={u}]",
        "  \\stpset{",
        "    support size=12mm,",
        "    hinge radius=1.5mm,",
        "    load color=red!75!black,",
        "    load label color=red!75!black",
        "  }",
    ]
    for p in ordered:
        L.append(f"  \\stpNode{{{nid[p]}}}{{{p[0]:.4f},{p[1]:.4f}}}")

    for a, b in members:
        L.append(f"  \\stpMember{{beam}}{{{nid[a]}}}{{{nid[b]}}}")

    for p, mask in bcs:
        name = nid[_nearest(ordered, p)]
        L.append(f"  \\stpSupportFromMask{{{mask}}}{{{name}}}  % BC [{mask}]")

    for p in springs:
        name = nid[_nearest(ordered, p)]
        L.append(f"  \\stpSupport{{{name}}}[type=spring, angle=0, label=$k$]")

    for ld in qloads:
        a = nid[_nearest(ordered, ld["a"])]
        b = nid[_nearest(ordered, ld["b"])]
        dx, dy, _dz = ld["dir"]
        lab = f"$q={ld['mag']:g}$"
        if abs(dx) < 1e-9 and dy < 0:
            L.append(f"  \\stpLineLoad{{global}}{{{a}}}{{{b}}}[0.85][0.85][0.12][{lab}]")
        else:
            L.append(
                f"  \\stpLineLoadCAE{{{a}}}{{{b}}}{{{dx:g},{dy:g}}}[{lab}]"
            )

    for p, mag in moments:
        name = nid[_nearest(ordered, p)]
        L.append(f"  \\stpLoad{{moment}}{{{name}}}[30][200][0][$M={mag:g}$]")

    for p, mag in forces:
        name = nid[_nearest(ordered, p)]
        L.append(f"  \\stpPointLoad{{{name}}}{{0,-1}}[$F={mag:g}$]")

    L.append("\\end{tikzpicture}")
    note = f"satopdf 2D: {len(ordered)} nodes, {len(members)} members"
    return "\n".join(L) + "\n", note


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else r"c:\Users\Bachelor\Desktop\frame.dxf"
    code, note = dxf_to_satopdf2d(path=src)
    print(note)
    print(code[:800])
