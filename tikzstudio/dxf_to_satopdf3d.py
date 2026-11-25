"""Convert CAE 3D DXF (LoadXData VIS blocks) → satopdf TikZ source."""
from __future__ import annotations

import math
import re
import sys
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
    EdgeLine,
    analytic_faces_from_entity,
    curve_loops_as_polylines,
    cylinder_extent_pts,
    face_curve_loops_from_entity,
    _edge_samples,
    _emit_edge_tex,
    format_stp_analytic_face,
    revolve_extent_pts,
    transform_analytic_face,
)
from .cae_welds import emit_weld_tex_3d, parse_seam_welds, parse_spot_welds
from .dxf_import import _A0, _SCALE_N, _TO_CM, _sheet_scale, iter_inserted_entities


def _k(p, tol=1e-6):
    return (
        round(float(p[0]) / tol) * tol,
        round(float(p[1]) / tol) * tol,
        round(float(p[2]) / tol) * tol,
    )


def _dist3(a, b) -> float:
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))


def _dxf_surface_isoline_counts(e) -> tuple[int | None, int | None]:
    """AutoCAD SURFACE / SWEPTSURFACE / … U/V isoline density (dxf.u_count/v_count)."""
    try:
        u = int(getattr(e.dxf, "u_count", 0) or 0)
        v = int(getattr(e.dxf, "v_count", 0) or 0)
    except Exception:
        return None, None
    if u <= 0 and v <= 0:
        return None, None

    def _clamp(n: int) -> int:
        return max(2, min(int(n), 24))

    return (_clamp(u) if u > 0 else None, _clamp(v) if v > 0 else None)


def _beam_attrs_structural(attrs) -> bool:
    """True when LINE carries CAE beam/rod payload (keep even if on a shell edge)."""
    if attrs is None:
        return False
    if getattr(attrs, "section", None):
        return True
    if getattr(attrs, "dist_load", None):
        return True
    if getattr(attrs, "point_loads", None):
        return True
    if getattr(attrs, "moments", None):
        return True
    if getattr(attrs, "bcs", None):
        return True
    if getattr(attrs, "springs", None):
        return True
    kind = (getattr(attrs, "kind", None) or "beam").strip().lower()
    return kind == "rod"


def _seg_matches_line_edge(a, b, ea, eb, tol: float) -> bool:
    return (
        _dist3(a, ea) <= tol and _dist3(b, eb) <= tol
    ) or (
        _dist3(a, eb) <= tol and _dist3(b, ea) <= tol
    )


def filter_beams_duplicating_shell_edges(beam_segs, faces, *, tol: float = 1.0):
    """Drop sweep/extrude profile LINEs that coincide with shell face edges.

    Bare construction curves left beside SWEPTSURFACE / EXTRUDEDSURFACE would
    otherwise become spurious ``\\stpDmember`` beams. LINEs with MY_CAE_* beam
    payload are kept.
    """
    if not faces or not beam_segs:
        return beam_segs
    edges: list[tuple] = []
    for face in faces:
        for loop in face.get("loops") or []:
            for ed in loop:
                if isinstance(ed, EdgeLine):
                    edges.append((ed.a, ed.b))
    if not edges:
        return beam_segs
    # Bin edge endpoints so each beam checks only nearby edges, not every face.
    step = max(float(tol), 1e-9)
    bins: dict[tuple[int, int, int], list[int]] = {}

    def _bin(p) -> tuple[int, int, int]:
        return (
            math.floor(float(p[0]) / step),
            math.floor(float(p[1]) / step),
            math.floor(float(p[2]) / step),
        )

    for i, (ea, eb) in enumerate(edges):
        bins.setdefault(_bin(ea), []).append(i)
        bins.setdefault(_bin(eb), []).append(i)

    def _nearby(p) -> set[int]:
        ix, iy, iz = _bin(p)
        hit: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    hit.update(bins.get((ix + dx, iy + dy, iz + dz), ()))
        return hit

    kept = []
    for seg in beam_segs:
        if _beam_attrs_structural(getattr(seg, "attrs", None)):
            kept.append(seg)
            continue
        matched = False
        for i in _nearby(seg.a) & _nearby(seg.b):
            ea, eb = edges[i]
            if _seg_matches_line_edge(seg.a, seg.b, ea, eb, tol):
                matched = True
                break
        if matched:
            continue
        kept.append(seg)
    return kept


def _vlen(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _vnorm(v):
    L = _vlen(v)
    if L < 1e-15:
        return (0.0, 0.0, 0.0)
    return (v[0] / L, v[1] / L, v[2] / L)


def _vcross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _view_screen_basis(vx, vy, vz, up=(0.0, 0.0, 1.0)):
    """Match satopdf \\stpDsetView (VPOINT): look dir n = -VPOINT, r=n×up, v=r×n."""
    n = _vnorm((-float(vx), -float(vy), -float(vz)))
    upn = _vnorm(up)
    r = _vcross(n, upn)
    if _vlen(r) < 1e-8:
        # n ∥ up → alternate reference (same as sty)
        if abs(upn[2]) > 0.9:
            r = (-n[2], 0.0, n[0])
        else:
            r = _vcross(n, (0.0, 0.0, 1.0))
    r = _vnorm(r)
    v = _vnorm(_vcross(r, n))
    return r, v


def _project_span_cm(points, to_cm: float, view: tuple, coords: tuple | None):
    """Projected paper width/height in cm at drawing scale 1:1 (TikZ cm)."""
    pts = list(points)
    if not pts:
        return 1.0, 1.0
    if coords is not None:
        # Legacy oblique: x-ang, y-ang [, Dx, Dy, Dz, z-ang]
        ax = math.radians(float(coords[0]))
        ay = math.radians(float(coords[1]))
        Dx = float(coords[2]) if len(coords) > 2 else 1.0
        Dy = float(coords[3]) if len(coords) > 3 else 1.0
        Dz = float(coords[4]) if len(coords) > 4 else 1.0
        az = math.radians(float(coords[5]) if len(coords) > 5 else 90.0)
        xx, xy = Dx * math.cos(ax), Dx * math.sin(ax)
        yx, yy = Dy * math.cos(ay), Dy * math.sin(ay)
        zx, zy = Dz * math.cos(az), Dz * math.sin(az)

        def proj(p):
            x, y, z = float(p[0]) * to_cm, float(p[1]) * to_cm, float(p[2]) * to_cm
            return (x * xx + y * yx + z * zx, x * xy + y * yy + z * zy)

    else:
        r, v = _view_screen_basis(view[0], view[1], view[2])

        def proj(p):
            q = (float(p[0]) * to_cm, float(p[1]) * to_cm, float(p[2]) * to_cm)
            return (_vdot(q, r), _vdot(q, v))

    xy = [proj(p) for p in pts]
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]
    return max(xs) - min(xs), max(ys) - min(ys)


def _cae_unit_to_cm(doc, points) -> tuple[float, int]:
    """LoadXData CAE drawings are in mm. Honor cm/m; ignore bogus inch tags."""
    ins = int(doc.header.get("$INSUNITS", 0) or 0)
    # Explicit metric
    if ins == 4:  # mm
        return 0.1, ins
    if ins == 5:  # cm
        return 1.0, ins
    if ins == 6:  # m
        return 100.0, ins
    if ins == 0:  # unset → mm (engineering default)
        return 0.1, ins
    # Inches/feet/etc. often wrong on CAE exports; large extents ⇒ treat as mm
    if points:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        zs = [float(p[2]) for p in points]
        ext = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 0.0)
        if ext > 50.0:  # e.g. 6000 "inches" is not a frame drawing
            return 0.1, 0
    return _TO_CM.get(ins, 0.1), ins


def _auto_stp_dscale(doc, points, view: tuple, coords: tuple | None):
    """A0 + ladder 1:1,1:2,1:4,… → largest N that fits; stpDscale = to_cm / N."""
    to_cm, _ins = _cae_unit_to_cm(doc, points)
    span_x, span_y = _project_span_cm(points, to_cm, view, coords)
    _sc, n = _sheet_scale(span_x, span_y)
    stp = to_cm / float(n)
    return stp, n, to_cm, span_x, span_y


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


def _parse_face_load_text(txt: str):
    """SETSHELLLOAD Face VIS label: P_face=… / F_total=… (ux,uy,uz)."""
    m = re.search(
        r"(P_face|F_total)\s*=\s*([-+0-9.eE]+)\s*(\S*)\s*"
        r"\(\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)\s*\)",
        txt or "",
        re.I,
    )
    if not m:
        return None
    kind = m.group(1).lower()
    return {
        "kind": "pressure" if kind == "p_face" else "total",
        "mag": float(m.group(2)),
        "unit": (m.group(3) or "").strip(),
        "dir": (float(m.group(4)), float(m.group(5)), float(m.group(6))),
    }


def _parse_point_load_text(txt: str):
    """SETPTLOAD VIS label: F[START|END]=1000.0N (direction not in text)."""
    m = re.search(
        r"F\[[^\]]*\]\s*=\s*([-+0-9.eE]+)\s*([A-Za-zµμ·\-]*)",
        txt or "",
    )
    if not m:
        return None
    return float(m.group(1)), (m.group(2) or "N").strip() or "N"


def _dir_from_load_block(blk) -> tuple[float, float, float]:
    """Longest LINE in VIS block: tail→tip = force direction (create-ptload-block)."""
    best = None
    best_len2 = -1.0
    for be in blk:
        if be.dxftype() != "LINE":
            continue
        a, b = be.dxf.start, be.dxf.end
        d = (float(b.x - a.x), float(b.y - a.y), float(b.z - a.z))
        len2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        if len2 > best_len2:
            best_len2 = len2
            best = d
    if best is None or best_len2 < 1e-18:
        return (0.0, 0.0, -1.0)
    inv = 1.0 / math.sqrt(best_len2)
    return (best[0] * inv, best[1] * inv, best[2] * inv)


def _point_load_label(mag: float, unit: str) -> str:
    unit_tex = re.sub(r"[^A-Za-z0-9_\-./]", "", unit) or "N"
    return rf"$F={mag:g}\,\mathrm{{{unit_tex}}}$"


def _parse_shell_load_xdata(tags) -> dict | None:
    """First FACE_PRESSURE / FACE_TOTAL_FORCE record. NORMAL has no fixed direction."""
    vals = _xdata_pairs(tags)
    i = 0
    found = None
    while i < len(vals):
        code, val = vals[i]
        scope = str(val).upper() if code == 1000 and isinstance(val, str) else ""
        if scope not in ("EDGE_LOAD", "FACE_PRESSURE", "FACE_TOTAL_FORCE") or i + 6 >= len(vals):
            i += 1
            continue
        try:
            n = int(vals[i + 6][1])
        except (TypeError, ValueError):
            n = 0
        if scope in ("FACE_PRESSURE", "FACE_TOTAL_FORCE") and found is None:
            try:
                mag = float(vals[i + 2][1])
            except (TypeError, ValueError):
                mag = None
            slot = vals[i + 4]
            normal = slot[0] == 1000 and str(slot[1]).upper() == "NORMAL"
            direction = None if normal else _as_xyz(slot[1])
            if mag is not None and (normal or direction is not None):
                found = {
                    "kind": "pressure" if scope == "FACE_PRESSURE" else "total",
                    "mag": mag,
                    "unit": str(vals[i + 3][1] or ""),
                    "dir": direction,
                    "normal": normal,
                }
        i = i + 7 + max(0, n)
    return found


def _parse_shell_edge_loads(tags) -> list[dict]:
    """MY_CAE_SHELL_LOAD records whose type is EDGE_LOAD (boundary polyline)."""
    vals = _xdata_pairs(tags)
    recs: list[dict] = []
    i = 0
    while i < len(vals):
        code, val = vals[i]
        scope = str(val).upper() if code == 1000 and isinstance(val, str) else ""
        if scope not in ("EDGE_LOAD", "FACE_PRESSURE", "FACE_TOTAL_FORCE") or i + 6 >= len(vals):
            i += 1
            continue
        try:
            n = int(vals[i + 6][1])
        except (TypeError, ValueError):
            n = 0
        j = i + 7
        pts: list[tuple[float, float, float]] = []
        for _ in range(max(0, n)):
            if j < len(vals) and vals[j][0] == 1010:
                p = _as_xyz(vals[j][1])
                if p is not None:
                    pts.append(p)
            j += 1
        if scope == "EDGE_LOAD":
            direction = _as_xyz(vals[i + 4][1])
            try:
                mag = float(vals[i + 2][1])
            except (TypeError, ValueError):
                mag = None
            if direction is not None and mag is not None and len(pts) >= 2:
                recs.append(
                    {
                        "mag": mag,
                        "unit": str(vals[i + 3][1] or ""),
                        "dir": direction,
                        "pts": pts,
                    }
                )
        i = j
    return recs


def _edge_load_label(mag: float, unit: str) -> str:
    unit_tex = re.sub(r"[^A-Za-z0-9_\-./]", "", unit or "")
    if unit_tex:
        return rf"$q={mag:g}\,\mathrm{{{unit_tex}}}$"
    return rf"$q={mag:g}$"


def _face_load_label(info: dict) -> str:
    mag = info["mag"]
    unit = info.get("unit") or ("MPa" if info["kind"] == "pressure" else "N")
    # sanitize unit for mathrm
    unit_tex = re.sub(r"[^A-Za-z0-9_\-./]", "", unit) or (
        "MPa" if info["kind"] == "pressure" else "N"
    )
    if info.get("normal"):
        tag = rf"\,n"
    else:
        tag = ""
    if info["kind"] == "pressure":
        return rf"$P_{{\mathrm{{face}}}}={mag:g}\,\mathrm{{{unit_tex}}}{tag}$"
    return rf"$F_{{\mathrm{{total}}}}={mag:g}\,\mathrm{{{unit_tex}}}{tag}$"


def _uniq_ring(pts: list[tuple]) -> list[tuple]:
    if not pts:
        return []
    out = [pts[0]]
    for p in pts[1:]:
        if p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _centroid(pts: list[tuple]) -> tuple:
    n = len(pts)
    return (
        sum(p[0] for p in pts) / n,
        sum(p[1] for p in pts) / n,
        sum(p[2] for p in pts) / n,
    )


def _mesh_loops_from_acis(entity) -> list[list[tuple]]:
    """REGION / SURFACE / 3DSOLID → vertex rings via ezdxf ACIS mesh."""
    sab = getattr(entity, "sab", None) or getattr(entity, "acis_data", None)
    if not sab:
        return []
    try:
        from ezdxf.acis import api as acis
    except Exception:
        return []
    loops: list[list[tuple]] = []
    try:
        bodies = acis.load(sab)
    except Exception:
        return []
    for body in bodies:
        try:
            meshes = acis.mesh_from_body(body)
        except Exception:
            continue
        for mesh in meshes:
            verts = [_k(v) for v in mesh.vertices]
            for face in mesh.faces:
                ring = _uniq_ring([verts[i] for i in face if 0 <= i < len(verts)])
                if len(ring) >= 3:
                    loops.append(ring)
    return loops


def _face_loops_from_entity(e) -> list[list[tuple]]:
    """Extract shell loops from 3DFACE / MESH / REGION / SURFACE / LWPOLYLINE."""
    t = e.dxftype()
    if t == "3DFACE":
        pts = _uniq_ring(
            [_k(e.dxf.vtx0), _k(e.dxf.vtx1), _k(e.dxf.vtx2), _k(e.dxf.vtx3)]
        )
        return [pts] if len(pts) >= 3 else []
    if t == "MESH":
        try:
            verts = [_k(v) for v in e.vertices]
            loops = []
            for face in e.faces:
                ring = _uniq_ring([verts[i] for i in face if 0 <= i < len(verts)])
                if len(ring) >= 3:
                    loops.append(ring)
            return loops
        except Exception:
            return []
    if t in (
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
    ):
        return _mesh_loops_from_acis(e)
    if t == "LWPOLYLINE" and bool(e.closed):
        elev = float(getattr(e.dxf, "elevation", 0.0) or 0.0)
        pts = [_k((x, y, elev)) for x, y, *_rest in e.get_points("xy")]
        pts = _uniq_ring(pts)
        return [pts] if len(pts) >= 3 else []
    return []


def _mask_to_dirs(mask: str):
    """Return (ux,uy,uz,rx,ry,rz) flags 0|1 from GLOBAL[abcdef]."""
    bits = [(1 if (i < len(mask) and mask[i] == "1") else 0) for i in range(6)]
    return tuple(bits)


def _xdata_pairs(tags) -> list[tuple]:
    out = []
    for t in tags or []:
        code = getattr(t, "code", None)
        val = getattr(t, "value", t)
        if code is None and isinstance(t, (tuple, list)) and len(t) >= 2:
            code, val = t[0], t[1]
        out.append((code, val))
    return out


def _as_xyz(val) -> tuple[float, float, float] | None:
    try:
        return (float(val[0]), float(val[1]), float(val[2]))
    except Exception:
        return None


def _parse_shell_edge_bcs(tags) -> list[dict]:
    """MY_CAE_SHELL_BC records whose scope is EDGE_BC (boundary polyline)."""
    vals = _xdata_pairs(tags)
    recs: list[dict] = []
    i = 0
    while i < len(vals):
        code, val = vals[i]
        scope = str(val).upper() if code == 1000 and isinstance(val, str) else ""
        if scope not in ("EDGE_BC", "FACE_BC") or i + 10 >= len(vals):
            i += 1
            continue
        try:
            n = int(vals[i + 10][1])
        except (TypeError, ValueError):
            n = 0
        j = i + 11
        pts: list[tuple[float, float, float]] = []
        for _ in range(max(0, n)):
            if j < len(vals) and vals[j][0] == 1010:
                p = _as_xyz(vals[j][1])
                if p is not None:
                    pts.append(p)
            j += 1
        if scope == "EDGE_BC" and len(pts) >= 2:
            recs.append(
                {
                    "u_mask": str(vals[i + 1][1] or "000"),
                    "u_axes": [_as_xyz(vals[i + k][1]) for k in (2, 3, 4)],
                    "r_mask": str(vals[i + 5][1] or "000"),
                    "r_axes": [_as_xyz(vals[i + k][1]) for k in (6, 7, 8)],
                    "pts": pts,
                }
            )
        i = j
    return recs


def _triad_flags(mask3: str, axes: list) -> list[int]:
    """Map a 3-bit local mask onto global X/Y/Z by each axis's largest component."""
    flags = [0, 0, 0]
    bits = (mask3 or "000")[:3]
    for i, bit in enumerate(bits):
        if bit != "1":
            continue
        v = axes[i] if i < len(axes) else None
        if not v:
            flags[i] = 1
            continue
        ax = max(range(3), key=lambda k: abs(v[k]))
        flags[ax] = 1
    return flags


def _edge_bc_mask(rec: dict) -> str:
    u = _triad_flags(rec.get("u_mask") or "000", rec.get("u_axes") or [])
    r = _triad_flags(rec.get("r_mask") or "000", rec.get("r_axes") or [])
    return "".join(str(b) for b in u + r)


def _poly_length(pts: list[tuple]) -> float:
    return sum(_dist3(a, b) for a, b in zip(pts, pts[1:]))


def _edge_bc_closed(pts: list[tuple]) -> bool:
    if len(pts) < 3:
        return False
    length = _poly_length(pts)
    if length < 1e-9:
        return False
    return _dist3(pts[0], pts[-1]) <= max(1e-3, 1e-4 * length)


def _point_along(pts: list[tuple], distance: float) -> tuple:
    if not pts:
        return (0.0, 0.0, 0.0)
    if distance <= 0.0:
        return pts[0]
    walked = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = _dist3(a, b)
        if walked + seg >= distance - 1e-9 or seg < 1e-15:
            t = 0.0 if seg < 1e-15 else (distance - walked) / seg
            t = max(0.0, min(1.0, t))
            return tuple(a[i] + t * (b[i] - a[i]) for i in range(3))
        walked += seg
    return pts[-1]


def _edge_bc_stations(pts: list[tuple], scale: float) -> list[tuple]:
    """Equal-arc stations for one boundary curve.

    An open curve gets 3 to 5 symbols and always includes both ends.
    A closed curve has no end, so it gets 5 symbols around the loop.
    """
    if len(pts) < 2:
        return []
    closed = _edge_bc_closed(pts)
    seq = list(pts)
    length = _poly_length(seq)
    if length < 1e-9:
        return [seq[0]]
    if closed:
        return [_point_along(seq, length * k / 5.0) for k in range(5)]
    # Largest count in 3..5 whose gap is at least two symbol lengths on paper.
    paper = 0.70 / scale if scale and scale > 0 else 0.0
    count = 3
    for n in (5, 4, 3):
        if length / (n - 1) >= paper - 1e-9:
            count = n
            break
    return [_point_along(seq, length * i / (count - 1)) for i in range(count)]


def _point_seg_dist(p, a, b) -> float:
    ab = [float(b[i]) - float(a[i]) for i in range(3)]
    ap = [float(p[i]) - float(a[i]) for i in range(3)]
    ab2 = sum(x * x for x in ab)
    if ab2 < 1e-18:
        return _dist3(p, a)
    t = max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / ab2))
    return _dist3(p, tuple(float(a[i]) + t * ab[i] for i in range(3)))


def _edge_deviation(edge, pts: list[tuple]) -> float:
    samples = _edge_samples(edge, n=48)
    if len(samples) < 2 or not pts:
        return float("inf")
    segs = list(zip(samples, samples[1:]))
    if getattr(edge, "kind", "") == "circle":
        segs.append((samples[-1], samples[0]))
    worst = 0.0
    for p in pts:
        worst = max(worst, min(_point_seg_dist(p, a, b) for a, b in segs))
    return worst


def _match_boundary_edge(faces, idxs, pts):
    """Edge whose equation the picked samples lie on. Prefer the closest length."""
    best = None
    best_key = None
    slen = _poly_length(pts)
    for i in idxs or []:
        if i < 0 or i >= len(faces):
            continue
        for loop in faces[i].get("loops") or []:
            if not isinstance(loop, (list, tuple)):
                continue
            for edge in loop:
                dev = _edge_deviation(edge, pts)
                samples = _edge_samples(edge, n=48)
                elen = _poly_length(samples)
                if getattr(edge, "kind", "") == "circle" and len(samples) >= 2:
                    elen += _dist3(samples[-1], samples[0])
                tol = max(0.5, 0.02 * max(elen, slen, 1.0))
                if dev > tol:
                    continue
                key = (dev, abs(elen - slen))
                if best_key is None or key < best_key:
                    best_key = key
                    best = edge
    return best


def _xform_xyz(xform, p: tuple) -> tuple:
    q = xform.transform((float(p[0]), float(p[1]), float(p[2])))
    return (float(q[0]), float(q[1]), float(q[2]))


def _xform_dir(xform, v: tuple) -> tuple:
    q = xform.transform_direction((float(v[0]), float(v[1]), float(v[2])))
    n = math.sqrt(sum(float(q[i]) ** 2 for i in range(3)))
    if n < 1e-12:
        return v
    return (float(q[0]) / n, float(q[1]) / n, float(q[2]) / n)


def _nearest3(nodes, p):
    return min(
        nodes, key=lambda q: sum((q[i] - p[i]) ** 2 for i in range(3))
    )


def dxf_to_satopdf3d(
    data: bytes | None = None,
    *,
    path: str | Path | None = None,
    name: str = "drawing.dxf",
    scale: float | None = None,
    view: tuple = (1, -1, 1),
    coords: tuple | None = None,
    load_count: int = 6,
    load_shaft: float = 0.55,
    fragment: bool = True,
) -> tuple[str, str]:
    """view: AutoCAD VPOINT (vx,vy,vz). coords: optional legacy paper angles
    (x-ang, y-ang[, Dx[, Dy]]) — if set, overrides view.

    scale: \\stpDscale multiplier for DXF coords (TikZ cm). None → auto from A0
    + ladder 1:1,1:2,1:4,… (largest that fits), same rule as geometry DXF import.
    """
    doc = _read(data, path)
    msp = doc.modelspace()
    src = Path(path).name if path else name

    nodes: dict[tuple, tuple] = {}
    beam_segs = collect_beam_segs_from_msp(msp, dim=3, key_tol=1e-6)
    beam_segs.extend(collect_beam_segs_from_inserts(doc, msp, dim=3, key_tol=1e-6))
    for s in beam_segs:
        nodes[s.a] = s.a
        nodes[s.b] = s.b

    # Shell faces: exact curve equations (line/arc/circle/spline), NOT FE tessellation.
    faces: list[dict] = []
    face_loads_by_idx: dict[int, dict] = {}
    shell_edge_bcs: list[dict] = []
    shell_edge_loads: list[dict] = []
    # Sampled boundary points for scale / envelope only (never emitted as FE nodes).
    extent_pts: list[tuple] = []
    _FACE_TYPES = (
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
        "LWPOLYLINE",
        "CIRCLE",
        "ELLIPSE",
        "SPLINE",
        "HATCH",
    )
    def _take_face(e, xform=None):
        layer = (e.dxf.layer or "").upper()
        if layer.startswith("CAE_VIS") or layer.startswith("CAE_LOAD"):
            return
        if e.dxftype() not in _FACE_TYPES:
            return
        analytic = analytic_faces_from_entity(e)
        if not analytic:
            return
        shell_ld = None
        try:
            shell_ld = _parse_shell_load_xdata(e.get_xdata("MY_CAE_SHELL_LOAD"))
        except Exception:
            shell_ld = None
        edge_bcs = []
        edge_lds = []
        try:
            edge_bcs = _parse_shell_edge_bcs(e.get_xdata("MY_CAE_SHELL_BC"))
        except Exception:
            edge_bcs = []
        try:
            edge_lds = _parse_shell_edge_loads(e.get_xdata("MY_CAE_SHELL_LOAD"))
        except Exception:
            edge_lds = []
        if xform is not None:
            for rec in edge_bcs:
                rec["pts"] = [_xform_xyz(xform, p) for p in rec["pts"]]
                rec["u_axes"] = [
                    _xform_dir(xform, v) if v else None for v in rec["u_axes"]
                ]
                rec["r_axes"] = [
                    _xform_dir(xform, v) if v else None for v in rec["r_axes"]
                ]
            for rec in edge_lds:
                rec["pts"] = [_xform_xyz(xform, p) for p in rec["pts"]]
                rec["dir"] = _xform_dir(xform, rec["dir"])
        shell_edge_bcs.extend(edge_bcs)
        shell_edge_loads.extend(edge_lds)
        span0 = len(faces)
        mesh_u, mesh_v = _dxf_surface_isoline_counts(e)
        for af in analytic:
            if xform is not None:
                af = transform_analytic_face(af, xform)
            cen = _k(af.get("cen") or (0.0, 0.0, 0.0))
            if af.get("kind") == "cylinder":
                extent_pts.extend(cylinder_extent_pts(af, n=24))
            elif af.get("kind") == "revolve":
                extent_pts.extend(revolve_extent_pts(af, n=24))
            else:
                # region / plane / ruled / wire: boundary samples for extent
                for poly in curve_loops_as_polylines(af.get("loops") or [], n=24):
                    extent_pts.extend(_k(p) for p in poly)
            fi = len(faces)
            face = {**af, "cen": cen, "handle": e.dxf.handle}
            if af.get("kind") == "plane":
                if mesh_u is not None:
                    face["mesh_u"] = mesh_u
                if mesh_v is not None:
                    face["mesh_v"] = mesh_v
            faces.append(face)
            # Centroid node only when a face load needs an arrow tip
            if shell_ld is not None:
                nodes[cen] = cen
                face_loads_by_idx[fi] = shell_ld
        span = list(range(span0, len(faces)))
        for rec in edge_bcs:
            rec["faces"] = span
        for rec in edge_lds:
            rec["faces"] = span

    for e in msp:
        _take_face(e)
    # Associative ARRAY / block INSERT: source lives in an anonymous block.
    for e, xform in iter_inserted_entities(doc, msp):
        _take_face(e, xform)

    # Sweep/extrude often leaves profile/path LINEs on face edges — not beams
    if faces:
        beam_segs = filter_beams_duplicating_shell_edges(beam_segs, faces)
        nodes = {s.a: s.a for s in beam_segs}
        nodes.update({s.b: s.b for s in beam_segs})
        for fi in face_loads_by_idx:
            cen = faces[fi]["cen"]
            nodes[cen] = cen

    # Beam XDATA → vis-handle map for SETPTLOAD direction (fallback)
    ptload_by_vis: dict[str, tuple[float, tuple, str]] = {}
    for e in msp.query("LINE"):
        try:
            tags = e.get_xdata("MY_CAE_POINT_LOAD")
        except Exception:
            continue
        if not tags:
            continue
        # records: endTag(1000) mag(1040) dir(1013) vis(1005) unit(1000) …
        i = 0
        vals = []
        for t in tags:
            code = getattr(t, "code", None)
            val = getattr(t, "value", t)
            if code is None and isinstance(t, (tuple, list)) and len(t) >= 2:
                code, val = t[0], t[1]
            vals.append((code, val))
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
                direction = (float(dvec[0]), float(dvec[1]), float(dvec[2]))
                ptload_by_vis[str(vis_h).upper()] = (float(mag), direction, unit)
            i += step

    bcs: list[tuple] = []
    loads: list[dict] = []
    point_loads: list[dict] = []
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
                for t in texts:
                    m = re.search(r"\[([01]{6})\]", t or "")
                    if m:
                        mask = m.group(1)
                        break
            if mask:
                bcs.append((origin, mask))
                nodes[origin] = origin
        elif "CAE_VIS_LOAD" in layer:
            face_parsed = None
            for t in texts:
                face_parsed = _parse_face_load_text(t) or face_parsed
            if face_parsed is not None:
                # Fallback when face has no MY_CAE_SHELL_LOAD XDATA: match by centroid
                for fi, face in enumerate(faces):
                    if fi in face_loads_by_idx:
                        continue
                    cen = face["cen"]
                    if sum((cen[i] - origin[i]) ** 2 for i in range(3)) < 1.0:
                        face_loads_by_idx[fi] = face_parsed
                        break
                continue
            # SETPTLOAD nodal force: F[START|END]=…
            f_parsed = None
            for t in texts:
                f_parsed = _parse_point_load_text(t) or f_parsed
            if f_parsed is not None:
                mag, unit = f_parsed
                direction = None
                vis_key = str(e.dxf.handle).upper()
                if vis_key in ptload_by_vis:
                    _m, direction, unit_xd = ptload_by_vis[vis_key]
                    if unit_xd:
                        unit = unit_xd
                if direction is None:
                    direction = _dir_from_load_block(blk)
                nodes[origin] = origin
                point_loads.append(
                    {
                        "p": origin,
                        "mag": mag,
                        "dir": direction,
                        "label": _point_load_label(mag, unit),
                    }
                )
                continue
            parsed = None
            for t in texts:
                parsed = _parse_load_text(t) or parsed
            if parsed is None:
                continue
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
            mag, direction, _unit = parsed
            loads.append(
                {
                    "a": a,
                    "b": b,
                    "mag": mag,
                    "dir": direction,
                    "label": f"$q={mag:g}$",
                }
            )

    # Welds + beam intersections → unit split (attrs inherited on children)
    spot_welds = parse_spot_welds(msp, _k)
    seam_welds = parse_seam_welds(msp, _k)
    weld_pts = [sw["xyz"] for sw in spot_welds]
    for sm in seam_welds:
        weld_pts.extend(sm["pts"])

    extra_cuts = list(weld_pts)
    for p, _mask in bcs:
        extra_cuts.append(p)
    for pl in point_loads:
        extra_cuts.append(pl["p"])

    mesh_nodes, meshed = mesh_beams(
        beam_segs, extra_cuts, tol=1e-2, key_tol=1e-6, dim=3
    )
    nodes.update(mesh_nodes)
    for sw in spot_welds:
        sw["xyz"] = _nearest3(nodes.keys(), sw["xyz"]) if nodes else sw["xyz"]
        nodes[sw["xyz"]] = sw["xyz"]
    for sm in seam_welds:
        sm["pts"] = [
            _nearest3(nodes.keys(), p) if nodes else p for p in sm["pts"]
        ]
        for p in sm["pts"]:
            nodes[p] = p

    members = [(s.a, s.b) for s in meshed]
    member_attrs = {(s.a, s.b): s.attrs for s in meshed}
    # q span rebound to each child segment (intensity/direction unchanged)
    loads = [
        {
            "a": ld["start"],
            "b": ld["end"],
            "mag": ld["magnitude"],
            "dir": tuple(ld["direction"]),
            "label": f"$q={ld['magnitude']:g}$",
        }
        for ld in expand_dist_loads(meshed, loads, tol=1e-2)
    ]

    ordered = sorted(nodes.keys(), key=lambda t: (t[1], t[0], t[2]))
    if not ordered and not faces:
        raise ValueError("没有可转换的结构线段或板壳面")
    # Axis / dim anchor: prefer structural nodes; else bbox corner of shell extents
    if not ordered:
        if extent_pts:
            xs = [p[0] for p in extent_pts]
            ys = [p[1] for p in extent_pts]
            zs = [p[2] for p in extent_pts]
            anchor = _k((min(xs), min(ys), min(zs)))
        else:
            anchor = (0.0, 0.0, 0.0)
        nodes[anchor] = anchor
        ordered = [anchor]
    nid = {p: f"N{i}" for i, p in enumerate(ordered)}

    span_pts = list(ordered) + extent_pts
    if scale is None:
        scale, scale_n, to_cm, span_x_cm, span_y_cm = _auto_stp_dscale(
            doc, span_pts, view, coords
        )
    else:
        to_cm, _ins = _cae_unit_to_cm(doc, span_pts)
        span_x_cm, span_y_cm = _project_span_cm(span_pts, to_cm, view, coords)
        if to_cm > 0 and scale > 0:
            approx = max(1, int(round(to_cm / scale)))
            scale_n = approx if approx in _SCALE_N else approx
        else:
            scale_n = None

    # Boundary loads and restraints use the face edge equation in TeX.
    # They do not add structural nodes.
    edge_bc_lines: list[str] = []
    edge_ld_lines: list[str] = []
    seen_edge: set[str] = set()
    for rec in shell_edge_bcs:
        mask = _edge_bc_mask(rec)
        if not any(ch == "1" for ch in mask):
            continue
        edge = _match_boundary_edge(faces, rec.get("faces") or [], rec["pts"])
        if edge is None:
            continue
        call = _emit_edge_tex(edge, indent="").strip()
        if not call:
            continue
        ux, uy, uz, rx, ry, rz = _mask_to_dirs(mask)
        line = (
            f"  \\stpDedgeBc{{{call}}}"
            f"[{ux}][{uy}][{uz}][{rx}][{ry}][{rz}]"
            f"  % EDGE_BC[{mask}]"
        )
        if line not in seen_edge:
            seen_edge.add(line)
            edge_bc_lines.append(line)
    for rec in shell_edge_loads:
        if not rec.get("dir"):
            continue
        edge = _match_boundary_edge(faces, rec.get("faces") or [], rec["pts"])
        if edge is None:
            continue
        call = _emit_edge_tex(edge, indent="").strip()
        if not call:
            continue
        ddx, ddy, ddz = rec["dir"]
        label = _edge_load_label(rec["mag"], rec.get("unit") or "")
        line = (
            f"  \\stpDedgeLoad{{{call}}}{{{ddx:g},{ddy:g},{ddz:g}}}"
            f"[{load_count}][{load_shaft:g}][{label}]"
        )
        if line not in seen_edge:
            seen_edge.add(line)
            edge_ld_lines.append(line)
    ordered = sorted(nodes.keys(), key=lambda t: (t[1], t[0], t[2]))
    nid = {p: f"N{i}" for i, p in enumerate(ordered)}

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
    if scale_n is not None:
        L.append(
            f"% Drawing scale 1:{scale_n} "
            f"(projected {span_x_cm:.1f}×{span_y_cm:.1f} cm @1:1 → A0 "
            f"{_A0[0]}×{_A0[1]} cm; ladder {_SCALE_N[0]}…{_SCALE_N[-1]})"
        )
    if coords is not None:
        ang_x, ang_y = coords[0], coords[1]
        dx = coords[2] if len(coords) > 2 else 1
        dy = coords[3] if len(coords) > 3 else 1
        view_line = f"\\stpDsetCoords{{{ang_x}}}{{{ang_y}}}[{dx}][{dy}]"
    else:
        vx, vy, vz = view
        view_line = f"\\stpDsetView{{{vx:g}}}{{{vy:g}}}{{{vz:g}}}"
    # Up vector is a separate line so it can be edited without touching VPOINT.
    # Default matches \\stpDsetUp in satopdf.sty (+Z). Y-up is {0}{1}{0}.
    L += [
        "\\stpDsetUp{0}{0}{1}",
        view_line,
        "\\stpDsetAxis{xyz}",
        f"\\renewcommand{{\\stpDscale}}{{{scale:g}}}",
        "\\renewcommand{\\stpDsupLen}{0.35}",
        "\\renewcommand{\\stpDhingeR}{0.9mm}",
        "\\renewcommand{\\stpDaxLen}{1.2}",
        "% Δ before tikzpicture (nullfont inside would zero char height)",
        "\\stpInitDimDelta",
        "\\begin{tikzpicture}[stpDCoords,stpScheme=color]",
    ]
    for p in ordered:
        L.append(
            f"  \\stpDpoint{{{nid[p]}}}{{{p[0]:.4f}}}{{{p[1]:.4f}}}{{{p[2]:.4f}}}"
        )
    L.append(f"  \\stpDaxis{{{nid[ordered[0]]}}}")

    for a, b in members:
        attr = member_attrs.get((a, b))
        sec_note = ""
        if attr and attr.section:
            sec_note = (
                f"  % sec={attr.section.get('type')}"
                f" {attr.section.get('spec')}"
                f" {attr.section.get('material')}"
            )
            if attr.dist_load and not attr.is_rod:
                sec_note += f" q={attr.dist_load.get('magnitude')}"
        if attr and attr.is_rod:
            # Axial rod: never use beam/truss heuristic
            if not sec_note:
                sec_note = "  % kind=rod"
            else:
                sec_note += " kind=rod"
            L.append(
                f"  \\stpDmember{{rod}}{{{nid[a]}}}{{{nid[b]}}}{sec_note}"
            )
        elif _is_axis_aligned(a, b):
            L.append(
                f"  \\stpDmember{{beam}}{{{nid[a]}}}{{{nid[b]}}}{sec_note}"
            )
        else:
            L.append(
                f"  \\stpDmember{{truss}}{{{nid[a]}}}{{{nid[b]}}}[1][1]"
                f"{sec_note}"
            )

    for face in faces:
        L.extend(format_stp_analytic_face(face))

    # Welds after faces/members (above shell fill, before BC/loads)
    L.extend(emit_weld_tex_3d(spot_welds, seam_welds, nid))

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

    L.extend(edge_bc_lines)

    for ld in loads:
        a, b = ld["a"], ld["b"]
        ddx, ddy, ddz = ld["dir"]
        L.append(
            f"  \\stpDlineload{{{nid[a]}}}{{{nid[b]}}}"
            f"[{ddx:g},{ddy:g},{ddz:g}][{load_count}][{load_shaft:g}][{ld['label']}]"
        )

    for pl in point_loads:
        nearest = min(
            ordered, key=lambda q: sum((q[i] - pl["p"][i]) ** 2 for i in range(3))
        )
        ddx, ddy, ddz = pl["dir"]
        L.append(
            f"  \\stpDpointload{{{nid[nearest]}}}{{{ddx:g},{ddy:g},{ddz:g}}}"
            f"[{load_shaft:g}][{pl['label']}]"
        )

    for fi, info in sorted(face_loads_by_idx.items()):
        face = faces[fi]
        # Tip at analytic centroid node (not a tessellated boundary)
        cname = nid.get(face["cen"])
        if not cname:
            continue
        label = _face_load_label(info)
        if info.get("normal"):
            # Direction is the local face normal, resolved when the face is meshed.
            L.append(
                f"  \\node[stpLoadLabel] at ({cname}) {{{label}}};"
                f"  % FACE normal"
            )
        else:
            ddx, ddy, ddz = info["dir"]
            L.append(
                f"  \\stpDpointload{{{cname}}}{{{ddx:g},{ddy:g},{ddz:g}}}"
                f"[{load_shaft:g}][{label}]"
            )

    L.extend(edge_ld_lines)

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

    # Overall envelope dims from true shell extents (not load centroids alone)
    #   \stpDdimEnv{x}{x0}{y0}{z0}{Lx}[$L_x$]
    box_pts = span_pts if span_pts else ordered
    xs = [p[0] for p in box_pts]
    ys = [p[1] for p in box_pts]
    zs = [p[2] for p in box_pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    lx, ly, lz = xmax - xmin, ymax - ymin, zmax - zmin
    if max(lx, ly, lz) > 1e-6:
        corner = f"{xmin:.4f}}}{{{ymin:.4f}}}{{{zmin:.4f}"
        if lx > 1e-6:
            L.append(
                "  \\stpDdimEnv{x}{"
                + corner
                + f"}}{{{lx:.4f}}}[$L_x={_fmt_len_mm(lx)}$]"
            )
        if ly > 1e-6:
            L.append(
                "  \\stpDdimEnv{y}{"
                + corner
                + f"}}{{{ly:.4f}}}[$L_y={_fmt_len_mm(ly)}$]"
            )
        if lz > 1e-6:
            L.append(
                "  \\stpDdimEnv{z}{"
                + corner
                + f"}}{{{lz:.4f}}}[$L_z={_fmt_len_mm(lz)}$]"
            )

    mass_info = accumulate_from_dxf(doc, face_loops_fn=face_curve_loops_from_entity)
    if mass_info["volume_mm3"] > 0:
        L.append(emit_struct_info_tex(mass_info["volume_mm3"], mass_info["mass_kg"]))

    L.append("\\end{tikzpicture}")
    if not fragment:
        L += ["\\end{document}", ""]
    n_fl = len(face_loads_by_idx)
    scale_note = f", scale 1:{scale_n}" if scale_n is not None else f", stpDscale={scale:g}"
    note = (
        f"satopdf 3D: {len(ordered)} nodes, {len(members)} members, "
        f"{len(faces)} faces, {len(point_loads)} point loads, {n_fl} face loads, "
        f"{len(edge_bc_lines)} edge BCs, {len(edge_ld_lines)} edge loads, "
        f"spots={len(spot_welds)}, seams={len(seam_welds)}"
        f"{scale_note}"
        f"; V={mass_info['volume_mm3']:.3g} mm3, m={mass_info['mass_kg']:.3g} kg"
        f" (beams={mass_info['n_beam']}, shells={mass_info['n_shell']})"
    )
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
