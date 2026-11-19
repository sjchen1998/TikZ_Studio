"""Convert CAE 3D DXF (LoadXData VIS blocks) → satopdf TikZ source."""
from __future__ import annotations

import math
import re
import sys
from io import BytesIO
from pathlib import Path

import ezdxf
from ezdxf import recover


def _k(p, tol=1e-6):
    return (
        round(float(p[0]) / tol) * tol,
        round(float(p[1]) / tol) * tol,
        round(float(p[2]) / tol) * tol,
    )


def _read(data: bytes | None = None, path: str | Path | None = None):
    if path is not None:
        return ezdxf.readfile(str(path))
    try:
        return ezdxf.read(BytesIO(data))
    except Exception:
        doc, _ = recover.read(BytesIO(data or b""))
        return doc


def _is_axis_aligned(a, b, tol=1e-6):
    dx, dy, dz = abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2])
    return sum(v > tol for v in (dx, dy, dz)) == 1


def _parse_bc_text(txt: str):
    m = re.search(r"GLOBAL\[([01]{6})\]", txt or "")
    return m.group(1) if m else None


def _parse_load_text(txt: str):
    m = re.search(
        r"q\s*=\s*([-+0-9.eE]+)\s*(\S*)\s*\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)",
        txt or "",
    )
    if not m:
        return None
    return (
        float(m.group(1)),
        (float(m.group(3)), float(m.group(4)), float(m.group(5))),
        (m.group(2) or "").strip(),
    )


def _mask_to_dirs(mask: str):
    """Return (ux,uy,uz,rx,ry,rz) flags 0|1 from GLOBAL[abcdef]."""
    bits = [(1 if (i < len(mask) and mask[i] == "1") else 0) for i in range(6)]
    return tuple(bits)


def _split_at_nodes(members, nodes):
    node_list = list(nodes)
    out = []
    for a, b in members:
        ax, ay, az = a
        bx, by, bz = b
        ab = (bx - ax, by - ay, bz - az)
        ab2 = sum(v * v for v in ab)
        hits = []
        if ab2 < 1e-12:
            continue
        for p in node_list:
            if p in (a, b):
                continue
            ap = (p[0] - ax, p[1] - ay, p[2] - az)
            cross = (
                ab[1] * ap[2] - ab[2] * ap[1],
                ab[2] * ap[0] - ab[0] * ap[2],
                ab[0] * ap[1] - ab[1] * ap[0],
            )
            if math.sqrt(sum(c * c for c in cross)) > 1e-3:
                continue
            t = sum(ab[i] * ap[i] for i in range(3)) / ab2
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


def dxf_to_satopdf3d(
    data: bytes | None = None,
    *,
    path: str | Path | None = None,
    name: str = "drawing.dxf",
    scale: float = 0.001,
    coords: tuple = (-25, 10, 1, 1.2),
    load_count: int = 6,
    load_shaft: float = 0.55,
    fragment: bool = True,
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
        nodes[a] = a
        nodes[b] = b
        raw_members.append((a, b))

    bcs: list[tuple] = []
    loads: list[dict] = []
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
        if "CAE_VIS_BC" in layer:
            mask = None
            for t in texts:
                mask = _parse_bc_text(t) or mask
            if not mask:
                # also accept BC[…]:MODE[mask]
                for t in texts:
                    m = re.search(r"\[([01]{6})\]", t or "")
                    if m:
                        mask = m.group(1)
                        break
            if mask:
                bcs.append((origin, mask))
                nodes[origin] = origin
        elif "CAE_VIS_LOAD" in layer:
            parsed = None
            for t in texts:
                parsed = _parse_load_text(t) or parsed
            ys = []
            for be in blk:
                if be.dxftype() == "LINE":
                    ys += [float(be.dxf.start.y), float(be.dxf.end.y)]
                elif be.dxftype() == "CIRCLE":
                    ys.append(float(be.dxf.center.y))
            y0, y1 = (min(ys), max(ys)) if ys else (0.0, 0.0)
            a = _k((origin[0], origin[1] + y0, origin[2]))
            b = _k((origin[0], origin[1] + y1, origin[2]))
            nodes[a] = a
            nodes[b] = b
            mag, direction, unit = parsed if parsed else (1.0, (0.0, 0.0, -1.0), "")
            loads.append(
                {
                    "a": a,
                    "b": b,
                    "mag": mag,
                    "dir": direction,
                    "label": f"$q={mag:g}$",
                }
            )

    members = _split_at_nodes(raw_members, nodes.keys())
    ordered = sorted(nodes.keys(), key=lambda t: (t[1], t[0], t[2]))
    if not ordered:
        raise ValueError("没有可转换的结构线段")
    nid = {p: f"N{i}" for i, p in enumerate(ordered)}

    ang_x, ang_y, dx, dy = coords
    L: list[str] = []
    if not fragment:
        L += [
            f"% Auto-generated from {src}",
            "\\documentclass[border=10pt]{standalone}",
            "\\usepackage{satopdf}",
            "\\begin{document}",
        ]
    else:
        L.append(f"% Auto-generated from {src}")
    L += [
        f"\\stpDsetCoords{{{ang_x}}}{{{ang_y}}}[{dx}][{dy}]",
        "\\stpDsetAxis{xyz}",
        f"\\renewcommand{{\\stpDscale}}{{{scale:g}}}",
        "\\renewcommand{\\stpDsupLen}{0.35}",
        "\\renewcommand{\\stpDhingeR}{0.9mm}",
        "\\renewcommand{\\stpDaxLen}{1.2}",
        "\\begin{tikzpicture}[stpDCoords]",
        "  \\stpset{load color=red!75!black, load label color=red!75!black}",
    ]
    for p in ordered:
        L.append(
            f"  \\stpDpoint{{{nid[p]}}}{{{p[0]:.4f}}}{{{p[1]:.4f}}}{{{p[2]:.4f}}}"
        )
    L.append(f"  \\stpDaxis{{{nid[ordered[0]]}}}")

    for a, b in members:
        if _is_axis_aligned(a, b):
            L.append(f"  \\stpDmember{{beam}}{{{nid[a]}}}{{{nid[b]}}}")
        else:
            L.append(f"  \\stpDmember{{truss}}{{{nid[a]}}}{{{nid[b]}}}[1][1]")

    for p, mask in bcs:
        nearest = min(ordered, key=lambda q: sum((q[i] - p[i]) ** 2 for i in range(3)))
        name = nid[nearest]
        ux, uy, uz, rx, ry, rz = _mask_to_dirs(mask)
        if ux or uy or uz or rx or ry or rz:
            L.append(
                f"  \\stpDsupport{{pin}}{{{name}}}"
                f"[{ux}][{uy}][{uz}][{rx}][{ry}][{rz}]"
                f"  % BC GLOBAL[{mask}]"
            )

    for ld in loads:
        a, b = ld["a"], ld["b"]
        dx, dy, dz = ld["dir"]
        L.append(
            f"  \\stpDlineload{{{nid[a]}}}{{{nid[b]}}}"
            f"[{dx:g},{dy:g},{dz:g}][{load_count}][{load_shaft:g}][{ld['label']}]"
        )

    corners = {
        _k((0, 0, 0)): ("A", "below left"),
        _k((800, 0, 0)): ("B", "below right"),
        _k((0, 6000, 0)): ("D", "above left"),
        _k((800, 6000, 0)): ("C", "above right"),
    }
    for xyz, (lab, pos) in corners.items():
        if xyz in nid:
            L.append(
                f"  \\node[stpLabel, {pos}=1.5mm] at ({nid[xyz]}) {{${lab}$}};"
            )

    L.append("\\end{tikzpicture}")
    if not fragment:
        L += ["\\end{document}", ""]
    note = f"satopdf 3D: {len(ordered)} nodes, {len(members)} members"
    return "\n".join(L) + "\n", note


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else r"c:\Users\Bachelor\Desktop\SA3D.dxf"
    root = Path(__file__).resolve().parents[1]
    dst = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else root / "texmf" / "tex" / "latex" / "local" / "satopdf-SA3D.tex"
    )
    tex, note = dxf_to_satopdf3d(path=src, fragment=False)
    dst.write_text(tex, encoding="utf-8")
    print("wrote", dst, note)
