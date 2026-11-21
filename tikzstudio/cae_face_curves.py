# -*- coding: utf-8 -*-
"""Exact curve equations for shell-face boundaries (FE-safe).

DXF REGION / CIRCLE / ARC / ELLIPSE / SPLINE / LWPOLYLINE → loops of analytic
edges.  Tessellation is used ONLY for area sorting / mass estimates / PDF
display helpers — never as the exported FE geometry.

Edge kinds:
  line    — endpoints
  circle  — centre, unit normal, radius
  arc     — centre, normal, major axis vector, ratio, t0, t1 (ACIS ellipse param)
  spline  — degree + control points (NUBS / DXF spline)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence, Union

from ezdxf.math import Vec3

from .cae_face_loops import (
    _ellipse_from_record,
    _intcurve_is_ref_only,
    _k,
    _nubs_cps_aligned,
    _nubs_cps_from_ref_intcurve,
    _parse_sab_records,
    _sab_coedge,
    _sab_edge,
    _sab_loop_list,
    _sab_vertex_point,
    _field_ptrs,
    _shoelace_area_xy,
    _uniq_ring,
    loop_from_circle,
    loop_from_arc,
    loop_from_ellipse,
    loop_from_spline,
    loop_from_lwpolyline,
    loops_from_hatch,
    loops_from_mesh_entity,
    order_outer_then_holes,
    tessellate_bspline,
    tessellate_ellipse,
)


@dataclass(frozen=True)
class EdgeLine:
    a: tuple[float, float, float]
    b: tuple[float, float, float]
    kind: str = "line"


@dataclass(frozen=True)
class EdgeCircle:
    center: tuple[float, float, float]
    normal: tuple[float, float, float]
    radius: float
    kind: str = "circle"


@dataclass(frozen=True)
class EdgeArc:
    """Elliptical/circular arc: C + cos(t)*major + sin(t)*ratio*(n̂×major)."""

    center: tuple[float, float, float]
    normal: tuple[float, float, float]
    major: tuple[float, float, float]
    ratio: float
    t0: float
    t1: float
    kind: str = "arc"


@dataclass(frozen=True)
class EdgeSpline:
    degree: int
    cps: tuple[tuple[float, float, float], ...]
    knots: tuple[float, ...] | None = None
    kind: str = "spline"


Edge = Union[EdgeLine, EdgeCircle, EdgeArc, EdgeSpline]


def _v3(p: Sequence[float] | Vec3) -> tuple[float, float, float]:
    if isinstance(p, Vec3):
        return _k((p.x, p.y, p.z))
    return _k(p)


def _edge_samples(edge: Edge, n: int = 24) -> list[tuple]:
    """Display / area helper only — not FE geometry."""
    if isinstance(edge, EdgeLine):
        return [edge.a, edge.b]
    if isinstance(edge, EdgeCircle):
        c, nrm, r = Vec3(edge.center), Vec3(edge.normal), edge.radius
        major = Vec3(r, 0, 0)
        if abs(nrm.normalize().z) < 0.9:
            major = nrm.normalize().cross(Vec3(0, 0, 1))
            if major.magnitude_square < 1e-18:
                major = nrm.normalize().cross(Vec3(0, 1, 0))
            major = major.normalize() * r
        return tessellate_ellipse(c, nrm, major, 1.0, -math.pi, math.pi, closed=True)
    if isinstance(edge, EdgeArc):
        return tessellate_ellipse(
            Vec3(edge.center),
            Vec3(edge.normal),
            Vec3(edge.major),
            edge.ratio,
            edge.t0,
            edge.t1,
            closed=abs(abs(edge.t1 - edge.t0) - 2 * math.pi) < 1e-4,
        )
    if isinstance(edge, EdgeSpline):
        cps = [Vec3(p) for p in edge.cps]
        knots = list(edge.knots) if edge.knots else None
        return tessellate_bspline(
            cps, degree=edge.degree, knots=knots, nseg=max(n, len(cps) * 8)
        )
    return []


def loop_polyline(edges: list[Edge], n: int = 24) -> list[tuple]:
    pts: list[tuple] = []
    for e in edges:
        seg = _edge_samples(e, n=n)
        if not seg:
            continue
        if not pts:
            pts.extend(seg)
        elif pts[-1] == seg[0]:
            pts.extend(seg[1:])
        else:
            pts.extend(seg)
    return _uniq_ring(pts)


def _shoelace_proj(pts: list[tuple], i: int, j: int) -> float:
    """Signed area of a 3D polyline projected onto coordinate axes (i, j)."""
    if len(pts) < 3:
        return 0.0
    a = 0.0
    n = len(pts)
    for k in range(n):
        x1, y1 = pts[k][i], pts[k][j]
        x2, y2 = pts[(k + 1) % n][i], pts[(k + 1) % n][j]
        a += x1 * y2 - x2 * y1
    return 0.5 * a


def _loop_area_score(poly: list[tuple]) -> float:
    """Largest projected |area| (XY / YZ / XZ) — robust for Y- or Z-facing shells."""
    if len(poly) < 3:
        return 0.0
    return max(
        abs(_shoelace_area_xy(poly)),
        abs(_shoelace_proj(poly, 1, 2)),
        abs(_shoelace_proj(poly, 0, 2)),
    )


def order_curve_loops(loops: list[list[Edge]]) -> list[list[Edge]]:
    """Largest loop first (outer), then holes — by projected area."""
    scored = []
    for edges in loops:
        if not edges:
            continue
        poly = loop_polyline(edges, n=32)
        if len(poly) < 3 and not (
            len(edges) == 1 and isinstance(edges[0], EdgeCircle)
        ):
            continue
        if len(poly) >= 3:
            area = _loop_area_score(poly)
        else:
            area = (
                math.pi * edges[0].radius ** 2
                if isinstance(edges[0], EdgeCircle)
                else 0.0
            )
        scored.append((area, edges))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [e for _, e in scored]


def _edge_from_sab(
    records: dict[int, dict],
    ed: dict[str, Any],
    sense: bool,
) -> Edge | None:
    sp = _sab_vertex_point(records, ed["start_vtx"])
    ep = _sab_vertex_point(records, ed["end_vtx"])
    t0, t1 = float(ed["t0"]), float(ed["t1"])
    if sense:
        sp, ep = ep, sp
        t0, t1 = t1, t0
    cid = ed.get("curve")
    ctype = records.get(cid, {}).get("type") if cid else None
    if ctype == "straight-curve" or ctype is None:
        if sp.distance(ep) < 1e-9:
            return None
        return EdgeLine(_v3(sp), _v3(ep))
    if ctype == "ellipse-curve":
        ell = _ellipse_from_record(records[cid])
        if ell is None:
            return EdgeLine(_v3(sp), _v3(ep)) if sp.distance(ep) > 1e-9 else None
        center, normal, major, ratio = ell
        closed = sp.distance(ep) < 1e-6
        full = closed or abs(abs(t1 - t0) - 2 * math.pi) < 1e-3
        if full and abs(ratio - 1.0) < 1e-6:
            r = float(major.magnitude)
            n = normal if normal.magnitude_square > 1e-18 else Vec3(0, 0, 1)
            return EdgeCircle(_v3(center), _v3(n.normalize()), r)
        if sense:
            # keep t0,t1 already swapped; major/normal unchanged
            pass
        return EdgeArc(
            _v3(center),
            _v3(normal),
            _v3(major),
            float(ratio),
            float(t0),
            float(t1),
        )
    if ctype == "intcurve-curve":
        # sp/ep already match coedge traversal (sense applied above).
        # Align NUBS to those ends; never reverse again by sense (that double-flipped
        # bottoms of Z-extruded faces and drew a spurious chord).
        aligned = _nubs_cps_aligned(records[cid], sp, ep)
        if aligned is None and _intcurve_is_ref_only(records[cid]):
            # Opposite extrusion end often stored as ACIS ref → copy+translate sibling
            aligned = _nubs_cps_from_ref_intcurve(records, int(cid), sp, ep)
        if aligned is None:
            return EdgeLine(_v3(sp), _v3(ep)) if sp.distance(ep) > 1e-9 else None
        degree, cps, knots = aligned
        if not cps:
            return None
        if Vec3(cps[0]).distance(sp) > Vec3(cps[0]).distance(ep):
            cps = list(reversed(cps))
            if knots:
                lo, hi = knots[0], knots[-1]
                knots = [lo + hi - k for k in reversed(knots)]
        # Snap ends to coedge vertices so TeX path joins without a jump chord
        cps = list(cps)
        cps[0] = sp
        cps[-1] = ep
        kt = tuple(float(k) for k in knots) if knots else None
        return EdgeSpline(int(degree), tuple(_v3(p) for p in cps), knots=kt)
    return EdgeLine(_v3(sp), _v3(ep)) if sp.distance(ep) > 1e-9 else None


def _curve_loop_from_sab(records: dict[int, dict], loop_id: int) -> list[Edge]:
    rec = records.get(loop_id)
    if not rec:
        return []
    ptrs = _field_ptrs(rec)
    start_co = next(
        (
            p
            for p in ptrs
            if p is not None and records.get(p, {}).get("type") == "coedge"
        ),
        None,
    )
    if start_co is None:
        return []
    edges: list[Edge] = []
    cid = start_co
    seen: set[int] = set()
    while cid is not None and cid not in seen:
        seen.add(cid)
        co = _sab_coedge(records, cid)
        if co is None or co["edge"] is None:
            break
        ed = _sab_edge(records, co["edge"])
        if ed is None:
            break
        edge = _edge_from_sab(records, ed, bool(co["sense"]))
        if edge is not None:
            edges.append(edge)
        cid = co["next"]
        if cid == start_co:
            break
    return edges


def _sab_face_surface(
    records: dict[int, dict], face_id: int
) -> tuple[int | None, str | None, dict | None]:
    """Return (surf_id, surf_type, surf_rec) for a SAB face."""
    rec = records.get(face_id)
    if not rec:
        return None, None, None
    for p in _field_ptrs(rec):
        if p is None or p not in records:
            continue
        t = records[p].get("type") or ""
        if t.endswith("-surface"):
            return p, t, records[p]
    return None, None, None


def _loops_are_full_circles(loops: list[list[Edge]]) -> bool:
    """True only for a pipe mantle bounded by two full circular wires."""
    if len(loops) != 2:
        return False
    for edges in loops:
        if len(edges) != 1:
            return False
        e0 = edges[0]
        if isinstance(e0, EdgeCircle):
            continue
        if isinstance(e0, EdgeArc) and abs(abs(e0.t1 - e0.t0) - 2 * math.pi) < 1e-2:
            continue
        return False
    return True


def _cone_cylinder_params(
    surf_rec: dict,
) -> tuple[Vec3, Vec3, float] | None:
    """Return (origin, unit axis, radius) for a cylindrical cone-surface."""
    locs = [v for k, v in surf_rec["fields"] if k == "LOCATION_VEC"]
    dirs = [v for k, v in surf_rec["fields"] if k == "DIRECTION_VEC"]
    dbls = [float(v) for k, v in surf_rec["fields"] if k == "DOUBLE"]
    if not locs or len(dirs) < 1:
        return None
    origin = Vec3(locs[0])
    axis = Vec3(dirs[0])
    if axis.magnitude_square < 1e-18:
        return None
    axis = axis.normalize()
    ratio = dbls[0] if len(dbls) > 0 else 1.0
    sine = dbls[1] if len(dbls) > 1 else 0.0
    cosine = dbls[2] if len(dbls) > 2 else 1.0
    radius = dbls[3] if len(dbls) > 3 else (
        float(Vec3(dirs[1]).magnitude) if len(dirs) > 1 else 0.0
    )
    if abs(sine) > 1e-6 or abs(abs(cosine) - 1.0) > 1e-3:
        return None
    if abs(ratio - 1.0) > 1e-3 or radius <= 1e-9:
        return None
    return origin, axis, float(radius)


def _parse_cone_as_cylinder(
    surf_rec: dict, loops: list[list[Edge]]
) -> dict[str, Any] | None:
    """Full closed cylinder only (two circular end wires). Partial cones → None."""
    if not _loops_are_full_circles(loops):
        return None
    mesh = _cone_mesh_params(surf_rec, loops)
    if mesh is None:
        return None
    # Drop angle keys for legacy full-cylinder callers
    return {
        "origin": mesh["origin"],
        "axis": mesh["axis"],
        "radius": mesh["radius"],
        "h0": mesh["h0"],
        "h1": mesh["h1"],
    }


def _cyl_basis(axis: Vec3) -> tuple[Vec3, Vec3]:
    ref = Vec3(0, 0, 1) if abs(axis.z) < 0.9 else Vec3(1, 0, 0)
    u = axis.cross(ref)
    if u.magnitude_square < 1e-18:
        u = axis.cross(Vec3(0, 1, 0))
    u = u.normalize()
    v = axis.cross(u).normalize()
    return u, v


def _angle_span(angs: list[float]) -> tuple[float, float]:
    """Contiguous angular span covering samples (radians, possibly th1 < th0+2π)."""
    if not angs:
        return -math.pi, math.pi
    sx = sum(math.cos(t) for t in angs)
    sy = sum(math.sin(t) for t in angs)
    if sx * sx + sy * sy < 1e-18:
        return -math.pi, math.pi
    mid = math.atan2(sy, sx)
    rel = [math.atan2(math.sin(t - mid), math.cos(t - mid)) for t in angs]
    return mid + min(rel), mid + max(rel)


def _cone_mesh_params(
    surf_rec: dict, loops: list[list[Edge]]
) -> dict[str, Any] | None:
    """Cylinder mesh params from cone-surface + boundary samples (full or partial)."""
    parsed = _cone_cylinder_params(surf_rec)
    if parsed is None:
        return None
    origin, axis, radius = parsed
    u, v = _cyl_basis(axis)
    heights: list[float] = []
    angles: list[float] = []
    for edges in loops:
        for p in loop_polyline(edges, n=48):
            w = Vec3(p) - origin
            h = float(w.dot(axis))
            heights.append(h)
            radial = w - axis * h
            if radial.magnitude_square > 1e-12:
                angles.append(
                    math.atan2(float(radial.dot(v)), float(radial.dot(u)))
                )
    if len(heights) < 2:
        return None
    h0, h1 = min(heights), max(heights)
    if abs(h1 - h0) < 1e-9:
        return None
    th0, th1 = _angle_span(angles)
    if abs(th1 - th0) < 1e-6:
        th0, th1 = -math.pi, math.pi
    # Near-full turn → treat as closed
    if abs(th1 - th0) > 2 * math.pi - 0.15:
        th0, th1 = -math.pi, math.pi
    return {
        "origin": _v3(origin),
        "axis": _v3(axis),
        "radius": float(radius),
        "h0": float(h0),
        "h1": float(h1),
        "th0": float(th0),
        "th1": float(th1),
    }


_PLANE_MESH_U = 2
_PLANE_MESH_V = 2


def _plane_frame(
    loops: list[list[Edge]],
) -> tuple[Vec3, Vec3, Vec3, list[tuple[float, float]]] | None:
    """Origin + orthonormal u,v in plane + outer ring in UV."""
    if not loops:
        return None
    poly = loop_polyline(loops[0], n=64)
    if len(poly) < 3:
        return None
    # Newell normal
    nx = ny = nz = 0.0
    for i in range(len(poly)):
        a, b = Vec3(poly[i]), Vec3(poly[(i + 1) % len(poly)])
        nx += (a.y - b.y) * (a.z + b.z)
        ny += (a.z - b.z) * (a.x + b.x)
        nz += (a.x - b.x) * (a.y + b.y)
    n = Vec3(nx, ny, nz)
    if n.magnitude_square < 1e-18:
        return None
    n = n.normalize()
    origin = Vec3(
        sum(p[0] for p in poly) / len(poly),
        sum(p[1] for p in poly) / len(poly),
        sum(p[2] for p in poly) / len(poly),
    )
    u, v = _cyl_basis(n)
    uv = [
        (
            float((Vec3(p) - origin).dot(u)),
            float((Vec3(p) - origin).dot(v)),
        )
        for p in poly
    ]
    return origin, u, v, uv


def _poly_line_hits(
    uv: list[tuple[float, float]], *, const: float, horizontal: bool
) -> list[float]:
    """Sorted intersection parameters along the other axis.

    ``uv`` may be open (implicit close) or already closed (last≈first).
    """
    hits: list[float] = []
    n = len(uv)
    if n < 2:
        return []
    closed = (
        abs(uv[0][0] - uv[-1][0]) < 1e-12 and abs(uv[0][1] - uv[-1][1]) < 1e-12
    )
    n_seg = n - 1 if closed else n
    for i in range(n_seg):
        u0, v0 = uv[i]
        u1, v1 = uv[i + 1] if closed else uv[(i + 1) % n]
        if horizontal:
            a0, a1, b0, b1 = v0, v1, u0, u1
        else:
            a0, a1, b0, b1 = u0, u1, v0, v1
        da = a1 - a0
        if abs(da) < 1e-15:
            continue
        t = (const - a0) / da
        if t < -1e-9 or t > 1.0 + 1e-9:
            continue
        if t < 0.0:
            t = 0.0
        if t > 1.0:
            t = 1.0
        hits.append(b0 + t * (b1 - b0))
    hits.sort()
    out: list[float] = []
    for h in hits:
        if not out or abs(h - out[-1]) > 1e-7:
            out.append(h)
    return out


def _loop_uv_poly(
    edges: list[Edge],
    origin: Vec3,
    u_ax: Vec3,
    v_ax: Vec3,
    n: int = 64,
) -> list[tuple[float, float]]:
    """Project a boundary loop into the plane UV frame."""
    poly = loop_polyline(edges, n=n)
    if len(poly) < 3:
        return []
    return [
        (
            float((Vec3(p) - origin).dot(u_ax)),
            float((Vec3(p) - origin).dot(v_ax)),
        )
        for p in poly
    ]


def _plane_mesh_segs(
    loops: list[list[Edge]],
    nu: int = _PLANE_MESH_U,
    nv: int = _PLANE_MESH_V,
) -> list[tuple[tuple, tuple]]:
    """Interior UV grid clipped to outer polygon minus holes (display only)."""
    frame = _plane_frame(loops)
    if frame is None:
        return []
    origin, u_ax, v_ax, uv = frame
    us = [p[0] for p in uv]
    vs = [p[1] for p in uv]
    umin, umax = min(us), max(us)
    vmin, vmax = min(vs), max(vs)
    if umax - umin < 1e-9 or vmax - vmin < 1e-9:
        return []
    hole_uvs = [
        huv
        for hole in loops[1:]
        if len(huv := _loop_uv_poly(hole, origin, u_ax, v_ax)) >= 3
    ]
    # Inset outer / expand holes slightly so isolines clear trim curves
    eps_u = max(1e-4, 0.004 * (umax - umin))
    eps_v = max(1e-4, 0.004 * (vmax - vmin))
    segs: list[tuple[tuple, tuple]] = []

    def _emit_spans(
        spans: list[tuple[float, float]], *, horizontal: bool, const: float
    ) -> None:
        for a, b in spans:
            if abs(b - a) < 1e-7:
                continue
            if horizontal:
                p0 = origin + u_ax * a + v_ax * const
                p1 = origin + u_ax * b + v_ax * const
            else:
                p0 = origin + u_ax * const + v_ax * a
                p1 = origin + u_ax * const + v_ax * b
            segs.append((_v3(p0), _v3(p1)))

    def _clipped_spans(
        outer_hits: list[float],
        hole_hits_list: list[list[float]],
        eps: float,
    ) -> list[tuple[float, float]]:
        spans = _inset_spans(_hits_to_spans(outer_hits), eps)
        for hh in hole_hits_list:
            hole_sp = [
                (a - eps, b + eps) for a, b in _hits_to_spans(hh)
            ]
            spans = _clip_intervals_subtract(spans, hole_sp)
        return spans

    for k in range(1, max(nu, 0) + 1):
        uu = umin + (umax - umin) * k / (nu + 1)
        spans = _clipped_spans(
            _poly_line_hits(uv, const=uu, horizontal=False),
            [
                _poly_line_hits(huv, const=uu, horizontal=False)
                for huv in hole_uvs
            ],
            eps_v,
        )
        _emit_spans(spans, horizontal=False, const=uu)
    for k in range(1, max(nv, 0) + 1):
        vv = vmin + (vmax - vmin) * k / (nv + 1)
        spans = _clipped_spans(
            _poly_line_hits(uv, const=vv, horizontal=True),
            [
                _poly_line_hits(huv, const=vv, horizontal=True)
                for huv in hole_uvs
            ],
            eps_u,
        )
        _emit_spans(spans, horizontal=True, const=vv)
    return segs


def faces_from_sab(entity) -> list[dict[str, Any]]:
    """One analytic face dict per SAB face.

    Display is AutoCAD-style wire mesh (no fill):
      - plane-surface → ``plane`` (boundary + UV grid)
      - cone-surface (full or partial cylinder) → ``cylinder`` (arc rings + gens)
      - spline-surface with 4-edge ruled loop → ``ruled`` (curved latitudes)
      - other spline-surface → ``wire`` (boundary only; AutoCAD often skips mesh)
    FE always keeps boundary edge equations.
    """
    sab = getattr(entity, "sab", None) or getattr(entity, "acis_data", None)
    if not sab:
        return []
    try:
        records = _parse_sab_records(sab)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for face_id in [rid for rid, r in records.items() if r["type"] == "face"]:
        loops: list[list[Edge]] = []
        for loop_id in _sab_loop_list(records, face_id):
            edges = _curve_loop_from_sab(records, loop_id)
            if edges:
                loops.append(edges)
        if not loops:
            continue
        loops = order_curve_loops(loops)
        _sid, stype, srec = _sab_face_surface(records, face_id)
        if stype == "cone-surface" and srec is not None:
            mesh = _cone_mesh_params(srec, loops)
            if mesh is not None:
                mid = 0.5 * (mesh["h0"] + mesh["h1"])
                o, a = Vec3(mesh["origin"]), Vec3(mesh["axis"])
                cen = o + a * mid
                out.append(
                    {
                        "kind": "cylinder",
                        "loops": loops,
                        "cen": _v3(cen),
                        **mesh,
                    }
                )
                continue
            cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
            out.append({"kind": "wire", "loops": loops, "cen": _k(cen)})
            continue
        if stype == "plane-surface":
            cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
            out.append({"kind": "plane", "loops": loops, "cen": _k(cen)})
            continue
        # spline-surface: ruled / extrusion strip (curved latitudes); holes OK
        if stype == "spline-surface" and loops and (
            _is_ruled_loop(loops[0]) or _extract_extrusion_rails(loops[0]) is not None
        ):
            cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
            out.append({"kind": "ruled", "loops": loops, "cen": _k(cen)})
            continue
        cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
        out.append({"kind": "wire", "loops": loops, "cen": _k(cen)})
    return out


def curves_from_region(entity) -> list[list[Edge]]:
    """Legacy: flatten all SAB face loops (planar even-odd). Prefer faces_from_sab."""
    faces = faces_from_sab(entity)
    loops: list[list[Edge]] = []
    for f in faces:
        if f.get("kind") == "cylinder":
            # lateral area helpers: keep end circles as loops for extent only
            loops.extend(f.get("loops") or [])
        else:
            loops.extend(f.get("loops") or [])
    return order_curve_loops(loops)


def analytic_faces_from_entity(e) -> list[dict[str, Any]]:
    """Primary export API — two display paths (AutoCAD-like):

    - REGION / planar curve entities → ``kind=region`` (even-odd fill, no mesh)
    - SURFACE / 3DSOLID / BODY → cylinder / ruled / plane mesh + wire
    """
    t = e.dxftype()
    if t == "REGION":
        out: list[dict[str, Any]] = []
        for f in faces_from_sab(e):
            loops = order_curve_loops(f.get("loops") or [])
            if not loops:
                continue
            cen = f.get("cen") or curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
            out.append({"kind": "region", "loops": loops, "cen": _k(cen)})
        return out
    if t in (
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
        return faces_from_sab(e)
    loops = face_curve_loops_from_entity(e)
    if not loops:
        return []
    cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
    # Closed planar curves (CIRCLE / LWPOLYLINE / HATCH / …) — fill like REGION
    return [{"kind": "region", "loops": loops, "cen": _k(cen)}]


def _poly_to_lines(pts: list[tuple]) -> list[Edge]:
    ring = _uniq_ring(pts)
    if len(ring) < 3:
        return []
    out = []
    for i in range(len(ring)):
        out.append(EdgeLine(ring[i], ring[(i + 1) % len(ring)]))
    return out


def face_curve_loops_from_entity(e) -> list[list[Edge]]:
    """Primary API: exact-curve loops, outer first."""
    t = e.dxftype()
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
        return curves_from_region(e)
    if t == "CIRCLE":
        c = Vec3(e.dxf.center)
        r = float(e.dxf.radius)
        n = Vec3(e.dxf.extrusion) if hasattr(e.dxf, "extrusion") else Vec3(0, 0, 1)
        if n.magnitude_square < 1e-18:
            n = Vec3(0, 0, 1)
        return [[EdgeCircle(_v3(c), _v3(n.normalize()), r)]]
    if t == "ARC":
        # single open arc is not a face; skip unless closed somehow
        return []
    if t == "ELLIPSE":
        c = Vec3(e.dxf.center)
        major = Vec3(e.dxf.major_axis)
        ratio = float(e.dxf.ratio)
        n = Vec3(e.dxf.extrusion) if hasattr(e.dxf, "extrusion") else Vec3(0, 0, 1)
        try:
            a0 = float(e.start_param)
            a1 = float(e.end_param)
        except Exception:
            a0, a1 = 0.0, 2 * math.pi
        if abs(abs(a1 - a0) - 2 * math.pi) < 1e-3 or abs(a1 - a0) > 2 * math.pi - 1e-3:
            if abs(ratio - 1.0) < 1e-6:
                return [[EdgeCircle(_v3(c), _v3(n.normalize()), float(major.magnitude))]]
            return [
                [
                    EdgeArc(
                        _v3(c), _v3(n), _v3(major), ratio, -math.pi, math.pi
                    )
                ]
            ]
        return [[EdgeArc(_v3(c), _v3(n), _v3(major), ratio, a0, a1)]]
    if t == "SPLINE":
        try:
            cps = tuple(_v3(p) for p in e.control_points)
            deg = int(e.dxf.degree)
            if len(cps) >= 2 and bool(getattr(e, "closed", False)):
                return [[EdgeSpline(deg, cps)]]
        except Exception:
            pass
        # fall back to polyline lines only if closed flattening exists
        lp = loop_from_spline(e)
        return [ _poly_to_lines(lp) ] if lp else []
    if t == "LWPOLYLINE":
        # Prefer bulge arcs as EdgeArc when possible; else line chain
        if not bool(e.closed):
            return []
        elev = float(getattr(e.dxf, "elevation", 0.0) or 0.0)
        edges: list[Edge] = []
        try:
            pts = list(e.get_points("xyb"))
        except Exception:
            lp = loop_from_lwpolyline(e)
            return [_poly_to_lines(lp)] if lp else []
        n = len(pts)
        for i in range(n):
            x0, y0, b = pts[i][0], pts[i][1], float(pts[i][2])
            x1, y1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
            a = _v3((x0, y0, elev))
            c = _v3((x1, y1, elev))
            if abs(b) < 1e-12:
                edges.append(EdgeLine(a, c))
            else:
                # bulge b = tan(Δ/4); reconstruct circular arc in XY
                ang = 4.0 * math.atan(b)
                chord = Vec3(x1 - x0, y1 - y0, 0)
                clen = chord.magnitude
                if clen < 1e-12:
                    continue
                s = math.sin(ang / 2.0)
                if abs(s) < 1e-12:
                    edges.append(EdgeLine(a, c))
                    continue
                radius = clen / (2.0 * s)
                # mid chord → centre
                mid = Vec3((x0 + x1) / 2, (y0 + y1) / 2, elev)
                # perpendicular in plane
                perp = Vec3(-chord.y, chord.x, 0).normalize()
                h = math.cos(ang / 2.0) * radius
                # sign of bulge
                centre = mid + perp * (h if b > 0 else -h)
                # angles
                v0 = Vec3(x0, y0, elev) - centre
                v1 = Vec3(x1, y1, elev) - centre
                t0 = math.atan2(v0.y, v0.x)
                t1 = math.atan2(v1.y, v1.x)
                if b > 0 and t1 < t0:
                    t1 += 2 * math.pi
                if b < 0 and t1 > t0:
                    t1 -= 2 * math.pi
                major = Vec3(radius, 0, 0)
                edges.append(
                    EdgeArc(
                        _v3(centre),
                        (0.0, 0.0, 1.0),
                        _v3(major),
                        1.0,
                        t0,
                        t1,
                    )
                )
        return order_curve_loops([edges]) if edges else []
    if t in ("3DFACE", "MESH"):
        loops = loops_from_mesh_entity(e)
        return [_poly_to_lines(lp) for lp in loops if lp]
    if t == "HATCH":
        loops = loops_from_hatch(e)
        return [_poly_to_lines(lp) for lp in order_outer_then_holes(loops)]
    return []


def _fmt_xyz(p: tuple[float, float, float]) -> str:
    return f"{p[0]:.6g},{p[1]:.6g},{p[2]:.6g}"


def format_stp_dface_curves(loops: list[list[Edge]]) -> list[str]:
    """TeX lines: equation-preserving planar face (no boundary node cloud)."""
    if not loops:
        return []
    L = ["  \\begin{stpDfaceEnv}"]
    for edges in loops:
        L.append("    \\begin{stpDfaceLoop}")
        for e in edges:
            if isinstance(e, EdgeLine):
                L.append(
                    f"      \\stpDedgeLine{{{_fmt_xyz(e.a)}}}{{{_fmt_xyz(e.b)}}}"
                )
            elif isinstance(e, EdgeCircle):
                L.append(
                    f"      \\stpDedgeCircle{{{_fmt_xyz(e.center)}}}"
                    f"{{{_fmt_xyz(e.normal)}}}{{{e.radius:.6g}}}"
                )
            elif isinstance(e, EdgeArc):
                L.append(
                    f"      \\stpDedgeArc{{{_fmt_xyz(e.center)}}}"
                    f"{{{_fmt_xyz(e.normal)}}}{{{_fmt_xyz(e.major)}}}"
                    f"{{{e.ratio:.6g}}}{{{e.t0:.8g}}}{{{e.t1:.8g}}}"
                )
            elif isinstance(e, EdgeSpline):
                L.append(_emit_edge_tex(e, indent="      "))
        L.append("    \\end{stpDfaceLoop}")
    L.append("  \\end{stpDfaceEnv}")
    return L


def _spline_disp_pts(e: EdgeSpline, nseg: int | None = None) -> list[tuple]:
    """B-spline samples for PDF display (not control-polygon chords)."""
    cps = [Vec3(p) for p in e.cps]
    if len(cps) < 2:
        return [_v3(p) for p in e.cps]
    n = nseg if nseg is not None else max(96, len(cps) * 12)
    knots = list(e.knots) if e.knots else None
    return tessellate_bspline(cps, degree=int(e.degree), knots=knots, nseg=n)


def _emit_edge_tex(e: Edge, indent: str = "      ", *, display: bool = True) -> str:
    if isinstance(e, EdgeLine):
        return f"{indent}\\stpDedgeLine{{{_fmt_xyz(e.a)}}}{{{_fmt_xyz(e.b)}}}"
    if isinstance(e, EdgeCircle):
        return (
            f"{indent}\\stpDedgeCircle{{{_fmt_xyz(e.center)}}}"
            f"{{{_fmt_xyz(e.normal)}}}{{{e.radius:.6g}}}"
        )
    if isinstance(e, EdgeArc):
        return (
            f"{indent}\\stpDedgeArc{{{_fmt_xyz(e.center)}}}"
            f"{{{_fmt_xyz(e.normal)}}}{{{_fmt_xyz(e.major)}}}"
            f"{{{e.ratio:.6g}}}{{{e.t0:.8g}}}{{{e.t1:.8g}}}"
        )
    if isinstance(e, EdgeSpline):
        # EQUATION: degree + control points; optional [samples] for smooth display
        cps = ",".join("{" + _fmt_xyz(p) + "}" for p in e.cps)
        if not display:
            return f"{indent}\\stpDedgeSpline{{{e.degree}}}{{{cps}}}"
        disp = ",".join("{" + _fmt_xyz(p) + "}" for p in _spline_disp_pts(e))
        return f"{indent}\\stpDedgeSpline{{{e.degree}}}{{{cps}}}[{disp}]"
    return ""


def _emit_plane_mesh(
    loops: list[list[Edge]],
    nu: int | None = None,
    nv: int | None = None,
) -> list[str]:
    """Interior UV grid segments for a planar face (display only)."""
    L: list[str] = []
    for a, b in _plane_mesh_segs(
        loops,
        nu=_PLANE_MESH_U if nu is None else int(nu),
        nv=_PLANE_MESH_V if nv is None else int(nv),
    ):
        L.append(f"  \\stpDmeshSeg{{{_fmt_xyz(a)}}}{{{_fmt_xyz(b)}}}")
    return L


_CYL_MESH_GEN = 16
_CYL_MESH_RING = 6


def _cyl_th_h(
    p: Sequence[float] | Vec3,
    origin: Vec3,
    axis: Vec3,
    u: Vec3,
    v: Vec3,
) -> tuple[float, float]:
    w = Vec3(p) - origin
    h = float(w.dot(axis))
    radial = w - axis * h
    th = math.atan2(float(radial.dot(v)), float(radial.dot(u)))
    return th, h


def _unwrap_theta_chain(ths: list[float]) -> list[float]:
    if not ths:
        return []
    out = [ths[0]]
    for t in ths[1:]:
        prev = out[-1]
        while t - prev > math.pi:
            t -= 2 * math.pi
        while t - prev < -math.pi:
            t += 2 * math.pi
        out.append(t)
    return out


def _cylinder_mesh_segs(
    face: dict[str, Any],
    ngen: int = _CYL_MESH_GEN,
    nring: int = _CYL_MESH_RING,
) -> list[tuple[tuple, tuple]]:
    """Isolines clipped to the trimmed face in (θ, h) — avoids phantom patches."""
    origin = Vec3(face["origin"])
    axis = Vec3(face["axis"])
    if axis.magnitude_square < 1e-18:
        return []
    axis = axis.normalize()
    radius = float(face["radius"])
    u, v = _cyl_basis(axis)
    loops = face.get("loops") or []
    if not loops:
        return []

    # Parameter polygons from SAB boundary edges (outer + holes)
    def _loop_th_h(edges: list[Edge]) -> list[tuple[float, float]]:
        pts3: list[tuple] = []
        for e in edges:
            seg = _edge_boundary_samples(e)
            if not seg:
                continue
            if not pts3:
                pts3.extend(seg)
            elif pts3[-1] == seg[0]:
                pts3.extend(seg[1:])
            else:
                pts3.extend(seg)
        pts3 = _uniq_ring(pts3)
        if len(pts3) < 3:
            return []
        raw = [_cyl_th_h(p, origin, axis, u, v) for p in pts3]
        ths = _unwrap_theta_chain([t for t, _ in raw])
        uv = list(zip(ths, [h for _, h in raw]))
        if abs(uv[0][0] - uv[-1][0]) > 1e-9 or abs(uv[0][1] - uv[-1][1]) > 1e-9:
            uv = list(uv) + [uv[0]]
        return uv

    loop_uvs = [_loop_th_h(edges) for edges in loops]
    loop_uvs = [uv for uv in loop_uvs if len(uv) >= 3]
    if not loop_uvs:
        return []
    # Largest loop = outer; remaining = holes (order_curve_loops usually already)
    loop_uvs.sort(key=len, reverse=True)
    best = loop_uvs[0]
    hole_uvs = loop_uvs[1:]

    ths = [p[0] for p in best]
    hs = [p[1] for p in best]
    th_min, th_max = min(ths), max(ths)
    h_min, h_max = min(hs), max(hs)
    if th_max - th_min < 1e-6 or h_max - h_min < 1e-6:
        return []

    segs: list[tuple[tuple, tuple]] = []

    def _to_xyz(th: float, h: float) -> tuple:
        p = origin + axis * h + u * (radius * math.cos(th)) + v * (
            radius * math.sin(th)
        )
        return _v3(p)

    # Slight inset so isolines stop inside SAB intersection / trim curves
    eps_th = max(1e-4, 0.004 * (th_max - th_min))
    eps_h = max(1e-4, 0.004 * (h_max - h_min))

    def _emit_spans(
        spans: list[tuple[float, float]], *, horizontal: bool, const: float
    ) -> None:
        # horizontal=True: const is h, spans are theta — sample the CIRCULAR
        # arc (not a single chord). Generators stay straight in h.
        for a, b in spans:
            if b - a < 1e-7:
                continue
            if horizontal:
                nsub = max(8, int(round(abs(b - a) / (2 * math.pi) * 48)))
                prev = _to_xyz(a, const)
                for s in range(1, nsub + 1):
                    th = a + (b - a) * s / nsub
                    cur = _to_xyz(th, const)
                    segs.append((prev, cur))
                    prev = cur
            else:
                segs.append((_to_xyz(const, a), _to_xyz(const, b)))

    def _clipped(
        outer_hits: list[float],
        hole_hits_list: list[list[float]],
        eps: float,
    ) -> list[tuple[float, float]]:
        spans = _inset_spans(_hits_to_spans(outer_hits), eps)
        for hh in hole_hits_list:
            hole_sp = [(a - eps, b + eps) for a, b in _hits_to_spans(hh)]
            spans = _clip_intervals_subtract(spans, hole_sp)
        return spans

    # Generators: constant θ (vertical in (θ,h) → horizontal=False)
    th_samples = [
        th_min + (th_max - th_min) * k / max(ngen, 1) for k in range(ngen + 1)
    ]
    span = th_max - th_min
    if span > 1e-6:
        for f in (0.92, 0.96, 0.98):
            th_samples.append(th_min + span * f)
    for th in th_samples:
        spans = _clipped(
            _poly_line_hits(best, const=th, horizontal=False),
            [
                _poly_line_hits(huv, const=th, horizontal=False)
                for huv in hole_uvs
            ],
            eps_h,
        )
        _emit_spans(spans, horizontal=False, const=th)
    # Rings: constant h (skip exact ends — boundary wire draws those)
    h_samples = [
        h_min + (h_max - h_min) * k / nring for k in range(1, max(nring, 1))
    ]
    for edges in loops:
        for e in edges:
            if isinstance(e, EdgeLine):
                continue
            hs_e = [
                float((Vec3(p) - origin).dot(axis))
                for p in _edge_samples(e, n=8)
            ]
            if len(hs_e) < 2:
                continue
            lo, hi = min(hs_e), max(hs_e)
            if not (h_min + 1e-3 < lo and hi < h_max - 1e-3):
                continue
            if hi - lo < 1e-3:
                h_samples.append(0.5 * (lo + hi))
            else:
                h_samples.extend(
                    [lo + (hi - lo) * t for t in (0.25, 0.5, 0.75)]
                )
    for hh in h_samples:
        spans = _clipped(
            _poly_line_hits(best, const=hh, horizontal=True),
            [
                _poly_line_hits(huv, const=hh, horizontal=True)
                for huv in hole_uvs
            ],
            eps_th,
        )
        _emit_spans(spans, horizontal=True, const=hh)

    # Drop fragments that leave the SAB trim in (θ, h), including holes
    def _th_in(p: tuple) -> bool:
        th, hh = _cyl_th_h(p, origin, axis, u, v)
        while th < th_min - 1e-9:
            th += 2 * math.pi
        while th > th_max + 1e-9:
            th -= 2 * math.pi
        if not _pip2(th, hh, best):
            return False
        for huv in hole_uvs:
            if _pip2(th, hh, huv):
                return False
        return True

    kept: list[tuple[tuple, tuple]] = []
    for a, b in segs:
        va, vb = Vec3(a), Vec3(b)
        if va.distance(vb) < 1e-12:
            continue
        fa, fb = _th_in(a), _th_in(b)
        mid = _v3(va * 0.5 + vb * 0.5)
        fm = _th_in(mid)
        if fa and fb and fm:
            kept.append((a, b))
            continue
        if not fa and not fb and not fm:
            continue
        nsub = 8
        flags: list[bool] = []
        pts: list[tuple] = []
        for k in range(nsub + 1):
            t = k / nsub
            p = _v3(va * (1.0 - t) + vb * t)
            pts.append(p)
            flags.append(_th_in(p))
        i = 0
        while i <= nsub:
            while i <= nsub and not flags[i]:
                i += 1
            if i > nsub:
                break
            j = i
            while j <= nsub and flags[j]:
                j += 1
            if j - 1 > i:
                kept.append((pts[i], pts[j - 1]))
            i = j
    return kept


def _emit_cylinder_mesh(face: dict[str, Any]) -> list[str]:
    """Generators + circular rings clipped to face trim (display only)."""
    L: list[str] = []
    for a, b in _cylinder_mesh_segs(face):
        L.append(f"  \\stpDmeshSeg{{{_fmt_xyz(a)}}}{{{_fmt_xyz(b)}}}")
    return L


def _resample_polyline(pts: list[tuple], n: int) -> list[tuple]:
    """Arc-length resample to n points (inclusive ends)."""
    if n < 2 or len(pts) < 2:
        return list(pts)
    vs = [Vec3(p) for p in pts]
    seg_lens = [vs[i].distance(vs[i + 1]) for i in range(len(vs) - 1)]
    total = sum(seg_lens)
    if total < 1e-12:
        return [_v3(vs[0])] * n
    out: list[tuple] = []
    for k in range(n):
        target = total * k / (n - 1)
        acc = 0.0
        placed = False
        for i, sl in enumerate(seg_lens):
            if acc + sl >= target - 1e-12 or i == len(seg_lens) - 1:
                t = 0.0 if sl < 1e-15 else (target - acc) / sl
                t = max(0.0, min(1.0, t))
                out.append(_v3(vs[i] + (vs[i + 1] - vs[i]) * t))
                placed = True
                break
            acc += sl
        if not placed:
            out.append(_v3(vs[-1]))
    out[0] = _v3(vs[0])
    out[-1] = _v3(vs[-1])
    return out


def _is_ruled_loop(edges: list[Edge]) -> bool:
    """True for a 4-edge loop: curve, line, curve, line (ruled strip)."""
    if len(edges) != 4:
        return False
    lines = [isinstance(e, EdgeLine) for e in edges]
    # Alternating: line at odd or even indices
    if lines == [False, True, False, True]:
        return True
    if lines == [True, False, True, False]:
        return True
    return False


def _chain_edge_samples(edges: list[Edge], n_per: int = 24) -> list[tuple]:
    """Sample one or more connected edges into a single polyline."""
    if not edges:
        return []
    if len(edges) == 1:
        return _edge_samples(edges[0], n=n_per)
    # Greedy chain by nearest endpoint
    remaining = list(edges)
    cur = remaining.pop(0)
    pts = list(_edge_samples(cur, n=n_per))
    while remaining:
        end = Vec3(pts[-1])
        best_i, best_rev, best_d = 0, False, float("inf")
        for i, e in enumerate(remaining):
            s = _edge_samples(e, n=max(4, n_per // 4))
            if not s:
                continue
            d0 = end.distance(Vec3(s[0]))
            d1 = end.distance(Vec3(s[-1]))
            if d0 < best_d:
                best_i, best_rev, best_d = i, False, d0
            if d1 < best_d:
                best_i, best_rev, best_d = i, True, d1
        e = remaining.pop(best_i)
        s = _edge_samples(e, n=n_per)
        if best_rev:
            s = list(reversed(s))
        if pts and s and pts[-1] == s[0]:
            pts.extend(s[1:])
        else:
            pts.extend(s)
    return pts


def _extract_extrusion_rails(
    edges: list[Edge],
    n_rail: int = 48,
) -> tuple[list[tuple], list[tuple], Vec3] | None:
    """End rails of an extrusion-like loop (gens along a shared axis).

    Supports simple 4-cycles and notched boundaries (extra mid-height edges).
    Returns (rail_a, rail_b, axis) with rails oriented so A[0]↔B[0].
    """
    gens: list[tuple[EdgeLine, Vec3, float]] = []
    for e in edges:
        if not isinstance(e, EdgeLine):
            continue
        d = Vec3(e.b) - Vec3(e.a)
        L = d.magnitude
        if L < 1e-6:
            continue
        gens.append((e, d / L, L))
    if not gens:
        return None
    gens.sort(key=lambda t: -t[2])
    axis = gens[0][1]
    gen_len = gens[0][2]
    # Require at least one long generator
    if gen_len < 1e-3:
        return None

    def _s_stats(e: Edge) -> tuple[float, float]:
        pts = _edge_samples(e, n=12)
        if not pts:
            return 0.0, 0.0
        ss = [float(Vec3(p).dot(axis)) for p in pts]
        return sum(ss) / len(ss), max(ss) - min(ss)

    planar: list[tuple[Edge, float]] = []
    for e in edges:
        sm, sr = _s_stats(e)
        # Skip near-axis generators (large span along axis)
        if isinstance(e, EdgeLine) and sr > 0.2 * gen_len:
            continue
        if sr <= max(0.5, 0.05 * gen_len):
            planar.append((e, sm))
    if len(planar) < 2:
        return None
    s_lo = min(sm for _, sm in planar)
    s_hi = max(sm for _, sm in planar)
    if s_hi - s_lo < 0.25 * gen_len:
        return None
    tol = max(0.5, 0.02 * (s_hi - s_lo))
    rail_a_e = [e for e, sm in planar if abs(sm - s_lo) <= tol]
    rail_b_e = [e for e, sm in planar if abs(sm - s_hi) <= tol]
    if not rail_a_e or not rail_b_e:
        return None
    A = _chain_edge_samples(rail_a_e, n_per=max(16, n_rail // max(1, len(rail_a_e))))
    B = _chain_edge_samples(rail_b_e, n_per=max(16, n_rail // max(1, len(rail_b_e))))
    if len(A) < 2 or len(B) < 2:
        return None
    if Vec3(B[0]).distance(Vec3(A[0])) > Vec3(B[-1]).distance(Vec3(A[0])):
        B = list(reversed(B))
    return (
        _resample_polyline(A, n_rail),
        _resample_polyline(B, n_rail),
        axis,
    )


def _rail_s_of_point(p: Vec3, A: list[tuple], axis: Vec3) -> float:
    """Continuous s∈[0,1]: closest point on rail A in the plane ⊥ axis.

    Boundary points come from SAB intersection curves; projecting them onto the
    rail cross-section recovers the trim in (s, h) without rebuilding the
    surface–surface intersection.
    """
    if len(A) < 2:
        return 0.0
    a0 = Vec3(A[0])
    v = p - a0
    cs = v - axis * float(v.dot(axis))
    best_s, best_d = 0.0, float("inf")
    n = len(A)
    for i in range(n - 1):
        r0 = Vec3(A[i]) - a0
        r1 = Vec3(A[i + 1]) - a0
        c0 = r0 - axis * float(r0.dot(axis))
        c1 = r1 - axis * float(r1.dot(axis))
        dvec = c1 - c0
        L2 = float(dvec.magnitude_square)
        if L2 < 1e-24:
            t = 0.0
            q = c0
        else:
            t = max(0.0, min(1.0, float((cs - c0).dot(dvec)) / L2))
            q = c0 + dvec * t
        dist = float(cs.distance(q))
        if dist < best_d:
            best_d = dist
            best_s = (i + t) / (n - 1)
    return best_s


def _edge_boundary_samples(edge: Edge) -> list[tuple]:
    """Dense samples of a SAB boundary edge (intersection / rail / gen)."""
    if isinstance(edge, EdgeLine):
        return [edge.a, edge.b]
    if isinstance(edge, (EdgeArc, EdgeCircle)):
        return _edge_samples(edge, n=48)
    if isinstance(edge, EdgeSpline):
        return _edge_samples(edge, n=max(64, len(edge.cps) * 12))
    return _edge_samples(edge, n=32)


def _ruled_param_poly(
    edges: list[Edge],
    A: list[tuple],
    axis: Vec3,
) -> list[tuple[float, float]]:
    """Trim loop in (s, h) from actual SAB boundary edges (intersection curves)."""
    if len(A) < 2 or not edges:
        return []
    pts3: list[tuple] = []
    for e in edges:
        seg = _edge_boundary_samples(e)
        if not seg:
            continue
        if not pts3:
            pts3.extend(seg)
        elif pts3[-1] == seg[0]:
            pts3.extend(seg[1:])
        else:
            pts3.extend(seg)
    pts3 = _uniq_ring(pts3)
    if len(pts3) < 3:
        return []
    out: list[tuple[float, float]] = []
    for p in pts3:
        pv = Vec3(p)
        out.append((_rail_s_of_point(pv, A, axis), float(pv.dot(axis))))
    if out and (
        abs(out[0][0] - out[-1][0]) > 1e-9 or abs(out[0][1] - out[-1][1]) > 1e-9
    ):
        out.append(out[0])
    return out


def _pip2(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Even-odd point-in-polygon (poly may be open or closed)."""
    n = len(poly)
    if n < 3:
        return False
    # Drop duplicate close point for iteration
    if (
        abs(poly[0][0] - poly[-1][0]) < 1e-12
        and abs(poly[0][1] - poly[-1][1]) < 1e-12
    ):
        n -= 1
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi
        ):
            inside = not inside
        j = i
    return inside


def _sh_inside(
    s: float,
    h: float,
    outer: list[tuple[float, float]],
    holes: list[list[tuple[float, float]]],
) -> bool:
    if not _pip2(s, h, outer):
        return False
    for hole in holes:
        if _pip2(s, h, hole):
            return False
    return True


def _clip_segs_to_sh(
    segs: list[tuple[tuple, tuple]],
    A: list[tuple],
    axis: Vec3,
    outer: list[tuple[float, float]],
    holes: list[list[tuple[float, float]]],
    nsub: int = 8,
) -> list[tuple[tuple, tuple]]:
    """Keep only isoline pieces inside the SAB trim (subdivide straddlers)."""
    if not segs or len(outer) < 3:
        return segs

    def _in(p: tuple) -> bool:
        pv = Vec3(p)
        return _sh_inside(
            _rail_s_of_point(pv, A, axis),
            float(pv.dot(axis)),
            outer,
            holes,
        )

    out: list[tuple[tuple, tuple]] = []
    for a, b in segs:
        va, vb = Vec3(a), Vec3(b)
        if va.distance(vb) < 1e-12:
            continue
        fa, fb = _in(a), _in(b)
        mid = _v3(va * 0.5 + vb * 0.5)
        fm = _in(mid)
        if fa and fb and fm:
            out.append((a, b))
            continue
        if not fa and not fb and not fm:
            continue
        # Straddles the trim — subdivide and keep interior runs
        flags: list[bool] = []
        pts: list[tuple] = []
        for k in range(nsub + 1):
            t = k / nsub
            p = _v3(va * (1.0 - t) + vb * t)
            pts.append(p)
            flags.append(_in(p))
        i = 0
        while i <= nsub:
            while i <= nsub and not flags[i]:
                i += 1
            if i > nsub:
                break
            j = i
            while j <= nsub and flags[j]:
                j += 1
            if j - 1 > i:
                out.append((pts[i], pts[j - 1]))
            i = j
    return out


def _clip_intervals_subtract(
    spans: list[tuple[float, float]], holes: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Subtract hole intervals from sorted disjoint spans."""
    if not spans:
        return []
    if not holes:
        return spans
    out = list(spans)
    for h0, h1 in sorted(holes):
        if h1 < h0:
            h0, h1 = h1, h0
        nxt: list[tuple[float, float]] = []
        for a, b in out:
            if h1 <= a or h0 >= b:
                nxt.append((a, b))
                continue
            if a < h0:
                nxt.append((a, h0))
            if h1 < b:
                nxt.append((h1, b))
        out = [(a, b) for a, b in nxt if b - a > 1e-9]
    return out


def _hits_to_spans(hits: list[float]) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    for i in range(0, len(hits) - 1, 2):
        a, b = hits[i], hits[i + 1]
        if b - a > 1e-9:
            spans.append((a, b))
    return spans


def _inset_spans(
    spans: list[tuple[float, float]], eps: float
) -> list[tuple[float, float]]:
    """Slightly shrink spans so isolines stop inside the SAB trim curve."""
    if eps <= 0:
        return spans
    out: list[tuple[float, float]] = []
    for a, b in spans:
        aa, bb = a + eps, b - eps
        if bb - aa > 1e-9:
            out.append((aa, bb))
    return out


def _ruled_mesh_segs(
    loops: list[list[Edge]],
    n_gen: int = 12,
    n_lat: int = 5,
    n_rail: int = 48,
) -> list[tuple[tuple, tuple]]:
    """Ruled isolines clipped to outer (+ holes): straight gens + curved lats."""
    if not loops:
        return []
    edges = loops[0]
    rails = _extract_extrusion_rails(edges, n_rail=n_rail)
    if rails is None and _is_ruled_loop(edges):
        # Fallback: classic 4-cycle without long parallel gens (skew ruled)
        eds = list(edges)
        if isinstance(eds[0], EdgeLine):
            eds = eds[1:] + eds[:1]
        A = _edge_samples(eds[0], n=n_rail)
        B = _edge_samples(eds[2], n=n_rail)
        if len(A) < 2 or len(B) < 2:
            return []
        if Vec3(B[0]).distance(Vec3(A[0])) > Vec3(B[-1]).distance(Vec3(A[0])):
            B = list(reversed(B))
        A, B = _resample_polyline(A, n_rail), _resample_polyline(B, n_rail)
        n = len(A)
        axis = Vec3(B[n // 2]) - Vec3(A[n // 2])
        if axis.magnitude_square < 1e-18:
            return []
        axis = axis.normalize()
    elif rails is None:
        return []
    else:
        A, B, axis = rails
        n = len(A)

    outer_uv = _ruled_param_poly(edges, A, axis)
    hole_uvs = [_ruled_param_poly(h, A, axis) for h in loops[1:]]
    hole_uvs = [h for h in hole_uvs if len(h) >= 3]

    # Prefer mean rail heights if ends differ slightly
    hA = sum(float(Vec3(p).dot(axis)) for p in A) / len(A)
    hB = sum(float(Vec3(p).dot(axis)) for p in B) / len(B)

    def _at(s: float, t: float) -> tuple:
        """Interpolated point on the ruled patch (s,t) ∈ [0,1]²."""
        f = max(0.0, min(1.0, s)) * (n - 1)
        i = int(math.floor(f))
        i = max(0, min(n - 2, i))
        u = f - i
        pa = Vec3(A[i]) * (1.0 - u) + Vec3(A[i + 1]) * u
        pb = Vec3(B[i]) * (1.0 - u) + Vec3(B[i + 1]) * u
        return _v3(pa * (1.0 - t) + pb * t)

    segs: list[tuple[tuple, tuple]] = []

    # Use (s, h) clipping when we have a reliable param polygon from SAB edges
    use_clip = len(outer_uv) >= 3
    if use_clip:
        # Inset so isolines stop just inside SAB intersection curves
        eps_h = max(1e-4, 0.003 * abs(hB - hA))
        eps_s = 0.003
        # Generators: constant s → hits in h
        for k in range(1, n_gen):
            s = k / n_gen
            spans = _inset_spans(
                _hits_to_spans(
                    _poly_line_hits(outer_uv, const=s, horizontal=False)
                ),
                eps_h,
            )
            for huv in hole_uvs:
                # Expand hole slightly (subtract more) so mesh clears the hole edge
                hole_sp = [
                    (a - eps_h, b + eps_h)
                    for a, b in _hits_to_spans(
                        _poly_line_hits(huv, const=s, horizontal=False)
                    )
                ]
                spans = _clip_intervals_subtract(spans, hole_sp)
            for ha, hb in spans:
                if abs(hB - hA) < 1e-12:
                    continue
                t0 = max(0.0, min(1.0, (ha - hA) / (hB - hA)))
                t1 = max(0.0, min(1.0, (hb - hA) / (hB - hA)))
                if abs(t1 - t0) < 1e-7:
                    continue
                segs.append((_at(s, t0), _at(s, t1)))
        # Latitudes: constant h (skip exact rail ends) — curved rail lerp
        for k in range(1, n_lat):
            t = k / n_lat
            hh = hA + (hB - hA) * t
            spans = _inset_spans(
                _hits_to_spans(
                    _poly_line_hits(outer_uv, const=hh, horizontal=True)
                ),
                eps_s,
            )
            for huv in hole_uvs:
                hole_sp = [
                    (a - eps_s, b + eps_s)
                    for a, b in _hits_to_spans(
                        _poly_line_hits(huv, const=hh, horizontal=True)
                    )
                ]
                spans = _clip_intervals_subtract(spans, hole_sp)
            for s0, s1 in spans:
                if s1 < s0:
                    s0, s1 = s1, s0
                if s1 - s0 < 1e-7:
                    continue
                # Dense samples along s so endpoints sit on the trim
                n_sub = max(8, int(round((s1 - s0) * (n - 1))) + 1)
                prev = _at(s0, t)
                for j in range(1, n_sub + 1):
                    sj = s0 + (s1 - s0) * j / n_sub
                    cur = _at(sj, t)
                    if Vec3(prev).distance(Vec3(cur)) > 1e-9:
                        segs.append((prev, cur))
                    prev = cur
        # Second pass: drop fragments that still leave the SAB trim
        # (nearest-s on complex intersection curves can slightly overshoot)
        return _clip_segs_to_sh(segs, A, axis, outer_uv, hole_uvs)

    # Unclipped fallback (simple strip)
    for k in range(1, n_gen):
        s = k / n_gen
        segs.append((_at(s, 0.0), _at(s, 1.0)))
    for k in range(1, n_lat):
        t = k / n_lat
        prev = _at(0.0, t)
        for j in range(1, n):
            cur = _at(j / (n - 1), t)
            if Vec3(prev).distance(Vec3(cur)) > 1e-9:
                segs.append((prev, cur))
            prev = cur
    return segs


def _emit_ruled_mesh(loops: list[list[Edge]]) -> list[str]:
    if not loops:
        return []
    L: list[str] = []
    for a, b in _ruled_mesh_segs(loops):
        L.append(f"  \\stpDmeshSeg{{{_fmt_xyz(a)}}}{{{_fmt_xyz(b)}}}")
    return L


def format_stp_analytic_face(face: dict[str, Any]) -> list[str]:
    """Emit face TeX: REGION → fill; SURFACE/solid → mesh + wire + FE eq."""
    loops = face.get("loops") or []
    kind = face.get("kind")
    L: list[str] = []
    # Planar REGION / closed curves: even-odd fill (holes), compact TeX
    if kind == "region":
        L.extend(format_stp_dface_curves(loops))
        return L
    if kind == "cylinder":
        L.extend(_emit_cylinder_mesh(face))
        L.extend(_emit_loop_wire(loops))
        L.extend(_emit_loop_eq(loops))
        return L
    if kind == "ruled":
        L.extend(_emit_ruled_mesh(loops))
        L.extend(_emit_loop_wire(loops))
        L.extend(_emit_loop_eq(loops))
        return L
    if kind == "plane":
        # Planar face on SURFACE/3DSOLID — AutoCAD-style isolines
        L.extend(
            _emit_plane_mesh(
                loops,
                nu=face.get("mesh_u"),
                nv=face.get("mesh_v"),
            )
        )
        L.extend(_emit_loop_wire(loops))
        L.extend(_emit_loop_eq(loops))
        return L
    # wire / unknown
    L.extend(_emit_loop_wire(loops))
    L.extend(_emit_loop_eq(loops))
    return L


def _emit_loop_wire(loops: list[list[Edge]]) -> list[str]:
    """Stroke face boundary once (no fill)."""
    if not loops:
        return []
    L = ["  \\begin{stpDwireEnv}"]
    for edges in loops:
        L.append("    \\begin{stpDfaceLoop}")
        for e in edges:
            L.append(_emit_edge_tex(e))
        L.append("    \\end{stpDfaceLoop}")
    L.append("  \\end{stpDwireEnv}")
    return L


def _emit_loop_eq(loops: list[list[Edge]]) -> list[str]:
    """FE equation rails (display suppressed)."""
    if not loops:
        return []
    L = ["  \\begin{stpDruledEq}"]
    for edges in loops:
        L.append("    \\begin{stpDruledRail}")
        for e in edges:
            L.append(_emit_edge_tex(e, display=False))
        L.append("    \\end{stpDruledRail}")
    L.append("  \\end{stpDruledEq}")
    return L


def cylinder_extent_pts(face: dict[str, Any], n: int = 24) -> list[tuple]:
    """Display/scale samples on cylinder mantle (not FE nodes)."""
    o, a = Vec3(face["origin"]), Vec3(face["axis"])
    if a.magnitude_square < 1e-18:
        return []
    a = a.normalize()
    r = float(face["radius"])
    u, v = _cyl_basis(a)
    u, v = u * r, v * r
    th0 = float(face.get("th0", -math.pi))
    th1 = float(face.get("th1", math.pi))
    pts = []
    for h in (float(face["h0"]), float(face["h1"])):
        c = o + a * h
        for i in range(n):
            t = th0 + (th1 - th0) * i / max(n - 1, 1)
            p = c + u * math.cos(t) + v * math.sin(t)
            pts.append(_k((p.x, p.y, p.z)))
    return pts


def curve_loops_centroid(loops: list[list[Edge]]) -> tuple[float, float, float] | None:
    if not loops:
        return None
    poly = loop_polyline(loops[0], n=48)
    if len(poly) < 1:
        return None
    n = len(poly)
    return (
        sum(p[0] for p in poly) / n,
        sum(p[1] for p in poly) / n,
        sum(p[2] for p in poly) / n,
    )


def curve_loops_as_polylines(loops: list[list[Edge]], n: int = 32) -> list[list[tuple]]:
    """For mass / legacy callers that still want polylines (not FE export)."""
    return [loop_polyline(edges, n=n) for edges in loops if edges]
