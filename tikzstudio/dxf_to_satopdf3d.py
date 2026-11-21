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
    cylinder_extent_pts,
    face_curve_loops_from_entity,
    format_stp_analytic_face,
)
from .cae_welds import emit_weld_tex_3d, parse_seam_welds, parse_spot_welds
from .dxf_import import _A0, _SCALE_N, _TO_CM, _sheet_scale


def _k(p, tol=1e-6):
    return (
        round(float(p[0]) / tol) * tol,
        round(float(p[1]) / tol) * tol,
        round(float(p[2]) / tol) * tol,
    )


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
    """MY_CAE_SHELL_LOAD: FACE_PRESSURE | FACE_TOTAL_FORCE (skip EDGE_LOAD here)."""
    if not tags:
        return None
    kind = None
    mag = None
    unit = ""
    direction = None
    for t in tags:
        code = getattr(t, "code", None)
        val = getattr(t, "value", t)
        if code is None and isinstance(t, (tuple, list)) and len(t) >= 2:
            code, val = t[0], t[1]
        if code == 1000 and isinstance(val, str):
            u = val.upper()
            if u in ("FACE_PRESSURE", "FACE_TOTAL_FORCE", "EDGE_LOAD"):
                kind = u
            elif u.startswith("LC"):
                pass
            elif kind is not None and mag is not None and not unit:
                unit = val
        elif code == 1040 and kind is not None and mag is None:
            mag = float(val)
        elif code == 1013 and direction is None:
            direction = (float(val[0]), float(val[1]), float(val[2]))
    if kind not in ("FACE_PRESSURE", "FACE_TOTAL_FORCE") or mag is None or direction is None:
        return None
    return {
        "kind": "pressure" if kind == "FACE_PRESSURE" else "total",
        "mag": mag,
        "unit": unit,
        "dir": direction,
    }


def _face_load_label(info: dict) -> str:
    mag = info["mag"]
    unit = info.get("unit") or ("MPa" if info["kind"] == "pressure" else "N")
    # sanitize unit for mathrm
    unit_tex = re.sub(r"[^A-Za-z0-9_\-./]", "", unit) or (
        "MPa" if info["kind"] == "pressure" else "N"
    )
    if info["kind"] == "pressure":
        return rf"$P_{{\mathrm{{face}}}}={mag:g}\,\mathrm{{{unit_tex}}}$"
    return rf"$F_{{\mathrm{{total}}}}={mag:g}\,\mathrm{{{unit_tex}}}$"


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
    if t in ("REGION", "SURFACE", "3DSOLID"):
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
    for s in beam_segs:
        nodes[s.a] = s.a
        nodes[s.b] = s.b

    # Shell faces: exact curve equations (line/arc/circle/spline), NOT FE tessellation.
    faces: list[dict] = []
    face_loads_by_idx: dict[int, dict] = {}
    # Sampled boundary points for scale / envelope only (never emitted as FE nodes).
    extent_pts: list[tuple] = []
    _FACE_TYPES = (
        "REGION",
        "SURFACE",
        "3DSOLID",
        "3DFACE",
        "MESH",
        "LWPOLYLINE",
        "CIRCLE",
        "ELLIPSE",
        "SPLINE",
        "HATCH",
    )
    for e in msp:
        layer = (e.dxf.layer or "").upper()
        if layer.startswith("CAE_VIS") or layer.startswith("CAE_LOAD"):
            continue
        if e.dxftype() not in _FACE_TYPES:
            continue
        analytic = analytic_faces_from_entity(e)
        if not analytic:
            continue
        shell_ld = None
        try:
            shell_ld = _parse_shell_load_xdata(e.get_xdata("MY_CAE_SHELL_LOAD"))
        except Exception:
            shell_ld = None
        for af in analytic:
            cen = _k(af.get("cen") or (0.0, 0.0, 0.0))
            if af.get("kind") == "cylinder":
                extent_pts.extend(cylinder_extent_pts(af, n=24))
            else:
                # plane / wire: use boundary samples
                for poly in curve_loops_as_polylines(af.get("loops") or [], n=24):
                    extent_pts.extend(_k(p) for p in poly)
            fi = len(faces)
            faces.append({**af, "cen": cen, "handle": e.dxf.handle})
            # Centroid node only when a face load needs an arrow tip
            if shell_ld is not None:
                nodes[cen] = cen
                face_loads_by_idx[fi] = shell_ld

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
    L += [
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
        ddx, ddy, ddz = info["dir"]
        label = _face_load_label(info)
        L.append(
            f"  \\stpDpointload{{{cname}}}{{{ddx:g},{ddy:g},{ddz:g}}}"
            f"[{load_shaft:g}][{label}]"
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
