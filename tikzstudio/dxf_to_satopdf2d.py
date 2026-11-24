"""Convert CAE 2D DXF (LoadXData VIS blocks) → satopdf TikZ fragment."""
from __future__ import annotations

import math
import re
from io import BytesIO
from pathlib import Path

import ezdxf
from ezdxf import recover

from .cae_beam_mesh import (
    collect_beam_segs_from_inserts,
    collect_beam_segs_from_msp,
    expand_dist_loads,
    mesh_beams,
)
from .cae_section_mass import (
    accumulate_from_dxf,
    emit_struct_info_tex,
    format_length_mm_tex as _fmt_len_mm,
)
from .cae_face_curves import (
    analytic_faces_from_entity,
    curve_loops_as_polylines,
    format_stp_analytic_face,
    loops_are_coplanar,
    transform_analytic_face,
)
from .dxf_import import iter_inserted_entities
from .cae_welds import emit_weld_tex_2d, parse_seam_welds, parse_spot_welds

# Shell faces only. Loose CIRCLE / LWPOLYLINE stay beams or geometry.
_SHELL_FACE_TYPES = (
    "REGION",
    "SURFACE",
    "EXTRUDEDSURFACE",
    "PLANESURFACE",
    "LOFTEDSURFACE",
    "REVOLVEDSURFACE",
    "SWEPTSURFACE",
    "NURBSSURFACE",
    "3DSOLID",
    "BODY",
    "3DFACE",
    "MESH",
)


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
    """SETPTLOAD VIS: F[START|END]=1000.0N → (mag, unit)."""
    m = re.search(
        r"F\[[^\]]*\]\s*=\s*([-+0-9.eE]+)\s*([A-Za-zµμ·\-]*)",
        txt or "",
    )
    if not m:
        return None
    return float(m.group(1)), (m.group(2) or "N").strip() or "N"


def _parse_M(txt: str):
    m = re.search(r"M\[[^\]]*\]\s*=\s*([-+0-9.eE]+)", txt or "")
    return float(m.group(1)) if m else None


def _dir_from_load_block_2d(blk) -> tuple[float, float]:
    """Longest LINE in VIS block: tail→tip = force direction (xy)."""
    best = None
    best_len2 = -1.0
    for be in blk:
        if be.dxftype() != "LINE":
            continue
        a, b = be.dxf.start, be.dxf.end
        d = (float(b.x - a.x), float(b.y - a.y))
        len2 = d[0] * d[0] + d[1] * d[1]
        if len2 > best_len2:
            best_len2 = len2
            best = d
    if best is None or best_len2 < 1e-18:
        return (0.0, -1.0)
    inv = 1.0 / math.sqrt(best_len2)
    return (best[0] * inv, best[1] * inv)


def _parse_K(txt: str):
    m = re.search(r"K\[[^\]]*\]\s*=", txt or "")
    return bool(m)


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


def _degree_map(members: list[tuple]) -> dict[tuple, list[tuple]]:
    """node → list of other endpoints of incident members."""
    adj: dict[tuple, list[tuple]] = {}
    for a, b in members:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    return adj


def _mask_to_kind(mask: str) -> str | None:
    """Map UXUYUZ RXRYRZ → satopdf support kind (before single/shared refine)."""
    bits = [(c == "1") for c in (mask or "").ljust(6, "0")[:6]]
    ux, uy, _uz, _rx, _ry, rz = bits
    if ux and uy and rz:
        return "fixed"
    if ux and uy:
        return "pin"
    if uy and not ux:
        return "roller"
    if ux and not uy:
        return "rollerX"
    if rz:
        return "slider"
    if ux or uy:
        return "fixed"
    return None


def _outward_angle(node: tuple, other: tuple) -> float:
    """Rotate so local -Y points away from the member along the beam axis.

    Wall/triangle hatch grows on local -Y; for a single-member end the glyph
    sits on the beam extension opposite the member body.
    """
    alpha = math.degrees(math.atan2(other[1] - node[1], other[0] - node[0]))
    return (alpha + 270.0) % 360.0


def _fmt_ang(ang: float) -> str:
    a = round(ang % 360.0, 1)
    if abs(a - round(a)) < 1e-6:
        return str(int(round(a)))
    return f"{a:g}"


def _emit_support(name: str, mask: str, node: tuple, adj: dict) -> str:
    """Shared joint → fixed/pin triangle; single-member end → wall (+ beam angle)."""
    kind = _mask_to_kind(mask)
    if kind is None:
        return f"  % skip BC [{mask}] at {name} (no 2D mapping)"
    others = adj.get(node, [])
    deg = len(others)
    if deg == 1 and kind == "fixed":
        # Single-member clamp: hatch wall on beam extension (away from member)
        ang = _outward_angle(node, others[0])
        return (
            f"  \\stpSupport{{{name}}}[type=wall, angle={_fmt_ang(ang)}, size=12mm]"
            f"  % single-member fixed [{mask}]"
        )
    if deg == 1 and kind in ("pin", "roller", "rollerX", "slider"):
        ang = _outward_angle(node, others[0])
        return (
            f"  \\stpSupport{{{name}}}[type={kind}, angle={_fmt_ang(ang)}, size=12mm]"
            f"  % single-member [{mask}]"
        )
    # Shared by ≥2 members (or floating BC): joint glyph, default ground angle
    if kind == "fixed":
        return (
            f"  \\stpSupport{{{name}}}[type=fixed, angle=0, size=12mm]"
            f"  % shared-node fixed [{mask}] deg={deg}"
        )
    return (
        f"  \\stpSupport{{{name}}}[type={kind}, angle=0, size=12mm]"
        f"  % shared-node [{mask}] deg={deg}"
    )


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
    beam_segs = collect_beam_segs_from_msp(msp, dim=2)
    beam_segs.extend(collect_beam_segs_from_inserts(doc, msp, dim=2))
    for s in beam_segs:
        nodes[s.a] = s.a
        nodes[s.b] = s.b

    # REGION is filled as-is. Other shell faces are filled the same way only
    # when the boundary curves (not sample points) lie in one plane.
    face_lines: list[str] = []
    face_xy: list[tuple[float, float]] = []
    n_faces = 0
    def _take_face(e, xform=None):
        nonlocal n_faces
        layer = (e.dxf.layer or "").upper()
        if layer.startswith("CAE_VIS") or layer.startswith("CAE_LOAD"):
            return
        if e.dxftype() not in _SHELL_FACE_TYPES:
            return
        for af in analytic_faces_from_entity(e) or []:
            if xform is not None:
                af = transform_analytic_face(af, xform)
            loops = af.get("loops") or []
            if af.get("kind") != "region" and not loops_are_coplanar(loops):
                continue
            face_lines.extend(format_stp_analytic_face(af))
            n_faces += 1
            for poly in curve_loops_as_polylines(loops, n=16):
                for p in poly:
                    face_xy.append((float(p[0]), float(p[1])))

    for e in msp:
        _take_face(e)
    for e, xform in iter_inserted_entities(doc, msp):
        _take_face(e, xform)

    # Beam XDATA → vis-handle map for SETPTLOAD direction
    ptload_by_vis: dict[str, tuple[float, tuple[float, float], str]] = {}
    for e in msp.query("LINE"):
        try:
            tags = e.get_xdata("MY_CAE_POINT_LOAD")
        except Exception:
            continue
        if not tags:
            continue
        vals = []
        for t in tags:
            code = getattr(t, "code", None)
            val = getattr(t, "value", t)
            if code is None and isinstance(t, (tuple, list)) and len(t) >= 2:
                code, val = t[0], t[1]
            vals.append((code, val))
        i = 0
        while i + 4 <= len(vals):
            c0, end_tag = vals[i]
            c1, mag = vals[i + 1] if i + 1 < len(vals) else (None, None)
            c2, dvec = vals[i + 2] if i + 2 < len(vals) else (None, None)
            c3, vis_h = vals[i + 3] if i + 3 < len(vals) else (None, None)
            unit = "N"
            if i + 4 < len(vals) and vals[i + 4][0] == 1000:
                unit = str(vals[i + 4][1] or "N")
                step = 5
            else:
                step = 4
            if (
                c0 == 1000
                and c1 == 1040
                and c2 == 1013
                and c3 == 1005
                and isinstance(end_tag, str)
                and end_tag.upper() in ("START", "END")
            ):
                direction = (float(dvec[0]), float(dvec[1]))
                ptload_by_vis[str(vis_h).upper()] = (float(mag), direction, unit)
            i += step

    bcs: list[tuple] = []
    springs: list[tuple] = []
    qloads: list[dict] = []
    moments: list[tuple] = []
    forces: list[dict] = []

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

        f_parsed = None
        for t in texts:
            f_parsed = _parse_F(t) or f_parsed
        if f_parsed is not None:
            mag, unit = f_parsed
            direction = None
            vis_key = str(e.dxf.handle).upper()
            if vis_key in ptload_by_vis:
                _m, direction, unit_xd = ptload_by_vis[vis_key]
                if unit_xd:
                    unit = unit_xd
            if direction is None:
                direction = _dir_from_load_block_2d(blk)
            # Degenerate in-plane direction (pure ±z load) → default downward
            if abs(direction[0]) < 1e-12 and abs(direction[1]) < 1e-12:
                direction = (0.0, -1.0)
            nodes[origin] = origin
            forces.append(
                {"p": origin, "mag": mag, "dir": direction, "unit": unit}
            )

    # Welds — snap onto beams, then split at welds + beam intersections
    def _k2(p):
        return _k((p[0], p[1]))

    spot_welds = parse_spot_welds(msp, _k2)
    seam_welds = parse_seam_welds(msp, _k2)
    weld_pts = [sw["xyz"] for sw in spot_welds]
    for sm in seam_welds:
        weld_pts.extend(sm["pts"])

    # VIS BC / load / spring origins also force a split when they lie on a beam
    extra_cuts = list(weld_pts)
    for p, _mask in bcs:
        extra_cuts.append(p)
    for p in springs:
        extra_cuts.append(p)
    for pl in forces:
        extra_cuts.append(pl["p"])
    for p, _m in moments:
        extra_cuts.append(p)

    mesh_nodes, meshed = mesh_beams(
        beam_segs, extra_cuts, tol=1e-2, key_tol=1e-4, dim=2
    )
    nodes.update(mesh_nodes)
    # Snap weld dict coords to meshed node keys (projection may shift slightly)
    for sw in spot_welds:
        sw["xyz"] = _nearest(nodes.keys(), sw["xyz"]) if nodes else sw["xyz"]
        nodes[sw["xyz"]] = sw["xyz"]
    for sm in seam_welds:
        sm["pts"] = [
            _nearest(nodes.keys(), p) if nodes else p for p in sm["pts"]
        ]
        for p in sm["pts"]:
            nodes[p] = p

    members = [(s.a, s.b) for s in meshed]
    # Preserve attrs on meshed segs for CAE / comments
    member_attrs = {(s.a, s.b): s.attrs for s in meshed}
    # q span rebound to each child: (0,0)-(1000,1000) @P → (0,0)-P and P-(1000,1000)
    qloads = expand_dist_loads(meshed, qloads, tol=1e-2)
    ordered = sorted(nodes.keys(), key=lambda t: (t[0], t[1]))
    nid = {p: f"N{i}" for i, p in enumerate(ordered)}

    xs = [p[0] for p in ordered]
    ys = [p[1] for p in ordered]
    if face_xy:
        xs.extend(p[0] for p in face_xy)
        ys.extend(p[1] for p in face_xy)
    if not xs:
        xs, ys = [0.0], [0.0]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    u = _unit_scale(span)

    L: list[str] = [
        f"% Auto-generated from {src}",
        f"\\begin{{tikzpicture}}[x={u},y={u},stpScheme=color]",
        "  \\stpset{support size=12mm, hinge radius=1.5mm}",
    ]
    for p in ordered:
        L.append(f"  \\stpNode{{{nid[p]}}}{{{p[0]:.4f},{p[1]:.4f}}}")

    for a, b in members:
        attr = member_attrs.get((a, b))
        kind = "rod" if (attr and attr.is_rod) else "beam"
        notes: list[str] = []
        if attr and attr.section:
            notes.append(
                f"sec={attr.section.get('type')}"
                f" {attr.section.get('spec')}"
                f" {attr.section.get('material')}"
            )
            if attr.dist_load and not attr.is_rod:
                notes.append(f"q={attr.dist_load.get('magnitude')}")
        if kind == "rod":
            notes.append("kind=rod")
        sec_note = f"  % {' '.join(notes)}" if notes else ""
        L.append(f"  \\stpMember{{{kind}}}{{{nid[a]}}}{{{nid[b]}}}{sec_note}")

    # Coplanar shells / REGION: same even-odd fill as the 3D importer.
    L.extend(face_lines)

    # Welds after members (above geometry, before BC/loads)
    L.extend(emit_weld_tex_2d(spot_welds, seam_welds, nid))

    adj = _degree_map(members)
    for p, mask in bcs:
        node = _nearest(ordered, p)
        name = nid[node]
        L.append(_emit_support(name, mask, node, adj))

    for p in springs:
        node = _nearest(ordered, p)
        name = nid[node]
        others = adj.get(node, [])
        ang = _outward_angle(node, others[0]) if len(others) == 1 else 0.0
        L.append(
            f"  \\stpSupport{{{name}}}[type=spring, angle={_fmt_ang(ang)}, label=$k$]"
        )

    for ld in qloads:
        a = nid[_nearest(ordered, ld["start"])]
        b = nid[_nearest(ordered, ld["end"])]
        direction = ld["direction"]
        dx = float(direction[0]) if len(direction) > 0 else 0.0
        dy = float(direction[1]) if len(direction) > 1 else -1.0
        lab = f"$q={ld['magnitude']:g}$"
        # Nominal spacing ~1/6 of span → 7 uniformly spaced arrows (incl. ends)
        if abs(dx) < 1e-9 and dy < 0:
            L.append(
                f"  \\stpLineLoad{{global}}{{{a}}}{{{b}}}[0.85][0.85][0.1667][{lab}]"
            )
        else:
            L.append(
                f"  \\stpLineLoadCAE{{{a}}}{{{b}}}{{{dx:g},{dy:g}}}[{lab}][7]"
            )

    for p, mag in moments:
        name = nid[_nearest(ordered, p)]
        L.append(f"  \\stpLoad{{moment}}{{{name}}}[30][200][0][$M={mag:g}$]")

    for pl in forces:
        name = nid[_nearest(ordered, pl["p"])]
        dx, dy = pl["dir"]
        unit = re.sub(r"[^A-Za-z0-9_\-./]", "", pl.get("unit") or "N") or "N"
        L.append(
            f"  \\stpPointLoad{{{name}}}{{{dx:g},{dy:g}}}"
            f"[$F={pl['mag']:g}\\,\\mathrm{{{unit}}}$]"
        )

    # Overall envelope dims — per-axis offset via (Δ), default \stpDimOff
    #   \stpDimX{SW}{SE}[$L_x$]          \stpDimX{SW}{SE}(0.4cm)[$L_x$]
    #   \stpDimY{SW}{NW}[$L_y$]          \stpDimY{SW}{NW}(0.5cm)[$L_y$]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    lx, ly = xmax - xmin, ymax - ymin
    if lx > 1e-6 or ly > 1e-6:
        L.append(f"  \\stpNode{{DimSW}}{{{xmin:.4f},{ymin:.4f}}}")
        L.append(f"  \\stpNode{{DimSE}}{{{xmax:.4f},{ymin:.4f}}}")
        L.append(f"  \\stpNode{{DimNW}}{{{xmin:.4f},{ymax:.4f}}}")
        if lx > 1e-6:
            L.append(
                f"  \\stpDimX{{DimSW}}{{DimSE}}[$L_x={_fmt_len_mm(lx)}$]"
            )
        if ly > 1e-6:
            L.append(
                f"  \\stpDimY{{DimSW}}{{DimNW}}[$L_y={_fmt_len_mm(ly)}$]"
            )

    mass_info = accumulate_from_dxf(doc)
    if mass_info["volume_mm3"] > 0:
        L.append(emit_struct_info_tex(mass_info["volume_mm3"], mass_info["mass_kg"]))

    L.append("\\end{tikzpicture}")
    note = (
        f"satopdf 2D: {len(ordered)} nodes, {len(members)} members, "
        f"{n_faces} planar faces, "
        f"{len(forces)} point loads, spots={len(spot_welds)}, seams={len(seam_welds)}"
        f"; V={mass_info['volume_mm3']:.3g} mm3, m={mass_info['mass_kg']:.3g} kg"
        f" (beams={mass_info['n_beam']}, shells={mass_info['n_shell']})"
    )
    return "\n".join(L) + "\n", note


if __name__ == "__main__":
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else r"c:\Users\Bachelor\Desktop\frame.dxf"
    code, note = dxf_to_satopdf2d(path=src)
    print(note)
    print(code[:800])
