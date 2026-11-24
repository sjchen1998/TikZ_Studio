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

from ezdxf.math import BSpline, Vec3

from .cae_face_loops import (
    _clamp_knot_vector,
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


def _cone_taper_params(
    surf_rec: dict,
) -> tuple[Vec3, Vec3, float, float, float, Vec3 | None] | None:
    """Circular or elliptic cone: radius grows as ``radius + h * sine/cosine``.

    A loft between two circles is this surface. A zero sine is a cylinder and
    is left to ``_cone_cylinder_params``.
    """
    locs = [v for k, v in surf_rec["fields"] if k == "LOCATION_VEC"]
    dirs = [v for k, v in surf_rec["fields"] if k == "DIRECTION_VEC"]
    dbls = [float(v) for k, v in surf_rec["fields"] if k == "DOUBLE"]
    if not locs or not dirs:
        return None
    origin = Vec3(locs[0])
    axis = Vec3(dirs[0])
    if axis.magnitude_square < 1e-18:
        return None
    axis = axis.normalize()
    ratio = dbls[0] if dbls else 1.0
    sine = dbls[1] if len(dbls) > 1 else 0.0
    cosine = dbls[2] if len(dbls) > 2 else 1.0
    radius = dbls[3] if len(dbls) > 3 else (
        float(Vec3(dirs[1]).magnitude) if len(dirs) > 1 else 0.0
    )
    if radius <= 1e-9 or abs(cosine) < 1e-6:
        return None
    if ratio <= 1e-6:
        return None
    major = None
    if len(dirs) > 1 and Vec3(dirs[1]).magnitude_square > 1e-12:
        major = Vec3(dirs[1])
        major = major - axis * float(major.dot(axis))
        if major.magnitude_square > 1e-12:
            major = major.normalize()
        else:
            major = None
    return origin, axis, float(radius), float(sine / cosine), float(ratio), major


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


def _latitude_coverage_span(angs: list[float]) -> tuple[float, float, bool]:
    """Sector covered by latitude samples; largest circular gap = opening.

    Returns ``(th0, th1, full_turn)`` with ``th1 = th0 + covered_span``.
    """
    if not angs:
        return -math.pi, math.pi, True
    pts = sorted(
        {round(math.atan2(math.sin(t), math.cos(t)), 9) for t in angs}
    )
    if len(pts) == 1:
        return pts[0], pts[0], False
    gaps: list[tuple[float, float, float]] = []
    for i in range(len(pts) - 1):
        gaps.append((pts[i + 1] - pts[i], pts[i], pts[i + 1]))
    gaps.append((pts[0] + 2 * math.pi - pts[-1], pts[-1], pts[0] + 2 * math.pi))
    gap_w, _gap_a, gap_b = max(gaps, key=lambda g: g[0])
    # EdgeCircle tessellation often leaves a ~0.05–0.12 rad gap at the seam
    if gap_w < 0.20:
        return -math.pi, math.pi, True
    th0 = math.atan2(math.sin(gap_b), math.cos(gap_b))
    th1 = th0 + (2 * math.pi - gap_w)
    return th0, th1, False


def _cone_mesh_params(
    surf_rec: dict, loops: list[list[Edge]]
) -> dict[str, Any] | None:
    """Cylinder or tapered-cone mesh params from the cone-surface and its wires."""
    parsed = _cone_cylinder_params(surf_rec)
    slope, ratio, major = 0.0, 1.0, None
    if parsed is None:
        taper = _cone_taper_params(surf_rec)
        if taper is None:
            return None
        origin, axis, radius, slope, ratio, major = taper
    else:
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
        "slope": float(slope),
        "ratio": float(ratio),
        "major": None if major is None else _v3(major),
    }


_PLANE_MESH_U = 2
_PLANE_MESH_V = 2
_REVOLVE_MESH_TH = 12
_REVOLVE_MESH_PROF = 8


def _circular_lat_info(
    edge: Edge,
) -> tuple[Vec3, Vec3, float] | None:
    """(center, unit_normal, radius) for a circular latitude candidate."""
    if isinstance(edge, EdgeCircle):
        n = Vec3(edge.normal)
        if n.magnitude_square < 1e-18:
            return None
        return Vec3(edge.center), n.normalize(), float(edge.radius)
    if isinstance(edge, EdgeArc) and abs(float(edge.ratio) - 1.0) < 1e-3:
        n = Vec3(edge.normal)
        if n.magnitude_square < 1e-18:
            return None
        r = float(Vec3(edge.major).magnitude)
        if r < 1e-9:
            return None
        return Vec3(edge.center), n.normalize(), r
    return None


def _revolve_frame(
    axis: Vec3, hint: Vec3 | None = None
) -> tuple[Vec3, Vec3]:
    u, v = _cyl_basis(axis)
    if hint is not None and hint.magnitude_square > 1e-12:
        # Align u toward hint (projected ⊥ axis) for stable θ=0
        h = hint - axis * float(hint.dot(axis))
        if h.magnitude_square > 1e-12:
            u = h.normalize()
            v = axis.cross(u).normalize()
    return u, v


def _revolve_params_from_loop(
    edges: list[Edge],
    *,
    axis: Vec3 | None = None,
    origin: Vec3 | None = None,
    th0: float | None = None,
    th1: float | None = None,
) -> dict[str, Any] | None:
    """Build revolve mesh params from a SAB trim loop (latitudes + meridian)."""
    if len(edges) < 3:
        return None
    circ: list[tuple[Edge, Vec3, Vec3, float]] = []
    for e in edges:
        info = _circular_lat_info(e)
        if info is not None:
            c, n, r = info
            circ.append((e, c, n, r))
    if len(circ) < 2:
        return None

    # Cluster by normal → pick latitude group (‖n‖ shared with revolve axis)
    clusters: list[dict[str, Any]] = []
    for e, c, n, r in circ:
        placed = False
        for g in clusters:
            if abs(float(g["n"].dot(n))) > 0.92:
                g["items"].append((e, c, n, r))
                # Prefer consistent orientation
                if float(g["n"].dot(n)) < 0:
                    pass
                placed = True
                break
        if not placed:
            clusters.append({"n": n, "items": [(e, c, n, r)]})
    if not clusters:
        return None

    def _score(g: dict[str, Any]) -> tuple:
        items = g["items"]
        n_circ = sum(1 for e, *_ in items if isinstance(e, EdgeCircle))
        return (n_circ, len(items))

    if axis is not None:
        # Prefer cluster aligned with entity axis
        aligned = [
            g for g in clusters if abs(float(g["n"].dot(axis))) > 0.92
        ]
        lat_g = max(aligned or clusters, key=_score)
        ax = axis
    else:
        lat_g = max(clusters, key=_score)
        ax = Vec3(lat_g["n"]).normalize()

    lat_edges = [e for e, *_ in lat_g["items"]]
    lat_set = set(id(e) for e in lat_edges)

    # Origin: average of latitude centers projected (already on axis ideally)
    centers = [c for _, c, _, _ in lat_g["items"]]
    if origin is not None:
        o = origin
    else:
        o = sum(centers[1:], centers[0]) * (1.0 / len(centers))
        # Snap onto axis through first center
        o = centers[0] + ax * float((o - centers[0]).dot(ax))

    # Peel interior bridge-holes only (cap circles stay on outer)
    outer_edges, _bridged_holes = _split_bridge_holes(edges, origin=o, axis=ax)
    outer_lat = [e for e in outer_edges if id(e) in lat_set or (
        isinstance(e, EdgeCircle) and abs(float(Vec3(e.normal).normalize().dot(ax))) > 0.92
    )]
    outer_meridians = [e for e in outer_edges if id(e) not in lat_set and not (
        isinstance(e, EdgeCircle) and abs(float(Vec3(e.normal).normalize().dot(ax))) > 0.92
    )]
    meridians = outer_meridians or [e for e in edges if id(e) not in lat_set]
    if not meridians and not outer_edges:
        return None

    # θ frame from a mid-boundary hint
    hint_pts = _edge_samples(meridians[0], n=8) if meridians else _edge_samples(outer_edges[0], n=8)
    if not hint_pts:
        return None
    hint = Vec3(hint_pts[len(hint_pts) // 2]) - o
    u, v = _revolve_frame(ax, hint)

    # Profile from all outer edges (chain meridians; fill from full boundary)
    profile = _revolve_profile_from_edges(outer_edges or edges, o, ax, u, v)
    if len(profile) < 2:
        return None

    def _theta_of_pt(p: Vec3) -> float | None:
        w = p - o
        radial = w - ax * float(w.dot(ax))
        if radial.magnitude_square < 1e-12:
            return None
        return math.atan2(float(radial.dot(v)), float(radial.dot(u)))

    mer_thetas: list[float] = []
    for e in outer_meridians:
        # Skip non-generator rails (cut splines with large Δθ)
        angs = []
        for p in _edge_samples(e, n=12):
            t = _theta_of_pt(Vec3(p))
            if t is not None:
                angs.append(t)
        if not angs:
            continue
        un = _unwrap_theta_chain(angs)
        if max(un) - min(un) > 0.15:
            continue  # not a meridian
        sx = sum(math.cos(t) for t in angs)
        sy = sum(math.sin(t) for t in angs)
        if sx * sx + sy * sy < 1e-18:
            continue
        mer_thetas.append(math.atan2(sy, sx))
    uniq: list[float] = []
    for t in mer_thetas:
        if not any(
            abs(math.atan2(math.sin(t - u0), math.cos(t - u0))) < 1e-2 for u0 in uniq
        ):
            uniq.append(t)
    mer_thetas = uniq

    # Per-parallel latitude coverage (a top full circle must not hide a
    # bottom notch when deciding full_turn / opening angle).
    lat_by_h: dict[int, list[float]] = {}
    for e in outer_lat:
        pts = _edge_samples(e, n=48)
        if not pts:
            continue
        hs = [float((Vec3(p) - o).dot(ax)) for p in pts]
        h_key = int(round(0.5 * (min(hs) + max(hs))))
        bucket = lat_by_h.setdefault(h_key, [])
        for p in pts:
            t = _theta_of_pt(Vec3(p))
            if t is not None:
                bucket.append(t)

    full_turn = False
    use_th0, use_th1 = -math.pi, math.pi
    if th0 is not None and th1 is not None and abs(th1 - th0) > 2 * math.pi - 1e-3:
        full_turn = True
    elif lat_by_h:
        # Opening = most incomplete parallel; full only if every parallel is full
        worst_span = 2 * math.pi
        worst_th = (-math.pi, math.pi)
        all_full = True
        for angs in lat_by_h.values():
            a0, a1, is_full = _latitude_coverage_span(angs)
            if not is_full:
                all_full = False
                span = abs(a1 - a0)
                if span < worst_span:
                    worst_span = span
                    worst_th = (a0, a1)
        if all_full and any(isinstance(e, EdgeCircle) for e in outer_lat):
            full_turn = True
        elif all_full and len(mer_thetas) <= 1:
            # Two coincident seams + full parallels
            full_turn = True
        else:
            use_th0, use_th1 = worst_th
            if abs(use_th1 - use_th0) < 1e-3:
                return None
    elif len(mer_thetas) >= 2:
        a, b = mer_thetas[0], mer_thetas[1]
        d_ccw = (b - a) % (2 * math.pi)
        d_cw = (a - b) % (2 * math.pi)
        target = (
            abs(float(th1) - float(th0))
            if (th0 is not None and th1 is not None)
            else None
        )
        if target is not None and target > 1e-6:
            if abs(d_ccw - target) <= abs(d_cw - target):
                use_th0, use_th1 = a, a + d_ccw
            else:
                use_th0, use_th1 = a, a - d_cw
        else:
            if d_ccw >= d_cw:
                use_th0, use_th1 = a, a + d_ccw
            else:
                use_th0, use_th1 = a, a - d_cw
        if abs(use_th1 - use_th0) < 1e-3:
            return None
    else:
        return None

    if full_turn:
        use_th0, use_th1 = -math.pi, math.pi

    # Polyline / multi-edge profile: each line/arc sub-segment → its own (s0,s1)
    # so generators and latitudes are walked per piece (not one lazy full span).
    cum_tmp, tot_tmp = _profile_cumlen(profile)

    def _meridian_piece_s(
        e: Edge,
    ) -> tuple[float, float, float] | None:
        """Return (mean_θ, s0, s1) for a const-θ generator edge, else None."""
        if isinstance(e, EdgeLine):
            pts = [
                _v3(Vec3(e.a) * (1.0 - t) + Vec3(e.b) * t)
                for t in [i / 16 for i in range(17)]
            ]
        else:
            pts = _edge_samples(e, n=24)
        if len(pts) < 2:
            return None
        ths = [t for p in pts if (t := _theta_of_pt(Vec3(p))) is not None]
        if len(ths) < 2:
            return None
        un = _unwrap_theta_chain(ths)
        if max(un) - min(un) > 0.2:
            return None  # cut / non-meridian
        sx = sum(math.cos(t) for t in ths)
        sy = sum(math.sin(t) for t in ths)
        if sx * sx + sy * sy < 1e-18:
            return None
        mean_th = math.atan2(sy, sx)
        svals: list[float] = []
        for p in pts:
            w = Vec3(p) - o
            h = float(w.dot(ax))
            rho = float((w - ax * h).magnitude)
            svals.append(_hr_to_s(h, rho, profile, cum_tmp, tot_tmp))
        if len(svals) < 2:
            return None
        sa, sb = min(svals), max(svals)
        if sb - sa < 1e-6:
            return None
        return mean_th, sa, sb

    # Group meridian edges by θ; pick the generator with the most pieces
    # (polyline line+arc chain) and keep each piece as its own span.
    by_th: dict[int, list[tuple[float, float]]] = {}
    for e in outer_meridians:
        piece = _meridian_piece_s(e)
        if piece is None:
            continue
        mean_th, sa, sb = piece
        key = int(round(mean_th / 0.05))
        by_th.setdefault(key, []).append((sa, sb))
    profile_segs: list[tuple[float, float]] = []
    if by_th:
        best_key = max(by_th, key=lambda k: (len(by_th[k]), sum(b - a for a, b in by_th[k])))
        pieces = sorted(by_th[best_key], key=lambda t: t[0])
        # Drop near-duplicate copies only; never glue adjacent line|arc joints
        for a, b in pieces:
            if profile_segs and abs(a - profile_segs[-1][0]) < 1e-3 and abs(
                b - profile_segs[-1][1]
            ) < 1e-3:
                continue
            profile_segs.append((a, b))
    if not profile_segs:
        profile_segs = [(0.0, 1.0)]

    # Centroid sample at mid profile / mid angle
    h_mid = 0.5 * (profile[0][0] + profile[-1][0])
    rho_mid = 0.5 * (profile[0][1] + profile[-1][1])
    th_mid = 0.5 * (use_th0 + use_th1)
    cen = o + ax * h_mid + u * (rho_mid * math.cos(th_mid)) + v * (
        rho_mid * math.sin(th_mid)
    )
    return {
        "origin": _v3(o),
        "axis": _v3(ax),
        "u": _v3(u),
        "v": _v3(v),
        "profile": profile,
        "profile_segs": profile_segs,
        "th0": float(use_th0),
        "th1": float(use_th1),
        "full_turn": bool(full_turn),
        "cen": _v3(cen),
    }


def _revolve_eval(
    origin: Vec3,
    axis: Vec3,
    u: Vec3,
    v: Vec3,
    h: float,
    rho: float,
    th: float,
) -> tuple:
    p = origin + axis * h + u * (rho * math.cos(th)) + v * (rho * math.sin(th))
    return _v3(p)


def _phase_closed_samples(
    samples: list[tuple], anchor: Sequence[float] | Vec3
) -> list[tuple]:
    """Rotate a closed ring so it starts at the sample nearest ``anchor``."""
    if len(samples) < 3:
        return samples
    pts = samples[:-1] if samples[0] == samples[-1] else list(samples)
    if not pts:
        return samples
    av = Vec3(anchor)
    k0 = min(range(len(pts)), key=lambda i: av.distance(Vec3(pts[i])))
    out = pts[k0:] + pts[:k0]
    out.append(out[0])
    return out


def _chain_loop_pts3(edges: list[Edge]) -> list[tuple]:
    """Ordered 3D samples around a coedge loop; phase full circles to joins."""
    pts3: list[tuple] = []
    for e in edges:
        seg = _edge_boundary_samples(e)
        if not seg:
            continue
        if pts3 and isinstance(e, EdgeCircle):
            seg = _phase_closed_samples(seg, pts3[-1])
        if not pts3:
            pts3.extend(seg)
        elif Vec3(pts3[-1]).distance(Vec3(seg[0])) < 1e-6:
            pts3.extend(seg[1:])
        else:
            # Prefer reverse if the circle/arc was sampled opposite to coedge sense
            if Vec3(pts3[-1]).distance(Vec3(seg[-1])) < 1e-6:
                seg = list(reversed(seg))
                pts3.extend(seg[1:])
            else:
                pts3.extend(seg)
    return _uniq_ring(pts3)


def _edge_h_range(
    edge: Edge, origin: Vec3, axis: Vec3
) -> tuple[float, float] | None:
    pts = _edge_samples(edge, n=16)
    if not pts:
        return None
    hs = [float((Vec3(p) - origin).dot(axis)) for p in pts]
    return min(hs), max(hs)


def _split_bridge_holes(
    edges: list[Edge],
    origin: Vec3 | None = None,
    axis: Vec3 | None = None,
) -> tuple[list[Edge], list[list[Edge]]]:
    """Peel ACIS bridge digons + *interior* full-circle holes.

    Pattern: EdgeLine → EdgeCircle+ → reverse EdgeLine.  Cap circles at the
    axial ends of the face (annulus top/bottom) stay on the outer loop — only
    true mid-height punched holes are peeled.  Cancelling bridge lines are
    always dropped when the circle is kept as a cap.
    """
    n = len(edges)
    if n < 3:
        return list(edges), []
    bridges: list[tuple[int, int]] = []
    for i, a in enumerate(edges):
        if not isinstance(a, EdgeLine):
            continue
        for j in range(i + 1, n):
            b = edges[j]
            if not isinstance(b, EdgeLine):
                continue
            if (
                Vec3(a.a).distance(Vec3(b.b)) < 1e-4
                and Vec3(a.b).distance(Vec3(b.a)) < 1e-4
            ):
                bridges.append((i, j))
    # Axial extent of the whole loop (for cap vs interior test)
    h_lo, h_hi = 1e300, -1e300
    if origin is not None and axis is not None and axis.magnitude_square > 1e-18:
        axn = axis.normalize()
        for e in edges:
            hr = _edge_h_range(e, origin, axn)
            if hr:
                h_lo = min(h_lo, hr[0])
                h_hi = max(h_hi, hr[1])
    h_span = h_hi - h_lo if h_hi >= h_lo else 0.0
    cap_eps = max(1.0, 0.02 * h_span) if h_span > 0 else 1.0

    skip: set[int] = set()
    holes: list[list[Edge]] = []
    for i, j in bridges:
        mid = list(range(i + 1, j))
        if not mid or not all(isinstance(edges[k], EdgeCircle) for k in mid):
            continue
        # Drop cancelling bridges always
        skip.update({i, j})
        for k in mid:
            circ = edges[k]
            is_cap = False
            if (
                origin is not None
                and axis is not None
                and h_span > 1e-6
                and isinstance(circ, EdgeCircle)
            ):
                ch = float((Vec3(circ.center) - origin).dot(axis.normalize()))
                if ch <= h_lo + cap_eps or ch >= h_hi - cap_eps:
                    is_cap = True
            if is_cap:
                continue  # keep circle on outer
            holes.append([circ])
            skip.add(k)
    if not skip:
        return list(edges), []
    outer = [e for k, e in enumerate(edges) if k not in skip]
    return outer, holes


def _revolve_profile_from_edges(
    edges: list[Edge],
    origin: Vec3,
    axis: Vec3,
    u: Vec3,
    v: Vec3,
) -> list[tuple[float, float]]:
    """Build generating (h, ρ) profile from boundary edges (not a single cut)."""

    def _hr_of(p: Sequence[float] | Vec3) -> tuple[float, float]:
        w = Vec3(p) - origin
        h = float(w.dot(axis))
        rho = float((w - axis * h).magnitude)
        return h, rho

    def _theta_of(p: Sequence[float] | Vec3) -> float | None:
        w = Vec3(p) - origin
        radial = w - axis * float(w.dot(axis))
        if radial.magnitude_square < 1e-12:
            return None
        return math.atan2(float(radial.dot(v)), float(radial.dot(u)))

    def _dedup(seq: list[tuple[float, float]]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for h, r in seq:
            if out and math.hypot(h - out[-1][0], r - out[-1][1]) < 1e-3:
                continue
            out.append((h, r))
        return out

    def _span(pr: list[tuple[float, float]]) -> float:
        if len(pr) < 2:
            return 0.0
        return max(p[0] for p in pr) - min(p[0] for p in pr)

    def _sort_by_h(pr: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Open generating curve: unique ρ(h), sorted by h."""
        buckets: dict[int, list[float]] = {}
        for h, r in pr:
            key = int(round(h * 20.0))
            buckets.setdefault(key, []).append(r)
        keys = sorted(buckets)
        return [
            (k / 20.0, sorted(buckets[k])[len(buckets[k]) // 2]) for k in keys
        ]

    # 1) Group near-constant-θ edges by θ — each group is one generator
    groups: dict[int, list[tuple[float, float]]] = {}
    for e in edges:
        if _edge_is_revolve_latitude(e, axis):
            continue
        if isinstance(e, EdgeLine):
            a, b = Vec3(e.a), Vec3(e.b)
            pts = [
                _v3(a * (1.0 - t) + b * t) for t in [i / 48 for i in range(49)]
            ]
        else:
            pts = _edge_samples(e, n=64)
        if len(pts) < 2:
            continue
        ths = [t for p in pts if (t := _theta_of(p)) is not None]
        if len(ths) < 2:
            continue
        un = _unwrap_theta_chain(ths)
        if max(un) - min(un) > 0.2:
            continue  # cut / non-meridian
        sx = sum(math.cos(t) for t in ths)
        sy = sum(math.sin(t) for t in ths)
        if sx * sx + sy * sy < 1e-18:
            continue
        mean = math.atan2(sy, sx)
        key = int(round(mean / 0.05))  # ~3° bins
        groups.setdefault(key, []).extend(_hr_of(p) for p in pts)

    profile: list[tuple[float, float]] = []
    if groups:
        # Pick the generator with the largest axial span
        best: list[tuple[float, float]] = []
        for hr in groups.values():
            ordered = _sort_by_h(hr)
            if _span(ordered) > _span(best):
                best = ordered
        profile = best

    # Required axial span from ALL boundary samples
    all_hr = [_hr_of(p) for e in edges for p in _edge_samples(e, n=32)]
    if not all_hr:
        return profile
    need = max(p[0] for p in all_hr) - min(p[0] for p in all_hr)

    # 2) Fallback: single-valued ρ(h) from all boundary samples (cones / flares)
    if _span(profile) < 0.85 * need - 1e-6:
        mono = _sort_by_h(all_hr)
        if _span(mono) >= _span(profile):
            profile = mono

    return profile if len(profile) >= 2 else _dedup(all_hr)


def _profile_cumlen(
    profile: list[tuple[float, float]],
) -> tuple[list[float], float]:
    cum = [0.0]
    for i in range(len(profile) - 1):
        h0, r0 = profile[i]
        h1, r1 = profile[i + 1]
        cum.append(cum[-1] + math.hypot(h1 - h0, r1 - r0))
    return cum, cum[-1]


def _profile_at_s(
    profile: list[tuple[float, float]], cum: list[float], total: float, s: float
) -> tuple[float, float]:
    """(h, ρ) at normalized s∈[0,1] along profile."""
    if total < 1e-12 or len(profile) < 2:
        return profile[0]
    s = max(0.0, min(1.0, s))
    dist = total * s
    j = 0
    while j + 1 < len(cum) and cum[j + 1] < dist - 1e-15:
        j += 1
    if j + 1 >= len(cum):
        return profile[-1]
    seg = cum[j + 1] - cum[j]
    t = 0.0 if seg < 1e-15 else (dist - cum[j]) / seg
    h = profile[j][0] * (1.0 - t) + profile[j + 1][0] * t
    rho = profile[j][1] * (1.0 - t) + profile[j + 1][1] * t
    return h, rho


def _hr_to_s(
    h: float,
    rho: float,
    profile: list[tuple[float, float]],
    cum: list[float],
    total: float,
) -> float:
    """Closest point on profile in (h,ρ) → normalized arc-length s∈[0,1]."""
    if total < 1e-12 or len(profile) < 2:
        return 0.0
    best_d = 1e300
    best_s = 0.0
    for i in range(len(profile) - 1):
        h0, r0 = profile[i]
        h1, r1 = profile[i + 1]
        dh, dr = h1 - h0, r1 - r0
        L2 = dh * dh + dr * dr
        if L2 < 1e-24:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((h - h0) * dh + (rho - r0) * dr) / L2))
        hh, rr = h0 + t * dh, r0 + t * dr
        d = (h - hh) ** 2 + (rho - rr) ** 2
        if d < best_d:
            best_d = d
            best_s = (cum[i] + t * (cum[i + 1] - cum[i])) / total
    return best_s


def _h_to_s(
    h: float,
    profile: list[tuple[float, float]],
    cum: list[float],
    total: float,
) -> float:
    """Map axial height to profile s (for trim curves that leave the ρ(h) graph)."""
    if total < 1e-12 or len(profile) < 2:
        return 0.0
    h_lo = min(p[0] for p in profile)
    h_hi = max(p[0] for p in profile)
    if h <= h_lo:
        # endpoint with min h
        i = min(range(len(profile)), key=lambda k: profile[k][0])
        return cum[i] / total
    if h >= h_hi:
        i = max(range(len(profile)), key=lambda k: profile[k][0])
        return cum[i] / total
    for i in range(len(profile) - 1):
        h0, h1 = profile[i][0], profile[i + 1][0]
        if abs(h1 - h0) < 1e-15:
            continue
        lo, hi = (h0, h1) if h0 <= h1 else (h1, h0)
        if lo - 1e-9 <= h <= hi + 1e-9:
            t = (h - h0) / (h1 - h0)
            t = max(0.0, min(1.0, t))
            return (cum[i] + t * (cum[i + 1] - cum[i])) / total
    return _hr_to_s(h, 0.0, profile, cum, total)


def _revolve_ts_of_point(
    p: Sequence[float] | Vec3,
    origin: Vec3,
    axis: Vec3,
    u: Vec3,
    v: Vec3,
    profile: list[tuple[float, float]],
    cum: list[float],
    total: float,
) -> tuple[float, float] | None:
    w = Vec3(p) - origin
    h = float(w.dot(axis))
    radial = w - axis * h
    rho = float(radial.magnitude)
    if radial.magnitude_square < 1e-16:
        th = 0.0
    else:
        th = math.atan2(float(radial.dot(v)), float(radial.dot(u)))
    # Prefer axial s so notch/cut meridians (ρ ≠ profile) still form a
    # vertical UV wall at their θ — (h,ρ) nearest would warp the clip.
    s_h = _h_to_s(h, profile, cum, total)
    s_hr = _hr_to_s(h, rho, profile, cum, total)
    # On-surface: both agree; off-profile cut: trust height
    s = s_h if abs(s_h - s_hr) > 1e-3 else s_hr
    return th, s


def _revolve_rect_uv(th0: float, th1: float) -> list[tuple[float, float]]:
    """Full-mantle rectangle in (θ, s) for an untrimmed 360° revolve."""
    a, b = (th0, th1) if th1 >= th0 else (th1, th0)
    if abs(b - a) < 1e-9:
        b = a + 2 * math.pi
    return [(a, 0.0), (a, 1.0), (b, 1.0), (b, 0.0), (a, 0.0)]


def _revolve_is_simple_mantle(edges: list[Edge]) -> bool:
    """Untrimmed full mantle: two latitude circles (± optional seam generators).

    After bridge-peel of coincident EdgeLine seams, only the two cap circles
    remain — that case must still use a rectangular (θ,s) domain, not a
    double-wound unwrap of the two circles (which empties the mesh).
    """
    n_circ = sum(1 for e in edges if isinstance(e, EdgeCircle))
    if n_circ != 2:
        return False
    if len(edges) == 2:
        return all(isinstance(e, EdgeCircle) for e in edges)
    if len(edges) == 4:
        return True
    return False


def _revolve_param_poly(
    edges: list[Edge],
    origin: Vec3,
    axis: Vec3,
    u: Vec3,
    v: Vec3,
    profile: list[tuple[float, float]],
    cum: list[float],
    total: float,
    *,
    th0: float | None = None,
    th1: float | None = None,
    full_turn: bool = False,
) -> list[tuple[float, float]]:
    """Boundary loop in (θ, s) for isoline clipping (holes / notches)."""
    if not edges or total < 1e-12:
        return []
    # Untrimmed full revolves: avoid double-wind unwrap from two EdgeCircles
    if (
        full_turn
        and th0 is not None
        and th1 is not None
        and _revolve_is_simple_mantle(edges)
    ):
        return _revolve_rect_uv(th0, th1)
    pts3 = _chain_loop_pts3(edges)
    if len(pts3) < 3:
        # Lone full circle (hole): sample once around
        if len(edges) == 1 and isinstance(edges[0], EdgeCircle):
            pts3 = _edge_boundary_samples(edges[0])
        if len(pts3) < 3:
            return []
    raw: list[tuple[float, float]] = []
    for p in pts3:
        ts = _revolve_ts_of_point(p, origin, axis, u, v, profile, cum, total)
        if ts is not None:
            raw.append(ts)
    if len(raw) < 3:
        return []
    ths = _unwrap_theta_chain([t for t, _ in raw])
    uv = list(zip(ths, [s for _, s in raw]))
    # Closed 3D loops that wind once about the axis unwrap with Δθ≈±2π;
    # closing with a diagonal would cut the domain — close along constant-s seam.
    dth = uv[-1][0] - uv[0][0]
    ds = uv[-1][1] - uv[0][1]
    if abs(dth) > 1e-6 or abs(ds) > 1e-6:
        if abs(abs(dth) - 2 * math.pi) < 0.05 and abs(ds) < 1e-3:
            # already a near-full latitude ring; snap close in θ
            uv = list(uv)
            uv[-1] = (uv[0][0] + math.copysign(2 * math.pi, dth), uv[0][1])
            uv.append(uv[0])
        elif abs(dth) > math.pi:
            # seam close: vertical then to start
            uv = list(uv) + [(uv[-1][0], uv[0][1]), uv[0]]
        else:
            uv = list(uv) + [uv[0]]
    return uv


def _revolve_trim_loops(
    loops: list[list[Edge]],
    origin: Vec3 | None = None,
    axis: Vec3 | None = None,
) -> list[list[Edge]]:
    """Outer + holes, peeling interior bridge-to-circle holes out of loop[0]."""
    if not loops:
        return []
    outer, bridged = _split_bridge_holes(loops[0], origin=origin, axis=axis)
    out: list[list[Edge]] = []
    if outer:
        out.append(outer)
    out.extend(bridged)
    out.extend(loops[1:])
    return out


def _inside_spans_1d(
    u0: float,
    u1: float,
    inside_at,
    *,
    n_sample: int = 96,
    refine: int = 20,
) -> list[tuple[float, float]]:
    """Inside intervals on [u0,u1] via dense PIP samples + bisection to the trim.

    No cosmetic inset: endpoints lie on the PIP boundary to search tolerance.
    """
    if abs(u1 - u0) < 1e-15:
        return []
    if u1 < u0:
        u0, u1 = u1, u0
    n = max(8, int(n_sample))
    us = [u0 + (u1 - u0) * i / n for i in range(n + 1)]
    flags = [bool(inside_at(u)) for u in us]

    def _bisect(ua: float, ub: float, fa: bool, fb: bool) -> float:
        a, b, fa_ = ua, ub, fa
        for _ in range(refine):
            m = 0.5 * (a + b)
            fm = bool(inside_at(m))
            if fm == fa_:
                a, fa_ = m, fm
            else:
                b = m
        return a if fa_ else b

    spans: list[tuple[float, float]] = []
    i = 0
    while i <= n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j < n and flags[j + 1]:
            j += 1
        lo, hi = us[i], us[j]
        if i > 0 and not flags[i - 1]:
            lo = _bisect(us[i - 1], us[i], False, True)
        elif i == 0 and flags[0]:
            lo = u0
        if j < n and not flags[j + 1]:
            hi = _bisect(us[j], us[j + 1], True, False)
        elif j == n and flags[n]:
            hi = u1
        if hi - lo > 1e-12:
            spans.append((lo, hi))
        i = j + 1
    return spans


def _revolve_mesh_segs(
    face: dict[str, Any],
    n_th: int = _REVOLVE_MESH_TH,
    n_prof: int = _REVOLVE_MESH_PROF,
) -> list[tuple[tuple, tuple]]:
    """Isolines clipped to SAB trim in (θ, s), including holes / notches."""
    profile = face.get("profile") or []
    loops = face.get("loops") or []
    if len(profile) < 2:
        return []
    origin = Vec3(face["origin"])
    axis = Vec3(face["axis"]).normalize()
    u, v = Vec3(face["u"]), Vec3(face["v"])
    th0 = float(face["th0"])
    th1 = float(face["th1"])
    full = bool(face.get("full_turn"))
    cum, total = _profile_cumlen(profile)
    if total < 1e-12:
        return []

    trim = _revolve_trim_loops(loops, origin=origin, axis=axis)
    # Parametric trim polygons (outer + holes)
    outer_uv = _revolve_param_poly(
        trim[0] if trim else [],
        origin,
        axis,
        u,
        v,
        profile,
        cum,
        total,
        th0=th0,
        th1=th1,
        full_turn=full,
    )
    hole_uvs = []
    for hole in trim[1:] if trim else []:
        huv = _revolve_param_poly(
            hole,
            origin,
            axis,
            u,
            v,
            profile,
            cum,
            total,
            th0=th0,
            th1=th1,
            full_turn=full,
        )
        if len(huv) < 3:
            continue
        # Drop degenerate holes (e.g. full latitude → zero area in (θ,s))
        area = abs(
            sum(
                huv[i][0] * huv[i + 1][1] - huv[i + 1][0] * huv[i][1]
                for i in range(len(huv) - 1)
            )
            * 0.5
        )
        if area < 1e-6:
            continue
        hole_uvs.append(huv)
    use_clip = len(outer_uv) >= 3
    if use_clip:
        ths = [p[0] for p in outer_uv]
        ss = [p[1] for p in outer_uv]
        th_lo, th_hi = min(ths), max(ths)
        s_lo, s_hi = min(ss), max(ss)
        # Full-turn only: collapse double-wind unwrap to the face window.
        # Partial faces must keep the polygon's unwrap branch (clamping to
        # face th0/th1 on another sheet drops almost all isolines).
        if full and (th_hi - th_lo) > abs(th1 - th0) + 0.25:
            th_lo, th_hi = (min(th0, th1), max(th0, th1))
        # Degenerate / empty PIP domain (e.g. two circles unwrapped as a
        # spiral): fall back to the rectangular mantle so polyline line
        # segments of a 360° revolve still get generators that reach the caps.
        if full:
            mid_th = 0.5 * (th_lo + th_hi)
            mid_s = 0.5 * (s_lo + s_hi)
            if not _pip2(mid_th, mid_s, outer_uv):
                outer_uv = _revolve_rect_uv(th0, th1)
                th_lo, th_hi = (min(th0, th1), max(th0, th1))
                if abs(th_hi - th_lo) < 1e-9:
                    th_lo, th_hi = -math.pi, math.pi
                s_lo, s_hi = 0.0, 1.0
    else:
        th_lo, th_hi = (th0, th1) if th1 >= th0 else (th1, th0)
        s_lo, s_hi = 0.0, 1.0

    def _at(th: float, s: float) -> tuple:
        h, rho = _profile_at_s(profile, cum, total, s)
        if rho < 1e-9:
            return _v3(origin + axis * h)
        return _revolve_eval(origin, axis, u, v, h, rho, th)

    def _uv_inside(th: float, s: float) -> bool:
        if use_clip:
            if not _pip2(th, s, outer_uv):
                return False
            for huv in hole_uvs:
                if _pip2(th, s, huv):
                    return False
            return True
        return (th_lo - 1e-12) <= th <= (th_hi + 1e-12) and (
            s_lo - 1e-12
        ) <= s <= (s_hi + 1e-12)

    # Tip snap by isoline class so a notch spline cannot drag a parallel
    # off its height (that left a visible gap before the red boundary).
    lat_edge_pts: list[list[tuple]] = []
    mer_edge_pts: list[list[tuple]] = []
    if use_clip:
        for lp in trim:
            for e in lp:
                seg = _edge_boundary_samples(e)
                if len(seg) < 2:
                    continue
                if _edge_is_revolve_latitude(e, axis):
                    lat_edge_pts.append(seg)
                else:
                    mer_edge_pts.append(seg)
    snap_tol = 0.0
    snap_tol_h = 0.0
    h_span_face = 1.0
    all_snap = lat_edge_pts + mer_edge_pts
    if all_snap:
        flat = [p for seg in all_snap for p in seg]
        xs = [p[0] for p in flat]
        ys = [p[1] for p in flat]
        zs = [p[2] for p in flat]
        diag = math.hypot(
            max(xs) - min(xs),
            math.hypot(max(ys) - min(ys), max(zs) - min(zs)),
        )
        hs = [float((Vec3(p) - origin).dot(axis)) for p in flat]
        h_span_face = max(hs) - min(hs) if hs else 1.0
        # Axial-constrained (keep_h) snaps may travel radially to a cut
        # meridian; unconstrained snaps stay tight so tips cannot jump edges.
        snap_tol = max(2.0, 0.025 * diag)
        snap_tol_h = max(snap_tol, 0.08 * diag)

    def _snap_tip(
        p: tuple,
        edge_pts: list[list[tuple]],
        *,
        keep_h: bool = False,
    ) -> tuple:
        tol = snap_tol_h if keep_h else snap_tol
        if not edge_pts or tol <= 0:
            return p
        pv = Vec3(p)
        h0 = float((pv - origin).dot(axis))
        best = p
        best_d = 1e300
        for seg in edge_pts:
            for i in range(len(seg) - 1):
                a = Vec3(seg[i])
                b = Vec3(seg[i + 1])
                if keep_h:
                    # Intersect the parallel (const h) with the meridian edge
                    ha = float((a - origin).dot(axis))
                    hb = float((b - origin).dot(axis))
                    if abs(hb - ha) < 1e-12:
                        if abs(ha - h0) > 1e-3:
                            continue
                        q = a
                    else:
                        t = (h0 - ha) / (hb - ha)
                        if t < -1e-6 or t > 1.0 + 1e-6:
                            continue
                        t = max(0.0, min(1.0, t))
                        q = a + (b - a) * t
                else:
                    ab = b - a
                    L2 = ab.magnitude_square
                    if L2 < 1e-24:
                        q = a
                    else:
                        t = max(0.0, min(1.0, float((pv - a).dot(ab) / L2)))
                        q = a + ab * t
                d = pv.distance(q)
                if d < best_d:
                    best_d = d
                    best = _v3(q)
        return best if best_d <= tol else p

    def _emit_span(
        u_a: float,
        u_b: float,
        *,
        nsub: int,
        point_at,
        tip_edges: list[list[tuple]],
        keep_h: bool = False,
    ) -> None:
        """Emit subdivided isoline; snap tips onto matching SAB wire class."""
        if abs(u_b - u_a) < 1e-12:
            return
        nsub = max(2, nsub)
        pts = [point_at(u_a + (u_b - u_a) * j / nsub) for j in range(nsub + 1)]
        pts[0] = _snap_tip(pts[0], tip_edges, keep_h=keep_h)
        pts[-1] = _snap_tip(pts[-1], tip_edges, keep_h=keep_h)
        for j in range(nsub):
            if Vec3(pts[j]).distance(Vec3(pts[j + 1])) > 1e-9:
                segs.append((pts[j], pts[j + 1]))

    segs: list[tuple[tuple, tuple]] = []

    # Polyline profile → isolines per line/arc sub-segment (not one lazy pass)
    raw_segs = face.get("profile_segs") or [(0.0, 1.0)]
    prof_segs: list[tuple[float, float]] = []
    for a, b in raw_segs:
        aa, bb = max(a, s_lo), min(b, s_hi)
        # UV samples often undershoot 0/1 by 1e-5; pin so generators meet caps
        if abs(aa - s_lo) < 1e-3 and s_lo < 1e-3:
            aa = 0.0
        if abs(bb - s_hi) < 1e-3 and s_hi > 1.0 - 1e-3:
            bb = 1.0
        if bb - aa > 1e-9:
            prof_segs.append((aa, bb))
    if not prof_segs:
        prof_segs = [(0.0, 1.0)] if s_lo < 1e-3 and s_hi > 1.0 - 1e-3 else [(s_lo, s_hi)]

    th_list = [
        th_lo + (th_hi - th_lo) * k / max(n_th, 1) for k in range(n_th + 1)
    ]
    if full or abs(th_hi - th_lo) > 1e-9:
        th_list = th_list[1:-1] if len(th_list) > 2 else []

    # Generators: constant θ, one span walk per profile sub-segment
    for th in th_list:
        for seg_s0, seg_s1 in prof_segs:
            spans = _inside_spans_1d(
                seg_s0,
                seg_s1,
                lambda s, _th=th: _uv_inside(_th, s),
                n_sample=max(48, n_prof * 10),
            )
            for sa, sb in spans:
                # Pin to sub-segment ends (polyline joints / surface caps)
                pin = max(1e-4, 2e-3 * max(seg_s1 - seg_s0, 1e-9))
                if abs(sa - seg_s0) < pin:
                    sa = seg_s0
                if abs(sb - seg_s1) < pin:
                    sb = seg_s1
                _emit_span(
                    sa,
                    sb,
                    nsub=max(4, int(round((sb - sa) * n_prof)) + 1),
                    point_at=lambda s, _th=th: _at(_th, s),
                    tip_edges=lat_edge_pts,
                    keep_h=False,
                )

    # Latitudes follow arc length. A short line/arc piece must not get a full
    # n_prof grid — that packs parallels into the small revolved patch.
    lat_s: list[float] = []
    span_all = max(s_hi - s_lo, 1e-9)
    for seg_s0, seg_s1 in prof_segs:
        frac = (seg_s1 - seg_s0) / span_all
        n_loc = max(1, int(round(n_prof * frac)))
        if n_loc >= 2:
            for k in range(1, n_loc):
                lat_s.append(seg_s0 + (seg_s1 - seg_s0) * k / n_loc)
        elif frac >= 1.0 / max(n_prof, 1):
            lat_s.append(0.5 * (seg_s0 + seg_s1))
        # Polyline joint (shared end) — one parallel, not a second full grid
        for joint in (seg_s0, seg_s1):
            if s_lo + 1e-4 < joint < s_hi - 1e-4:
                lat_s.append(joint)
    # Unique
    lat_s_u: list[float] = []
    for s in sorted(lat_s):
        if not lat_s_u or abs(s - lat_s_u[-1]) > 1e-4:
            lat_s_u.append(s)
    for s in lat_s_u:
        spans = _inside_spans_1d(
            th_lo,
            th_hi,
            lambda th, _s=s: _uv_inside(th, _s),
            n_sample=max(
                96, int(abs(th_hi - th_lo) / (2 * math.pi) * 128) + 16
            ),
        )
        for ta, tb in spans:
            if abs(ta - th_lo) < 1e-4:
                ta = th_lo
            if abs(tb - th_hi) < 1e-4:
                tb = th_hi
            _emit_span(
                ta,
                tb,
                nsub=max(12, int(round(abs(tb - ta) / (2 * math.pi) * 48))),
                point_at=lambda th, _s=s: _at(th, _s),
                tip_edges=mer_edge_pts,
                keep_h=True,
            )

    return segs


def _emit_revolve_mesh(face: dict[str, Any]) -> list[str]:
    L: list[str] = []
    for a, b in _revolve_mesh_segs(face):
        L.append(f"  \\stpDmeshSeg{{{_fmt_xyz(a)}}}{{{_fmt_xyz(b)}}}")
    return L


def revolve_extent_pts(face: dict[str, Any], n: int = 24) -> list[tuple]:
    """Samples on revolved mantle for scale / envelope."""
    profile = face.get("profile") or []
    if len(profile) < 2:
        return []
    origin = Vec3(face["origin"])
    axis = Vec3(face["axis"]).normalize()
    u, v = Vec3(face["u"]), Vec3(face["v"])
    th0, th1 = float(face["th0"]), float(face["th1"])
    pts: list[tuple] = []
    for h, rho in (profile[0], profile[len(profile) // 2], profile[-1]):
        for i in range(n):
            th = th0 + (th1 - th0) * i / max(n - 1, 1)
            pts.append(_revolve_eval(origin, axis, u, v, h, rho, th))
    return pts


def _plane_frame(
    loops: list[list[Edge]],
) -> tuple[Vec3, Vec3, Vec3, list[tuple[float, float]]] | None:
    """Origin + orthonormal u,v in plane + outer ring in UV."""
    if not loops:
        return None
    poly = loop_polyline(loops[0], n=128)
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
    n: int = 128,
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
    ) -> list[tuple[float, float]]:
        spans = _hits_to_spans(outer_hits)
        for hh in hole_hits_list:
            spans = _clip_intervals_subtract(spans, _hits_to_spans(hh))
        return spans

    for k in range(1, max(nu, 0) + 1):
        uu = umin + (umax - umin) * k / (nu + 1)
        spans = _clipped_spans(
            _poly_line_hits(uv, const=uu, horizontal=False),
            [
                _poly_line_hits(huv, const=uu, horizontal=False)
                for huv in hole_uvs
            ],
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
        )
        _emit_spans(spans, horizontal=True, const=vv)
    return segs


class _Placement:
    """ACIS body transform. Copy and array keep local geometry and store the
    placement here: three axis vectors (linear part, scale included) plus
    translation. ``p' = M p + t``.
    """

    def __init__(self, x: Vec3, y: Vec3, z: Vec3, t: Vec3):
        self.x, self.y, self.z, self.t = x, y, z, t
        self.scale = max(x.magnitude, 1e-12)

    def is_identity(self) -> bool:
        return (
            self.t.magnitude_square < 1e-12
            and (self.x - Vec3(1, 0, 0)).magnitude_square < 1e-16
            and (self.y - Vec3(0, 1, 0)).magnitude_square < 1e-16
            and (self.z - Vec3(0, 0, 1)).magnitude_square < 1e-16
        )

    def point(self, p) -> Vec3:
        v = Vec3(p)
        return Vec3(
            v.x * self.x.x + v.y * self.y.x + v.z * self.z.x + self.t.x,
            v.x * self.x.y + v.y * self.y.y + v.z * self.z.y + self.t.y,
            v.x * self.x.z + v.y * self.y.z + v.z * self.z.z + self.t.z,
        )

    def direction(self, p) -> Vec3:
        v = Vec3(p)
        return Vec3(
            v.x * self.x.x + v.y * self.y.x + v.z * self.z.x,
            v.x * self.x.y + v.y * self.y.y + v.z * self.z.y,
            v.x * self.x.z + v.y * self.y.z + v.z * self.z.z,
        )


def _placement_from_records(records: dict[int, dict]) -> _Placement | None:
    """Body transform of a SAB lump. None when missing or identity."""
    tf = None
    for rec in records.values():
        if rec.get("type") != "body":
            continue
        for kind, val in rec["fields"]:
            if (
                kind == "POINTER"
                and isinstance(val, int)
                and records.get(val, {}).get("type") == "transform"
            ):
                tf = records[val]
                break
        if tf is not None:
            break
    if tf is None:
        found = [r for r in records.values() if r.get("type") == "transform"]
        if len(found) == 1:
            tf = found[0]
    if tf is None:
        return None
    vecs = [Vec3(v) for kind, v in tf["fields"] if kind == "DIRECTION_VEC"]
    if len(vecs) < 4:
        return None
    pl = _Placement(vecs[0], vecs[1], vecs[2], vecs[3])
    return None if pl.is_identity() else pl


def _edge_under_matrix(edge: Edge, matrix, scale: float) -> Edge:
    """Block insert / array item: block coordinates → parent coordinates."""
    if isinstance(edge, EdgeLine):
        return EdgeLine(_v3(matrix.transform(edge.a)), _v3(matrix.transform(edge.b)))
    if isinstance(edge, EdgeCircle):
        n = Vec3(matrix.transform_direction(edge.normal))
        if n.magnitude_square < 1e-18:
            n = Vec3(edge.normal)
        else:
            n = n.normalize()
        return EdgeCircle(_v3(matrix.transform(edge.center)), _v3(n), float(edge.radius) * scale)
    if isinstance(edge, EdgeArc):
        n = Vec3(matrix.transform_direction(edge.normal))
        if n.magnitude_square < 1e-18:
            n = Vec3(edge.normal)
        else:
            n = n.normalize()
        return EdgeArc(
            _v3(matrix.transform(edge.center)),
            _v3(n),
            _v3(matrix.transform_direction(edge.major)),
            float(edge.ratio),
            float(edge.t0),
            float(edge.t1),
        )
    if isinstance(edge, EdgeSpline):
        return EdgeSpline(
            int(edge.degree),
            tuple(_v3(matrix.transform(p)) for p in edge.cps),
            edge.knots,
        )
    return edge


def transform_analytic_face(face: dict[str, Any], matrix) -> dict[str, Any]:
    """Place a face that lives in a block (associative array item, INSERT)."""
    sx = Vec3(matrix.transform_direction((1.0, 0.0, 0.0))).magnitude
    sy = Vec3(matrix.transform_direction((0.0, 1.0, 0.0))).magnitude
    sz = Vec3(matrix.transform_direction((0.0, 0.0, 1.0))).magnitude
    scale = (sx + sy + sz) / 3.0 if (sx + sy + sz) > 1e-12 else 1.0
    out = dict(face)
    out["loops"] = [
        [_edge_under_matrix(e, matrix, scale) for e in lp]
        for lp in (face.get("loops") or [])
    ]
    if face.get("cen") is not None:
        out["cen"] = _v3(matrix.transform(face["cen"]))
    if face.get("origin") is not None:
        out["origin"] = _v3(matrix.transform(face["origin"]))
    for key in ("axis", "u", "v"):
        if face.get(key) is None:
            continue
        d = Vec3(matrix.transform_direction(face[key]))
        if d.magnitude_square > 1e-18:
            d = d.normalize()
        out[key] = _v3(d)
    if face.get("radius") is not None:
        out["radius"] = float(face["radius"]) * scale
    if face.get("h0") is not None:
        out["h0"] = float(face["h0"]) * scale
    if face.get("h1") is not None:
        out["h1"] = float(face["h1"]) * scale
    if face.get("profile"):
        out["profile"] = [
            (float(h) * scale, float(rho) * scale) for h, rho in face["profile"]
        ]
    return out


def _map_edge(edge: Edge, pl: _Placement) -> Edge:
    if isinstance(edge, EdgeLine):
        return EdgeLine(_v3(pl.point(edge.a)), _v3(pl.point(edge.b)))
    if isinstance(edge, EdgeCircle):
        n = pl.direction(edge.normal)
        if n.magnitude_square < 1e-18:
            n = Vec3(edge.normal)
        else:
            n = n.normalize()
        return EdgeCircle(_v3(pl.point(edge.center)), _v3(n), float(edge.radius) * pl.scale)
    if isinstance(edge, EdgeArc):
        n = pl.direction(edge.normal)
        if n.magnitude_square < 1e-18:
            n = Vec3(edge.normal)
        else:
            n = n.normalize()
        return EdgeArc(
            _v3(pl.point(edge.center)),
            _v3(n),
            _v3(pl.direction(edge.major)),
            float(edge.ratio),
            float(edge.t0),
            float(edge.t1),
        )
    if isinstance(edge, EdgeSpline):
        return EdgeSpline(
            int(edge.degree),
            tuple(_v3(pl.point(p)) for p in edge.cps),
            edge.knots,
        )
    return edge


def _bake_surface_record(rec: dict, pl: _Placement) -> None:
    """Move a cone/plane/spline surface record into the body placement."""
    fields = []
    dbl_i = 0
    for kind, val in rec["fields"]:
        if kind == "LOCATION_VEC":
            fields.append((kind, pl.point(val)))
        elif kind == "DIRECTION_VEC":
            fields.append((kind, pl.direction(val)))
        elif (
            kind == "DOUBLE"
            and rec.get("type") == "cone-surface"
            and dbl_i == 3
            and abs(pl.scale - 1.0) > 1e-9
        ):
            dbl_i += 1
            fields.append((kind, float(val) * pl.scale))
        else:
            if kind == "DOUBLE":
                dbl_i += 1
            fields.append((kind, val))
    rec["fields"] = fields


def _n_ctrl_from_knots(knots: list[float], degree: int, n_pts: int) -> int | None:
    """Control-point count implied by an ACIS knot vector (end mult may be degree)."""
    if degree < 1 or not knots:
        return None
    for n in range(degree + 1, n_pts + 1):
        need = n + degree + 1
        if len(knots) == need or len(knots) == need - 2:
            return n
    return None


def _closest_profile_u(bsp: BSpline, target: Vec3, shift: Vec3) -> tuple[float, float]:
    """Parameter on ``bsp`` (knot domain) closest to ``target - shift``."""
    knots = list(bsp.knots())
    degree = int(bsp.order) - 1
    u0 = float(knots[degree])
    u1 = float(knots[-(degree + 1)])

    def dist(u: float) -> float:
        return (Vec3(bsp.point(u)) + shift - target).magnitude

    best_u, best_d = u0, dist(u0)
    n = 48
    for i in range(n + 1):
        u = u0 + (u1 - u0) * i / n
        d = dist(u)
        if d < best_d:
            best_u, best_d = u, d
    lo = max(u0, best_u - (u1 - u0) / n)
    hi = min(u1, best_u + (u1 - u0) / n)
    for _ in range(30):
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        if dist(m1) < dist(m2):
            hi = m2
        else:
            lo = m1
    u = 0.5 * (lo + hi)
    return u, dist(u)


def _profile_span_spline(
    bsp: BSpline, ua: float, ub: float, shift: Vec3
) -> EdgeSpline | None:
    """NURBS of ``bsp`` on ``[ua, ub]``, then translated by ``shift``.

    ``ua > ub`` reverses the piece so the stroke follows the coedge.
    """
    degree = int(bsp.order) - 1
    knots0 = [float(k) for k in bsp.knots()]
    u0 = knots0[degree]
    u1 = knots0[-(degree + 1)]
    lo, hi = (ua, ub) if ua <= ub else (ub, ua)
    span = abs(u1 - u0)
    # A closest-point search stops a hair inside the end. That span is the
    # whole rail; splitting it moves the control points off the stored NURBS.
    end_tol = 1e-5 * max(span, 1.0)
    if lo <= u0 + end_tol:
        lo = u0
    if hi >= u1 - end_tol:
        hi = u1
    eps = 1e-8 * max(1.0, span)
    curve = bsp
    try:
        if lo > u0 + eps:
            _, curve = curve.split(lo)
        if hi < u1 - eps:
            curve, _ = curve.split(hi)
    except Exception:
        return None
    cps = [Vec3(p) + shift for p in curve.control_points]
    knots = [float(k) for k in curve.knots()]
    if len(cps) < 2 or len(knots) < degree + len(cps) + 1:
        return None
    if ua > ub:
        cps = list(reversed(cps))
        k0, k1 = knots[0], knots[-1]
        knots = [k0 + k1 - k for k in reversed(knots)]
    return EdgeSpline(degree, tuple(_v3(p) for p in cps), tuple(knots))


def _restore_profile_edges(
    loops: list[list[Edge]], extrude: dict[str, Any]
) -> None:
    """Replace a chord that is really the uncut extrusion profile.

    After a trim, ACIS often keeps that rail as an intcurve ``ref`` with no
    control points. The edge then falls back to the straight line between its
    vertices, so the surviving profile is stroked as a chord.
    """
    raw = extrude.get("cps") or ()
    if len(raw) < 2:
        return
    cps = [Vec3(p) for p in raw]
    degree = int(extrude.get("degree") or 1)
    order = degree + 1
    knots = list(extrude["knots"]) if extrude.get("knots") else None
    if knots and len(knots) >= order + len(cps):
        bsp = BSpline(cps, order=order, knots=knots)
    else:
        bsp = BSpline(cps, order=order)
    V = Vec3(extrude.get("vector") or (0.0, 0.0, 0.0))
    reach = max(float(V.magnitude), max(cps[0].distance(p) for p in cps), 1.0)
    tol = max(1e-2, 1e-5 * reach)
    for li, edges in enumerate(loops):
        rebuilt: list[Edge] = []
        for e in edges:
            if not isinstance(e, EdgeLine):
                rebuilt.append(e)
                continue
            best: tuple[float, float, float, Vec3] | None = None
            for shift in (Vec3(0, 0, 0), V):
                u0, d0 = _closest_profile_u(bsp, Vec3(e.a), shift)
                u1, d1 = _closest_profile_u(bsp, Vec3(e.b), shift)
                dist = max(d0, d1)
                if best is None or dist < best[0]:
                    best = (dist, u0, u1, shift)
            if best is None or best[0] > tol or abs(best[1] - best[2]) < 1e-4:
                rebuilt.append(e)
                continue
            spl = _profile_span_spline(bsp, best[1], best[2], best[3])
            rebuilt.append(spl if spl is not None else e)
        loops[li] = rebuilt


def _extrude_from_spline_surface(srec: dict | None) -> dict[str, Any] | None:
    """Profile NURBS plus its translation, from an ACIS ``cyl_spl_sur`` net.

    A boolean trim stores the extruded spline as one spline-surface whose
    v direction is degree 1. The face boundary is the trim, not the two
    profile rails, so the boundary rail test does not see the extrusion.
    """
    if not srec:
        return None
    fields = srec.get("fields") or []
    i = 0
    while i < len(fields):
        if fields[i] != ("ENTITY_TYPE", "nubs"):
            i += 1
            continue
        parsed = _surface_extrude_nubs(fields, i)
        if parsed is not None:
            return parsed
        i += 1
    return None


def _surface_extrude_nubs(fields: list, i: int) -> dict[str, Any] | None:
    """Parse one bs3 nubs. None when this token is a curve nubs or not an extrusion."""
    if i + 2 >= len(fields):
        return None
    if fields[i + 1][0] != "INT" or fields[i + 2][0] != "INT":
        return None
    u_deg = int(fields[i + 1][1])
    v_deg = int(fields[i + 2][1])
    if u_deg < 1 or v_deg != 1:
        return None
    j = i + 3
    while j < len(fields) and fields[j][0] == "ENUM":
        j += 1
    if j + 1 >= len(fields) or fields[j][0] != "INT" or fields[j + 1][0] != "INT":
        return None
    nu = int(fields[j][1])
    nv = int(fields[j + 1][1])
    if nu < 2 or nv < 2:
        return None
    j += 2

    def _pairs(n: int) -> list[float] | None:
        nonlocal j
        knots: list[float] = []
        for _ in range(n):
            if j + 1 >= len(fields):
                return None
            if fields[j][0] != "DOUBLE" or fields[j + 1][0] != "INT":
                return None
            mult = int(fields[j + 1][1])
            if mult < 1 or mult > 32:
                return None
            knots.extend([float(fields[j][1])] * mult)
            j += 2
        return knots

    ku = _pairs(nu)
    kv = _pairs(nv)
    if not ku or not kv:
        return None
    dbls: list[float] = []
    while j < len(fields) and fields[j][0] == "DOUBLE":
        dbls.append(float(fields[j][1]))
        j += 1
    n_pts = len(dbls) // 3
    n_u = _n_ctrl_from_knots(ku, u_deg, n_pts)
    n_v = _n_ctrl_from_knots(kv, v_deg, n_pts)
    if n_u is None or n_v is None or n_v != 2 or n_u * n_v != n_pts:
        return None
    cps = [Vec3(dbls[k], dbls[k + 1], dbls[k + 2]) for k in range(0, 3 * n_pts, 3)]
    row0 = cps[:n_u]
    row1 = cps[n_u:]
    V = row1[0] - row0[0]
    if V.magnitude_square < 1e-12:
        return None
    for c in range(n_u):
        if (row1[c] - row0[c] - V).magnitude > max(1e-3, 1e-4 * float(V.magnitude)):
            return None
    clamped = _clamp_knot_vector(ku, u_deg, n_u)
    if clamped is None:
        return None
    return {
        "degree": int(u_deg),
        "knots": tuple(float(k) for k in clamped),
        "cps": tuple(_v3(p) for p in row0),
        "vector": _v3(V),
    }


def _map_extrude(extrude: dict[str, Any], pl: _Placement | None) -> dict[str, Any]:
    """Put the extrusion profile into the same placement as the boundary edges.

    Spline-surface control points are raw SAB doubles. ``_bake_surface_record``
    moves cone and plane vectors only, so a copied body keeps the profile in
    local coordinates while the loops are already in world coordinates.
    """
    if pl is None:
        return extrude
    cps = tuple(_v3(pl.point(p)) for p in extrude.get("cps") or ())
    return {**extrude, "cps": cps, "vector": _v3(pl.direction(extrude.get("vector") or (0, 0, 0)))}


def _de_boor_point(
    u: float, degree: int, knots: Sequence[float], cps: Sequence
) -> Vec3:
    """Point on a clamped B-spline. ``knots`` has length ``len(cps)+degree+1``."""
    n = len(cps)
    if n == 0:
        return Vec3(0, 0, 0)
    if n == 1 or degree < 1:
        return Vec3(cps[0])
    u = float(u)
    if u <= float(knots[degree]):
        return Vec3(cps[0])
    if u >= float(knots[n]):
        return Vec3(cps[-1])
    lo, hi = degree, n - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if u < float(knots[mid]):
            hi = mid
        elif u >= float(knots[mid + 1]):
            lo = mid + 1
        else:
            lo = mid
            break
    k = lo
    d = [Vec3(cps[j]) for j in range(k - degree, k + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            i = k - degree + j
            den = float(knots[i + degree - r + 1]) - float(knots[i])
            a = 0.0 if abs(den) < 1e-15 else (u - float(knots[i])) / den
            d[j] = d[j - 1] * (1.0 - a) + d[j] * a
    return d[degree]


def _spline_net_counts(
    ku: list[float], kv: list[float], u_deg: int, v_deg: int, n_pts: int
) -> tuple[int, int] | None:
    """``(n_u, n_v)`` whose product is the control net. Prefer ACIS end-multiplicity."""

    def _cands(knots: list[float], degree: int) -> list[tuple[int, bool]]:
        out: list[tuple[int, bool]] = []
        for n in range(degree + 1, n_pts + 1):
            need = n + degree + 1
            if len(knots) == need:
                out.append((n, False))
            elif len(knots) == need - 2:
                out.append((n, True))
        return out

    best: tuple[tuple[bool, bool, bool], int, int] | None = None
    for nu, su in _cands(ku, u_deg):
        if n_pts % nu:
            continue
        nv = n_pts // nu
        for nvv, sv in _cands(kv, v_deg):
            if nvv != nv:
                continue
            score = (su and sv, su, sv)
            if best is None or score > best[0]:
                best = (score, nu, nv)
    if best is None:
        return None
    return best[1], best[2]


def _spline_surface_nubs(fields: list, i: int) -> dict[str, Any] | None:
    """Tensor-product bs3 net. None for a curve nubs or an unreadable surface."""
    if i + 2 >= len(fields):
        return None
    if fields[i + 1][0] != "INT" or fields[i + 2][0] != "INT":
        return None
    u_deg = int(fields[i + 1][1])
    v_deg = int(fields[i + 2][1])
    if u_deg < 1 or v_deg < 1 or u_deg > 16 or v_deg > 16:
        return None
    j = i + 3
    while j < len(fields) and fields[j][0] == "ENUM":
        j += 1
    if j + 1 >= len(fields) or fields[j][0] != "INT" or fields[j + 1][0] != "INT":
        return None
    nu = int(fields[j][1])
    nv = int(fields[j + 1][1])
    if nu < 2 or nv < 2:
        return None
    j += 2

    def _pairs(n: int) -> list[float] | None:
        nonlocal j
        knots: list[float] = []
        for _ in range(n):
            if j + 1 >= len(fields):
                return None
            if fields[j][0] != "DOUBLE" or fields[j + 1][0] != "INT":
                return None
            mult = int(fields[j + 1][1])
            if mult < 1 or mult > 32:
                return None
            knots.extend([float(fields[j][1])] * mult)
            j += 2
        return knots

    ku = _pairs(nu)
    kv = _pairs(nv)
    if not ku or not kv:
        return None
    dbls: list[float] = []
    while j < len(fields) and fields[j][0] == "DOUBLE":
        dbls.append(float(fields[j][1]))
        j += 1
    n_pts = len(dbls) // 3
    counts = _spline_net_counts(ku, kv, u_deg, v_deg, n_pts)
    if counts is None:
        return None
    n_u, n_v = counts
    uk = _clamp_knot_vector(ku, u_deg, n_u)
    vk = _clamp_knot_vector(kv, v_deg, n_v)
    if uk is None or vk is None:
        return None
    cps = tuple(
        _v3(Vec3(dbls[k], dbls[k + 1], dbls[k + 2]))
        for k in range(0, 3 * n_u * n_v, 3)
    )
    return {
        "u_degree": u_deg,
        "v_degree": v_deg,
        "u_knots": tuple(float(k) for k in uk),
        "v_knots": tuple(float(k) for k in vk),
        "n_u": n_u,
        "n_v": n_v,
        "cps": cps,
        "u0": float(uk[u_deg]),
        "u1": float(uk[-(u_deg + 1)]),
        "v0": float(vk[v_deg]),
        "v1": float(vk[-(v_deg + 1)]),
    }


def _spline_surface_from_record(srec: dict | None) -> dict[str, Any] | None:
    """Loft / skin bs3 surface. An extrusion (v degree 1) is left to that path."""
    if not srec:
        return None
    fields = srec.get("fields") or []
    i = 0
    while i < len(fields):
        if fields[i] != ("ENTITY_TYPE", "nubs"):
            i += 1
            continue
        parsed = _spline_surface_nubs(fields, i)
        if parsed is not None and int(parsed["v_degree"]) > 1 and int(parsed["n_v"]) > 2:
            return parsed
        i += 1
    return None


def _map_spline_surface(
    surf: dict[str, Any], pl: _Placement | None
) -> dict[str, Any]:
    if pl is None:
        return surf
    cps = tuple(_v3(pl.point(p)) for p in surf["cps"])
    return {**surf, "cps": cps}


def _spline_cp(surf: dict[str, Any], i: int, j: int) -> tuple:
    """Control point ``P[i,j]``, ``i`` along u (u varies fastest)."""
    return surf["cps"][j * int(surf["n_u"]) + i]


def _spline_point(surf: dict[str, Any], u: float, v: float) -> Vec3:
    n_u = int(surf["n_u"])
    cols = []
    for i in range(n_u):
        column = [_spline_cp(surf, i, j) for j in range(int(surf["n_v"]))]
        cols.append(_de_boor_point(v, int(surf["v_degree"]), surf["v_knots"], column))
    return _de_boor_point(u, int(surf["u_degree"]), surf["u_knots"], cols)


def _spline_uv_grid(surf: dict[str, Any]) -> tuple[list[float], list[float], list[Vec3]]:
    """One sample grid per surface, reused while projecting the trim."""
    cached = surf.get("_uv_grid")
    if cached is not None:
        return cached
    u0, u1 = float(surf["u0"]), float(surf["u1"])
    v0, v1 = float(surf["v0"]), float(surf["v1"])
    nu, nv = 24, 12
    us = [u0 + (u1 - u0) * i / nu for i in range(nu + 1)]
    vs = [v0 + (v1 - v0) * j / nv for j in range(nv + 1)]
    pts = [_spline_point(surf, u, v) for v in vs for u in us]
    cached = (us, vs, pts)
    surf["_uv_grid"] = cached
    return cached


def _spline_uv_of_point(surf: dict[str, Any], p: Vec3) -> tuple[float, float, float]:
    """``(u, v, distance)`` of the closest point on the net."""
    us, vs, pts = _spline_uv_grid(surf)
    u0, u1 = us[0], us[-1]
    v0, v1 = vs[0], vs[-1]
    nu = len(us) - 1
    best_i, best_d = 0, float("inf")
    for i, q in enumerate(pts):
        d = q.distance(p)
        if d < best_d:
            best_i, best_d = i, d
    iu, iv = best_i % len(us), best_i // len(us)
    best_u, best_v = us[iu], vs[iv]
    du = (u1 - u0) / nu
    dv = (v1 - v0) / max(len(vs) - 1, 1)
    for _ in range(8):
        for su in (-1.0, 0.0, 1.0):
            for sv in (-1.0, 0.0, 1.0):
                u = min(u1, max(u0, best_u + su * du))
                v = min(v1, max(v0, best_v + sv * dv))
                d = _spline_point(surf, u, v).distance(p)
                if d < best_d:
                    best_u, best_v, best_d = u, v, d
        du *= 0.5
        dv *= 0.5
    return best_u, best_v, best_d


def _domain_boundary_splines(surf: dict[str, Any]) -> list[BSpline]:
    """The four clamped edges of the parameter domain, as curves."""
    n_u, n_v = int(surf["n_u"]), int(surf["n_v"])
    ud, vd = int(surf["u_degree"]), int(surf["v_degree"])
    uk, vk = list(surf["u_knots"]), list(surf["v_knots"])
    rows = (
        [Vec3(_spline_cp(surf, i, 0)) for i in range(n_u)],
        [Vec3(_spline_cp(surf, i, n_v - 1)) for i in range(n_u)],
    )
    cols = (
        [Vec3(_spline_cp(surf, 0, j)) for j in range(n_v)],
        [Vec3(_spline_cp(surf, n_u - 1, j)) for j in range(n_v)],
    )
    out = [BSpline(row, order=ud + 1, knots=uk) for row in rows]
    out.extend(BSpline(col, order=vd + 1, knots=vk) for col in cols)
    return out


def _curve_span_bow(bsp: BSpline, ua: float, ub: float) -> float:
    lo, hi = (ua, ub) if ua <= ub else (ub, ua)
    a = Vec3(bsp.point(lo))
    b = Vec3(bsp.point(hi))
    ab = b - a
    L2 = float(ab.dot(ab))
    if L2 < 1e-12:
        return 0.0
    bow = 0.0
    for s in range(1, 16):
        u = lo + (hi - lo) * s / 16
        p = Vec3(bsp.point(u))
        t = max(0.0, min(1.0, float((p - a).dot(ab) / L2)))
        bow = max(bow, (a + ab * t - p).magnitude)
    return bow


def _restore_domain_edges(loops: list[list[Edge]], surf: dict[str, Any]) -> None:
    """Replace a chord that is really one edge of the spline surface.

    A loft stores that rail as an intcurve ``ref``. The edge then falls back
    to the straight line between the surface corners.
    """
    curves = _domain_boundary_splines(surf)
    reach = 1.0
    for bsp in curves:
        a = Vec3(bsp.control_points[0])
        b = Vec3(bsp.control_points[-1])
        reach = max(reach, a.distance(b))
    tol = max(0.5, 1e-5 * reach)
    for li, edges in enumerate(loops):
        rebuilt: list[Edge] = []
        for e in edges:
            if not isinstance(e, EdgeLine):
                rebuilt.append(e)
                continue
            best: tuple[float, float, float, BSpline] | None = None
            for bsp in curves:
                u0, d0 = _closest_profile_u(bsp, Vec3(e.a), Vec3(0, 0, 0))
                u1, d1 = _closest_profile_u(bsp, Vec3(e.b), Vec3(0, 0, 0))
                dist = max(d0, d1)
                if best is None or dist < best[0]:
                    best = (dist, u0, u1, bsp)
            if (
                best is None
                or best[0] > tol
                or abs(best[1] - best[2]) < 1e-4
                or _curve_span_bow(best[3], best[1], best[2]) < max(1.0, 1e-4 * reach)
            ):
                rebuilt.append(e)
                continue
            spl = _profile_span_spline(best[3], best[1], best[2], Vec3(0, 0, 0))
            rebuilt.append(spl if spl is not None else e)
        loops[li] = rebuilt


def _surface_periodic_u(surf: dict[str, Any]) -> bool:
    """True when the u=start and u=end sections are the same curve (closed loft)."""
    u0, u1 = float(surf["u0"]), float(surf["u1"])
    v0, v1 = float(surf["v0"]), float(surf["v1"])
    if u1 - u0 < 1e-9:
        return False
    span = _spline_point(surf, u0, v0).distance(_spline_point(surf, u1, v1))
    tol = max(1e-2, 1e-5 * max(span, 1.0))
    for v in (v0, 0.5 * (v0 + v1), v1):
        if _spline_point(surf, u0, v).distance(_spline_point(surf, u1, v)) > tol:
            return False
    return True


def _unwrap_periodic_u(
    uv: list[tuple[float, float]], u0: float, u1: float
) -> list[tuple[float, float]]:
    """Keep u continuous. On a closed loft, u=0 and u=1 are the same seam."""
    if len(uv) < 2:
        return uv
    period = u1 - u0
    if period < 1e-9:
        return uv
    out = [uv[0]]
    prev = uv[0][0]
    for u, v in uv[1:]:
        cand = u
        while cand - prev > period / 2.0:
            cand -= period
        while prev - cand > period / 2.0:
            cand += period
        out.append((cand, v))
        prev = cand
    return out


def _spline_param_uv(
    edges: list[Edge], surf: dict[str, Any]
) -> list[tuple[float, float]]:
    """Trim loop in the surface parameters ``(u, v)``."""
    pts3: list[tuple] = []
    for e in edges:
        # The clip only needs the trim's shape in (u, v). The drawn tips are
        # snapped back onto the real boundary curve.
        if isinstance(e, EdgeLine):
            seg = [e.a, e.b]
        else:
            seg = _edge_samples(e, n=40)
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
        u, v, _d = _spline_uv_of_point(surf, Vec3(p))
        out.append((u, v))
    if _surface_periodic_u(surf):
        out = _unwrap_periodic_u(out, float(surf["u0"]), float(surf["u1"]))
    if out and (
        abs(out[0][0] - out[-1][0]) > 1e-9 or abs(out[0][1] - out[-1][1]) > 1e-9
    ):
        out.append(out[0])
    return out


def _closed_loft_domain(loops: list[list[Edge]], surf: dict[str, Any]) -> bool:
    """Untrimmed closed loft: the boundary is the two end sections and the seam."""
    if not loops or loops[1:] or not _surface_periodic_u(surf):
        return False
    u0, u1 = float(surf["u0"]), float(surf["u1"])
    v0, v1 = float(surf["v0"]), float(surf["v1"])
    du, dv = 0.04 * (u1 - u0), 0.08 * (v1 - v0)
    for e in loops[0]:
        pts = [e.a, e.b] if isinstance(e, EdgeLine) else _edge_samples(e, n=12)
        for p in pts:
            u, v, _d = _spline_uv_of_point(surf, Vec3(p))
            on_section = min(abs(v - v0), abs(v - v1)) <= dv
            on_seam = min(abs(u - u0), abs(u - u1)) <= du
            if not (on_section or on_seam):
                return False
    return True


def _periodic_loft_grid(
    loops: list[list[Edge]], surf: dict[str, Any], n_u: int, n_v: int
) -> list[tuple[tuple, tuple]]:
    """Full iso-parameter grid. u=0 and u=1 are the same seam, so rings close."""
    u0, u1 = float(surf["u0"]), float(surf["u1"])
    v0, v1 = float(surf["v0"]), float(surf["v1"])
    bd = _boundary_polylines(loops)
    flat = [p for seg in bd for p in seg]
    snap_tol = 0.0
    if flat:
        xs = [p[0] for p in flat]
        ys = [p[1] for p in flat]
        zs = [p[2] for p in flat]
        diag = math.hypot(
            max(xs) - min(xs),
            math.hypot(max(ys) - min(ys), max(zs) - min(zs)),
        )
        snap_tol = max(1.0, 0.03 * diag)

    def _tip(p: tuple) -> tuple:
        return _snap_point_to_polylines(p, bd, snap_tol)

    segs: list[tuple[tuple, tuple]] = []

    def _at(u: float, v: float) -> tuple:
        return _v3(_spline_point(surf, u, v))

    for k in range(max(int(n_u), 1)):
        u = u0 + (u1 - u0) * k / n_u
        n_sub = max(6, 4 * (int(surf["n_v"]) - 1))
        prev = _tip(_at(u, v0))
        for j in range(1, n_sub + 1):
            cur = _at(u, v0 + (v1 - v0) * j / n_sub)
            if j == n_sub:
                cur = _tip(cur)
            if Vec3(prev).distance(Vec3(cur)) > 1e-9:
                segs.append((prev, cur))
            prev = cur
    for k in range(1, max(int(n_v), 1)):
        v = v0 + (v1 - v0) * k / n_v
        n_sub = 48
        prev = _at(u0, v)
        for j in range(1, n_sub + 1):
            cur = _at(u0 + (u1 - u0) * j / n_sub, v)
            if Vec3(prev).distance(Vec3(cur)) > 1e-9:
                segs.append((prev, cur))
            prev = cur
    return segs


def _spline_mesh_segs(
    loops: list[list[Edge]],
    surf: dict[str, Any],
    n_u: int = 8,
    n_v: int = 6,
) -> list[tuple[tuple, tuple]]:
    """Iso-parameter curves of a lofted spline, clipped to the trim in ``(u, v)``."""
    if not loops or not surf:
        return []
    u0, u1 = float(surf["u0"]), float(surf["u1"])
    v0, v1 = float(surf["v0"]), float(surf["v1"])
    if u1 - u0 < 1e-12 or v1 - v0 < 1e-12:
        return []
    if _closed_loft_domain(loops, surf):
        return _periodic_loft_grid(loops, surf, n_u, n_v)
    outer = _spline_param_uv(loops[0], surf)
    holes = [_spline_param_uv(h, surf) for h in loops[1:]]
    holes = [h for h in holes if len(h) >= 3]
    if len(outer) < 3:
        return []

    def _at(u: float, v: float) -> tuple:
        return _v3(_spline_point(surf, u, v))

    bd = _boundary_polylines(loops)
    flat = [p for seg in bd for p in seg]
    snap_tol = 0.0
    if flat:
        xs = [p[0] for p in flat]
        ys = [p[1] for p in flat]
        zs = [p[2] for p in flat]
        diag = math.hypot(
            max(xs) - min(xs),
            math.hypot(max(ys) - min(ys), max(zs) - min(zs)),
        )
        # A loft net only approximates an analytic section. Without a hole,
        # seat the tip on that section. A hole keeps the snap tight.
        snap_tol = max(1e-3, (0.03 if len(loops) < 2 else 0.001) * diag)

    def _tip(p: tuple) -> tuple:
        return _snap_point_to_polylines(p, bd, snap_tol)

    segs: list[tuple[tuple, tuple]] = []
    # Constant u: curves across the loft sections.
    for k in range(1, max(n_u, 1)):
        u = u0 + (u1 - u0) * k / n_u
        spans = _hits_to_spans(_poly_line_hits(outer, const=u, horizontal=False))
        for huv in holes:
            spans = _clip_intervals_subtract(
                spans,
                _hits_to_spans(_poly_line_hits(huv, const=u, horizontal=False)),
            )
        for va, vb in spans:
            va = max(v0, min(v1, va))
            vb = max(v0, min(v1, vb))
            if vb < va:
                va, vb = vb, va
            if vb - va < 1e-7:
                continue
            n_sub = max(6, int(round((vb - va) / (v1 - v0) * (int(surf["n_v"]) - 1) * 4)))
            pts = [_at(u, va + (vb - va) * j / n_sub) for j in range(n_sub + 1)]
            pts[0] = _tip(pts[0])
            pts[-1] = _tip(pts[-1])
            for j in range(n_sub):
                if Vec3(pts[j]).distance(Vec3(pts[j + 1])) > 1e-9:
                    segs.append((pts[j], pts[j + 1]))
    # Constant v: curves along a cross-section.
    for k in range(1, max(n_v, 1)):
        v = v0 + (v1 - v0) * k / n_v
        spans = _hits_to_spans(_poly_line_hits(outer, const=v, horizontal=True))
        for huv in holes:
            spans = _clip_intervals_subtract(
                spans,
                _hits_to_spans(_poly_line_hits(huv, const=v, horizontal=True)),
            )
        for ua, ub in spans:
            ua = max(u0, min(u1, ua))
            ub = max(u0, min(u1, ub))
            if ub < ua:
                ua, ub = ub, ua
            if ub - ua < 1e-7:
                continue
            n_sub = max(8, int(round((ub - ua) / (u1 - u0) * (int(surf["n_u"]) - 1) * 3)))
            pts = [_at(ua + (ub - ua) * j / n_sub, v) for j in range(n_sub + 1)]
            pts[0] = _tip(pts[0])
            pts[-1] = _tip(pts[-1])
            for j in range(n_sub):
                if Vec3(pts[j]).distance(Vec3(pts[j + 1])) > 1e-9:
                    segs.append((pts[j], pts[j + 1]))
    return segs


def faces_from_sab(entity) -> list[dict[str, Any]]:
    """One analytic face dict per SAB face.

    Display is AutoCAD-style wire mesh (no fill):
      - plane-surface → ``plane`` (boundary + UV grid)
      - cone-surface (cylinder) → ``cylinder``; tapered → ``revolve``
      - torus / revolved spline profile → ``revolve``
      - spline-surface with 4-edge ruled loop → ``ruled``
      - loft / skin spline-surface → ``spline`` (domain edges + iso-parameter mesh)
      - other → ``wire`` (boundary only)
    FE always keeps boundary edge equations.

    COPY / ARRAY store one local body plus a transform. The transform is
    applied to the boundary (and to the surface record) before classification.
    """
    sab = getattr(entity, "sab", None) or getattr(entity, "acis_data", None)
    if not sab:
        return []
    try:
        records = _parse_sab_records(sab)
    except Exception:
        return []
    placement = _placement_from_records(records)
    baked_surf: set[int] = set()
    # Entity-level REVOLVEDSURFACE axis / sweep angle (shared by multi-face)
    ent_axis = None
    ent_origin = None
    ent_th0 = None
    ent_th1 = None
    try:
        ap = getattr(entity.dxf, "axis_point", None)
        av = getattr(entity.dxf, "axis_vector", None)
        if ap is not None and av is not None:
            ent_origin = Vec3(ap)
            av = Vec3(av)
            if av.magnitude_square > 1e-18:
                ent_axis = av.normalize()
        ang = getattr(entity.dxf, "revolve_angle", None)
        st = getattr(entity.dxf, "start_angle", None)
        if ang is not None and abs(float(ang)) > 1e-6:
            ent_th0 = float(st or 0.0)
            ent_th1 = ent_th0 + float(ang)
    except Exception:
        pass
    out: list[dict[str, Any]] = []
    for face_id in [rid for rid, r in records.items() if r["type"] == "face"]:
        loops: list[list[Edge]] = []
        for loop_id in _sab_loop_list(records, face_id):
            edges = _curve_loop_from_sab(records, loop_id)
            if placement is not None:
                edges = [_map_edge(e, placement) for e in edges]
            if edges:
                loops.append(edges)
        if not loops:
            continue
        loops = order_curve_loops(loops)
        _sid, stype, srec = _sab_face_surface(records, face_id)
        if (
            placement is not None
            and srec is not None
            and _sid not in baked_surf
        ):
            baked_surf.add(_sid)
            _bake_surface_record(srec, placement)
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
            # tapered cone → revolve below
        elif stype == "plane-surface":
            cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
            out.append({"kind": "plane", "loops": loops, "cen": _k(cen)})
            continue
        extrude = (
            _extrude_from_spline_surface(srec) if stype == "spline-surface" else None
        )
        if extrude is not None:
            extrude = _map_extrude(extrude, placement)
            _restore_profile_edges(loops, extrude)
        # A loft net (degree > 1 along the sections) is not a ruled strip, even
        # when the trim is two curves joined by two generators.
        spline = (
            _spline_surface_from_record(srec)
            if stype == "spline-surface" and extrude is None
            else None
        )
        if spline is not None and loops:
            spline = _map_spline_surface(spline, placement)
            _restore_domain_edges(loops, spline)
            cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
            out.append(
                {"kind": "spline", "loops": loops, "cen": _k(cen), "spline": spline}
            )
            continue
        if stype == "spline-surface" and loops and (
            _is_ruled_loop(loops[0])
            or _extract_extrusion_rails(loops[0]) is not None
            or extrude is not None
        ):
            # ruled / extrusion strip (curved latitudes); holes OK.
            # A trimmed cyl_spl_sur keeps the surface extrusion even when the
            # boundary is the intersection curve rather than the two rails.
            cen = curve_loops_centroid(loops) or (0.0, 0.0, 0.0)
            face: dict[str, Any] = {"kind": "ruled", "loops": loops, "cen": _k(cen)}
            if extrude is not None:
                face["extrude"] = extrude
            out.append(face)
            continue
        # Revolve: torus / tapered cone / spline·LWPOLYLINE·arc profiles
        if loops:
            rev = _revolve_params_from_loop(
                loops[0],
                axis=ent_axis,
                origin=ent_origin,
                th0=ent_th0,
                th1=ent_th1,
            )
            if rev is not None:
                out.append({"kind": "revolve", "loops": loops, **rev})
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
    - SURFACE / 3DSOLID / BODY → cylinder / ruled / plane / revolve.
      A non-region face whose boundary curves are coplanar is filled like
      REGION when emitted (see ``format_stp_analytic_face``).
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
        # TeX evaluates the NURBS (degree, knots, control points) with de Boor.
        cps = ",".join("{" + _fmt_xyz(p) + "}" for p in e.cps)
        knot = ""
        if e.knots:
            knot = "[" + ",".join(format(float(k), ".10g") for k in e.knots) + "]"
        return f"{indent}\\stpDedgeSpline{{{e.degree}}}{knot}{{{cps}}}"
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


def _boundary_polylines(loops: list[list[Edge]]) -> list[list[tuple]]:
    """One sample polyline per SAB edge, for snapping isoline tips."""
    out: list[list[tuple]] = []
    for lp in loops:
        for e in lp:
            seg = _edge_boundary_samples(e)
            if len(seg) >= 2:
                out.append(seg)
    return out


def _snap_point_to_polylines(
    p: tuple, polylines: list[list[tuple]], tol: float
) -> tuple:
    """Project p onto the nearest boundary segment, if it lies within tol."""
    if tol <= 0 or not polylines:
        return p
    pv = Vec3(p)
    best = p
    best_d = 1e300
    for seg in polylines:
        for i in range(len(seg) - 1):
            a = Vec3(seg[i])
            b = Vec3(seg[i + 1])
            ab = b - a
            L2 = ab.magnitude_square
            if L2 < 1e-24:
                q = a
            else:
                t = max(0.0, min(1.0, float((pv - a).dot(ab) / L2)))
                q = a + ab * t
            d = pv.distance(q)
            if d < best_d:
                best_d = d
                best = _v3(q)
    return best if best_d <= tol else p


def _cone_frustum_segs(
    face: dict[str, Any],
    ends: list[EdgeCircle],
    ngen: int,
    nring: int,
) -> list[tuple[tuple, tuple]]:
    """Generators and intermediate circles of a cone bounded by two full circles.

    ``r(h) = radius + slope * h``. A cylinder has slope 0.
    """
    origin = Vec3(face["origin"])
    axis = Vec3(face["axis"])
    if axis.magnitude_square < 1e-18:
        return []
    axis = axis.normalize()
    radius = float(face["radius"])
    slope = float(face.get("slope") or 0.0)
    ratio = float(face.get("ratio") or 1.0)
    major = face.get("major")
    if major is not None:
        u = Vec3(major) - axis * float(Vec3(major).dot(axis))
        if u.magnitude_square < 1e-12:
            u, v = _cyl_basis(axis)
        else:
            u = u.normalize()
            v = axis.cross(u).normalize()
    else:
        u, v = _cyl_basis(axis)

    def _xyz(th: float, h: float) -> tuple:
        r = radius + slope * h
        return _v3(origin + axis * h + u * (r * math.cos(th)) + v * (r * ratio * math.sin(th)))

    hs = [float((Vec3(e.center) - origin).dot(axis)) for e in ends]
    h0, h1 = min(hs), max(hs)
    if abs(h1 - h0) < 1e-9:
        return []
    segs: list[tuple[tuple, tuple]] = []
    ngen = max(int(ngen), 1)
    for k in range(ngen):
        th = -math.pi + 2.0 * math.pi * k / ngen
        segs.append((_xyz(th, h0), _xyz(th, h1)))
    steps = 48
    for k in range(1, max(int(nring), 1)):
        h = h0 + (h1 - h0) * k / nring
        prev = _xyz(-math.pi, h)
        for s in range(1, steps + 1):
            th = -math.pi + 2.0 * math.pi * s / steps
            cur = _xyz(th, h)
            if Vec3(prev).distance(Vec3(cur)) > 1e-9:
                segs.append((prev, cur))
            prev = cur
    return segs


def _cylinder_mesh_segs(
    face: dict[str, Any],
    ngen: int = _CYL_MESH_GEN,
    nring: int = _CYL_MESH_RING,
) -> list[tuple[tuple, tuple]]:
    """Isolines clipped to the trimmed face in (θ, h) — avoids phantom patches."""
    ends = [
        edges[0]
        for edges in (face.get("loops") or [])
        if len(edges) == 1 and isinstance(edges[0], EdgeCircle)
    ]
    if len(ends) == 2:
        return _cone_frustum_segs(face, ends, ngen, nring)
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

    bd = _boundary_polylines(loops)
    flat = [p for seg in bd for p in seg]
    snap_tol = 0.0
    if flat:
        xs = [p[0] for p in flat]
        ys = [p[1] for p in flat]
        zs = [p[2] for p in flat]
        diag = math.hypot(
            max(xs) - min(xs),
            math.hypot(max(ys) - min(ys), max(zs) - min(zs)),
        )
        snap_tol = max(1.0, 0.02 * diag)

    def _tip(p: tuple) -> tuple:
        return _snap_point_to_polylines(p, bd, snap_tol)

    def _emit_spans(
        spans: list[tuple[float, float]], *, horizontal: bool, const: float
    ) -> None:
        # horizontal=True: const is h, spans are theta — sample the CIRCULAR
        # arc (not a single chord). Generators stay straight in h.
        # Only the span tips are snapped; chord joints stay on the cylinder.
        for a, b in spans:
            if b - a < 1e-7:
                continue
            if horizontal:
                nsub = max(8, int(round(abs(b - a) / (2 * math.pi) * 48)))
                pts = [
                    _to_xyz(a + (b - a) * s / nsub, const) for s in range(nsub + 1)
                ]
                pts[0] = _tip(pts[0])
                pts[-1] = _tip(pts[-1])
                for s in range(nsub):
                    if Vec3(pts[s]).distance(Vec3(pts[s + 1])) > 1e-9:
                        segs.append((pts[s], pts[s + 1]))
            else:
                segs.append((_tip(_to_xyz(const, a)), _tip(_to_xyz(const, b))))

    def _clipped(
        outer_hits: list[float],
        hole_hits_list: list[list[float]],
    ) -> list[tuple[float, float]]:
        spans = _hits_to_spans(outer_hits)
        for hh in hole_hits_list:
            spans = _clip_intervals_subtract(spans, _hits_to_spans(hh))
        return spans

    # Generators: constant θ. Skip θ = th_min/th_max — those are the
    # boundary meridians already stroked in red. Extra samples near one
    # end stacked a second bundle of lines on top of that edge.
    th_samples = [
        th_min + (th_max - th_min) * k / max(ngen, 1) for k in range(1, max(ngen, 1))
    ]
    for th in th_samples:
        spans = _clipped(
            _poly_line_hits(best, const=th, horizontal=False),
            [
                _poly_line_hits(huv, const=th, horizontal=False)
                for huv in hole_uvs
            ],
        )
        _emit_spans(spans, horizontal=False, const=th)
    # Rings: constant h (skip exact ends — boundary wire draws those).
    # Do not add a second set from partial arcs; that redrew full rings
    # on top of this grid.
    h_samples = [
        h_min + (h_max - h_min) * k / nring for k in range(1, max(nring, 1))
    ]
    for hh in h_samples:
        spans = _clipped(
            _poly_line_hits(best, const=hh, horizontal=True),
            [
                _poly_line_hits(huv, const=hh, horizontal=True)
                for huv in hole_uvs
            ],
        )
        _emit_spans(spans, horizontal=True, const=hh)

    return segs


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


def _resample_fraction(pts: list[tuple], n: int) -> list[tuple]:
    """n points at uniform index fraction (curve order, not arc length)."""
    if n < 2 or len(pts) < 2:
        return list(pts)
    if len(pts) == n:
        return list(pts)
    out: list[tuple] = []
    last = len(pts) - 1
    for k in range(n):
        f = last * k / (n - 1)
        i = min(last - 1, int(math.floor(f)))
        u = f - i
        out.append(_v3(Vec3(pts[i]) * (1.0 - u) + Vec3(pts[i + 1]) * u))
    out[0] = pts[0]
    out[-1] = pts[-1]
    return out


def _edge_param_samples(edge: Edge, n: int) -> list[tuple]:
    """Uniform samples in the curve parameter. Splines are de Boor on the
    knot domain, not the control polygon."""
    n = max(2, int(n))
    if isinstance(edge, EdgeLine):
        a, b = Vec3(edge.a), Vec3(edge.b)
        return [
            _v3(a * (1.0 - i / (n - 1)) + b * (i / (n - 1))) for i in range(n)
        ]
    if isinstance(edge, EdgeArc):
        pts = tessellate_ellipse(
            Vec3(edge.center),
            Vec3(edge.normal),
            Vec3(edge.major),
            edge.ratio,
            edge.t0,
            edge.t1,
            closed=abs(abs(edge.t1 - edge.t0) - 2 * math.pi) < 1e-4,
        )
        return _resample_fraction(pts, n) if len(pts) >= 2 else pts
    if isinstance(edge, EdgeSpline):
        cps = [Vec3(p) for p in edge.cps]
        if len(cps) < 2:
            return [_v3(p) for p in cps]
        degree = max(1, min(int(edge.degree), len(cps) - 1))
        order = degree + 1
        knots = list(edge.knots) if edge.knots else None
        try:
            if knots is not None and len(knots) >= order + len(cps):
                bsp = BSpline(cps, order=order, knots=knots)
            else:
                bsp = BSpline(cps, order=order)
            ks = list(bsp.knots())
            u0 = float(ks[degree])
            u1 = float(ks[-(degree + 1)])
            return [
                _v3(bsp.point(u0 + (u1 - u0) * i / (n - 1))) for i in range(n)
            ]
        except Exception:
            return tessellate_bspline(cps, degree=degree, knots=knots, nseg=n)
    return _edge_samples(edge, n=n)


def _chain_param_samples(edges: list[Edge], n_per: int) -> list[tuple]:
    """Sample a loop-ordered chain in curve parameter, joining end to start."""
    pts: list[tuple] = []
    for e in edges:
        s = _edge_param_samples(e, max(2, n_per))
        if not s:
            continue
        if not pts:
            pts.extend(s)
            continue
        if Vec3(pts[-1]).distance(Vec3(s[-1])) < Vec3(pts[-1]).distance(Vec3(s[0])):
            s = list(reversed(s))
        if Vec3(pts[-1]).distance(Vec3(s[0])) < 1e-3:
            pts.extend(s[1:])
        else:
            pts.extend(s)
    return pts


def _translation_dev(
    A: list[tuple], B: list[tuple]
) -> tuple[Vec3, float]:
    """Mean of B[i]-A[i] and the largest deviation from that translation."""
    m = min(len(A), len(B))
    if m < 1:
        return Vec3(0, 0, 0), 0.0
    ds = [Vec3(B[i]) - Vec3(A[i]) for i in range(m)]
    mean = sum(ds, Vec3(0, 0, 0)) / m
    dev = max(float((d - mean).magnitude) for d in ds)
    return mean, dev


def _orient_translation(A: list[tuple], B: list[tuple]) -> list[tuple]:
    """Pick B or reversed(B) so B[i]-A[i] is as constant as possible.

    An extrusion loop walks the second rail opposite the first, so the
    stored spline runs C(1-u)+V. Pairing by which endpoint is nearer in
    space follows that reversal only when the profile chord is longer than
    the extrusion; a control-vertex curve that bends along the extrusion
    makes the wrong end nearer and the rulings cross.
    """
    if len(B) < 2 or len(A) < 2:
        return list(B)
    m = min(len(A), len(B))
    Aa, Bb = A[:m], B[:m]

    def _score(samples: list[tuple]) -> float:
        _, dev = _translation_dev(Aa, samples)
        return dev

    rev = list(reversed(Bb))
    return rev if _score(rev) < _score(Bb) else list(Bb)


def _extrusion_chains(edges: list[Edge]) -> tuple[list[Edge], list[Edge]] | None:
    """Split a loop into two rails around parallel extrusion generators.

    Generators are the lines parallel to the longest line and of similar
    length. The profile may move along that axis (a 3D control polygon);
    rails are whatever is left, not only edges that lie in a constant-height
    plane.
    """
    best_L = 0.0
    best_d: Vec3 | None = None
    info: list[tuple[Vec3, float] | None] = []
    for e in edges:
        if not isinstance(e, EdgeLine):
            info.append(None)
            continue
        d = Vec3(e.b) - Vec3(e.a)
        L = float(d.magnitude)
        if L < 1e-6:
            info.append(None)
            continue
        info.append((d / L, L))
        if L > best_L:
            best_L = L
            best_d = d / L
    if best_d is None or best_L < 1e-3:
        return None
    cos_lim = math.cos(math.radians(8.0))
    is_gen: list[bool] = []
    for item in info:
        if item is None:
            is_gen.append(False)
            continue
        direction, L = item
        is_gen.append(abs(float(direction.dot(best_d))) >= cos_lim and L >= 0.5 * best_L)
    if sum(is_gen) < 2:
        return None
    chains: list[list[Edge]] = []
    cur: list[Edge] = []
    for e, g in zip(edges, is_gen):
        if g:
            if cur:
                chains.append(cur)
                cur = []
        else:
            cur.append(e)
    if cur:
        chains.append(cur)
    if chains and not is_gen[0] and not is_gen[-1] and len(chains) >= 2:
        chains[0] = chains[-1] + chains[0]
        chains.pop()
    chains = [c for c in chains if c]
    if len(chains) != 2:
        return None
    return chains[0], chains[1]


def _sample_orient_rails(
    chain_a: list[Edge],
    chain_b: list[Edge],
    n_rail: int,
) -> tuple[list[tuple], list[tuple], Vec3, float] | None:
    """Parameter-sample both rails, orient by translation, then arc-length resample.

    Arc-length spacing keeps a fit-point spline's grid even. It preserves
    correspondence only after the translation test has oriented the rails;
    doing it on a reversed control-vertex rail is what crossed the rulings.
    """
    n_rail = max(8, int(n_rail))

    def _one(chain: list[Edge]) -> list[tuple]:
        n_per = max(8, n_rail // max(1, len(chain)))
        pts = _chain_param_samples(chain, n_per)
        return _resample_fraction(pts, n_rail)

    A = _one(chain_a)
    B = _one(chain_b)
    if len(A) < 2 or len(B) < 2:
        return None
    B = _orient_translation(A, B)
    mean, _dev = _translation_dev(A, B)
    if mean.magnitude_square < 1e-18:
        return None
    A = _resample_polyline(A, n_rail)
    B = _resample_polyline(B, n_rail)
    mean, dev = _translation_dev(A, B)
    if mean.magnitude_square < 1e-18:
        return None
    return A, B, mean.normalize(), dev


def _extract_extrusion_rails(
    edges: list[Edge],
    n_rail: int = 48,
) -> tuple[list[tuple], list[tuple], Vec3] | None:
    """Rails of an extrusion: the second curve is the first translated.

    Returns (rail_a, rail_b, axis) with A[i] corresponding to B[i], or None
    when the two chains are not the same profile shifted along the generators.
    """
    chains = _extrusion_chains(edges)
    if chains is None:
        return None
    packed = _sample_orient_rails(chains[0], chains[1], n_rail)
    if packed is None:
        return None
    A, B, axis, dev = packed
    length = float(_translation_dev(A, B)[0].magnitude)
    if dev > max(1.0, 0.02 * length):
        return None
    return A, B, axis


def _ruled_rail_pair(
    edges: list[Edge], n_rail: int
) -> tuple[list[tuple], list[tuple], Vec3] | None:
    """Extrusion rails, or a 4-cycle ruled pair oriented the same way."""
    rails = _extract_extrusion_rails(edges, n_rail=n_rail)
    if rails is not None:
        return rails
    if not _is_ruled_loop(edges):
        return None
    eds = list(edges)
    if isinstance(eds[0], EdgeLine):
        eds = eds[1:] + eds[:1]
    packed = _sample_orient_rails([eds[0]], [eds[2]], n_rail)
    if packed is None:
        return None
    A, B, axis, _dev = packed
    return A, B, axis


def _extrusion_param_grid(
    A: list[tuple],
    B: list[tuple],
    n_gen: int,
    n_lat: int,
) -> list[tuple[tuple, tuple]]:
    """Rulings A(s)→B(s) and latitudes at constant extrusion fraction.

    s is arc length along the oriented profile, so each ruling is the
    extrusion of one curve point, not a control-polygon chord.
    """
    n = min(len(A), len(B))
    if n < 2:
        return []
    A, B = A[:n], B[:n]

    def _at(s: float, t: float) -> tuple:
        f = max(0.0, min(1.0, s)) * (n - 1)
        i = max(0, min(n - 2, int(math.floor(f))))
        u = f - i
        pa = Vec3(A[i]) * (1.0 - u) + Vec3(A[i + 1]) * u
        pb = Vec3(B[i]) * (1.0 - u) + Vec3(B[i + 1]) * u
        return _v3(pa * (1.0 - t) + pb * t)

    segs: list[tuple[tuple, tuple]] = []
    for k in range(1, max(n_gen, 1)):
        s = k / n_gen
        segs.append((_at(s, 0.0), _at(s, 1.0)))
    for k in range(1, max(n_lat, 1)):
        t = k / n_lat
        prev = _at(0.0, t)
        for j in range(1, n):
            cur = _at(j / (n - 1), t)
            if Vec3(prev).distance(Vec3(cur)) > 1e-9:
                segs.append((prev, cur))
            prev = cur
    return segs


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
    """Dense samples of a SAB boundary edge for exact trim clipping."""
    if isinstance(edge, EdgeLine):
        return [edge.a, edge.b]
    if isinstance(edge, (EdgeArc, EdgeCircle)):
        return _edge_samples(edge, n=96)
    if isinstance(edge, EdgeSpline):
        return _edge_samples(edge, n=max(128, len(edge.cps) * 16))
    return _edge_samples(edge, n=64)


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


def _rail_at(A: list[tuple], s: float) -> Vec3:
    """Point at fraction ``s`` along a sampled rail."""
    n = len(A)
    f = max(0.0, min(1.0, s)) * (n - 1)
    i = max(0, min(n - 2, int(math.floor(f))))
    u = f - i
    return Vec3(A[i]) * (1.0 - u) + Vec3(A[i + 1]) * u


def _ruled_param_st(
    edges: list[Edge],
    A: list[tuple],
    B: list[tuple],
    axis: Vec3,
) -> list[tuple[float, float]]:
    """Trim loop in (s, t). ``t`` is the fraction along the ruling, not height.

    A profile that itself moves along the extrusion has a different height at
    every s, so clipping at constant height draws the latitude past the cut.
    """
    if len(A) < 2 or len(B) < 2 or not edges:
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
        s = _rail_s_of_point(pv, A, axis)
        pa = _rail_at(A, s)
        pb = _rail_at(B, s)
        denom = float((pb - pa).dot(axis))
        if abs(denom) < 1e-12:
            t = 0.0
        else:
            t = float((pv - pa).dot(axis) / denom)
        out.append((s, t))
    if out and (
        abs(out[0][0] - out[-1][0]) > 1e-9 or abs(out[0][1] - out[-1][1]) > 1e-9
    ):
        out.append(out[0])
    return out


def _on_poly_boundary(
    x: float, y: float, poly: list[tuple[float, float]], eps: float = 1e-9
) -> bool:
    """True if (x,y) lies on an edge of the polygon (inclusive trim)."""
    n = len(poly)
    if n < 2:
        return False
    closed = (
        abs(poly[0][0] - poly[-1][0]) < 1e-12
        and abs(poly[0][1] - poly[-1][1]) < 1e-12
    )
    n_seg = n - 1 if closed else n
    for i in range(n_seg):
        x0, y0 = poly[i]
        x1, y1 = poly[i + 1] if closed else poly[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        if L2 < 1e-24:
            if abs(x - x0) <= eps and abs(y - y0) <= eps:
                return True
            continue
        t = ((x - x0) * dx + (y - y0) * dy) / L2
        if t < -1e-12 or t > 1.0 + 1e-12:
            continue
        t = max(0.0, min(1.0, t))
        px, py = x0 + t * dx, y0 + t * dy
        if abs(x - px) <= eps and abs(y - py) <= eps:
            return True
    return False


def _pip2(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    """Even-odd point-in-polygon; boundary counts as inside (CAE trim)."""
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
    # Inclusive: points on the SAB trim curve are part of the face
    if _on_poly_boundary(x, y, poly, eps=1e-7):
        return True
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


def _rails_from_extrude(
    extrude: dict[str, Any], n_rail: int
) -> tuple[list[tuple], list[tuple], Vec3] | None:
    """Profile samples and the same curve shifted by the extrusion vector."""
    cps = extrude.get("cps") or ()
    if len(cps) < 2:
        return None
    V = Vec3(extrude.get("vector") or (0, 0, 0))
    if V.magnitude_square < 1e-18:
        return None
    knots = extrude.get("knots")
    edge = EdgeSpline(
        int(extrude.get("degree") or 1),
        tuple(tuple(p) for p in cps),
        tuple(knots) if knots else None,
    )
    A = _edge_param_samples(edge, max(8, int(n_rail)))
    if len(A) < 2:
        return None
    A = _resample_polyline(A, max(8, int(n_rail)))
    B = [_v3(Vec3(p) + V) for p in A]
    return A, B, V.normalize()


def _ruled_mesh_segs(
    loops: list[list[Edge]],
    n_gen: int = 12,
    n_lat: int = 5,
    n_rail: int = 48,
    extrude: dict[str, Any] | None = None,
) -> list[tuple[tuple, tuple]]:
    """Ruled isolines: extrusion rulings at matching curve parameter, else trim clip."""
    if not loops:
        return []
    edges = loops[0]
    paired = _ruled_rail_pair(edges, n_rail)
    # Boundary rails miss a trimmed extrusion: the outline is the intersection
    # curve, while the surface record still has the profile and its translation.
    from_surface = False
    if paired is None and extrude is not None:
        paired = _rails_from_extrude(extrude, n_rail)
        from_surface = paired is not None
    if paired is None:
        return []
    A, B, axis = paired
    n = min(len(A), len(B))
    if n < 2:
        return []
    A, B = A[:n], B[:n]
    mean, dev = _translation_dev(A, B)
    # Pure extrusion (fit spline or control-vertex spline): rulings are
    # C(s) → C(s)+V. A height clip assumes each rail sits at one height, which
    # is true for a planar fit profile and false when the control polygon
    # moves along the extrusion.
    if (
        not from_surface
        and not loops[1:]
        and mean.magnitude > 1e-6
        and dev <= max(1.0, 0.02 * float(mean.magnitude))
    ):
        return _extrusion_param_grid(A, B, n_gen, n_lat)

    outer_uv = _ruled_param_st(edges, A, B, axis)
    hole_uvs = [_ruled_param_st(h, A, B, axis) for h in loops[1:]]
    hole_uvs = [h for h in hole_uvs if len(h) >= 3]

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
    bd = _boundary_polylines(loops)
    flat = [p for seg in bd for p in seg]
    snap_tol = 0.0
    if flat:
        xs = [p[0] for p in flat]
        ys = [p[1] for p in flat]
        zs = [p[2] for p in flat]
        diag = math.hypot(
            max(xs) - min(xs),
            math.hypot(max(ys) - min(ys), max(zs) - min(zs)),
        )
        # Seat a tip that is already on the trim. A wide snap pulls the
        # cut end onto a neighbouring loop of a self-intersecting hole.
        snap_tol = max(1e-3, 0.001 * diag)

    def _tip(p: tuple) -> tuple:
        return _snap_point_to_polylines(p, bd, snap_tol)

    # Clip in (s, t): s along the profile, t along the extrusion.
    use_clip = len(outer_uv) >= 3
    if use_clip:
        # Exact trim hits. Do not PIP-chop afterwards: endpoints that lie on
        # the polygon were classed as outside and the generator lost its tip.
        for k in range(1, n_gen):
            s = k / n_gen
            spans = _hits_to_spans(
                _poly_line_hits(outer_uv, const=s, horizontal=False)
            )
            for huv in hole_uvs:
                spans = _clip_intervals_subtract(
                    spans,
                    _hits_to_spans(
                        _poly_line_hits(huv, const=s, horizontal=False)
                    ),
                )
            for t0, t1 in spans:
                t0 = max(0.0, min(1.0, t0))
                t1 = max(0.0, min(1.0, t1))
                if abs(t1 - t0) < 1e-7:
                    continue
                segs.append((_tip(_at(s, t0)), _tip(_at(s, t1))))
        # Latitudes: constant extrusion fraction (the profile, translated).
        for k in range(1, n_lat):
            t = k / n_lat
            spans = _hits_to_spans(
                _poly_line_hits(outer_uv, const=t, horizontal=True)
            )
            for huv in hole_uvs:
                spans = _clip_intervals_subtract(
                    spans,
                    _hits_to_spans(
                        _poly_line_hits(huv, const=t, horizontal=True)
                    ),
                )
            for s0, s1 in spans:
                if s1 < s0:
                    s0, s1 = s1, s0
                if s1 - s0 < 1e-7:
                    continue
                n_sub = max(8, int(round((s1 - s0) * (n - 1))) + 1)
                pts = [
                    _at(s0 + (s1 - s0) * j / n_sub, t) for j in range(n_sub + 1)
                ]
                pts[0] = _tip(pts[0])
                pts[-1] = _tip(pts[-1])
                for j in range(n_sub):
                    if Vec3(pts[j]).distance(Vec3(pts[j + 1])) > 1e-9:
                        segs.append((pts[j], pts[j + 1]))
        return segs

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


def _emit_ruled_mesh(
    loops: list[list[Edge]], extrude: dict[str, Any] | None = None
) -> list[str]:
    if not loops:
        return []
    L: list[str] = []
    for a, b in _ruled_mesh_segs(loops, extrude=extrude):
        L.append(f"  \\stpDmeshSeg{{{_fmt_xyz(a)}}}{{{_fmt_xyz(b)}}}")
    return L


# Spline whose control points do not lie in one plane (the curve leaves every plane).
_NONPLANAR = object()


def _bbox_diag(pts: list[Vec3]) -> float:
    if len(pts) < 2:
        return 1.0
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)


def _dist_plane(p: Vec3, origin: Vec3, normal: Vec3) -> float:
    return abs((p - origin).dot(normal))


def _plane_from_points(pts: list[Vec3], tol: float):
    """Plane through three non-collinear points. None when the set is straight."""
    if len(pts) < 3:
        return None
    origin = pts[0]
    for i in range(len(pts)):
        d1 = pts[i] - origin
        if d1.magnitude <= tol:
            continue
        for j in range(i + 1, len(pts)):
            d2 = pts[j] - origin
            cross = d1.cross(d2)
            scale = max(d1.magnitude, d2.magnitude, 1.0)
            if cross.magnitude > tol * scale:
                return origin, cross.normalize()
    return None


def _edge_scale_points(edge: Edge) -> list[Vec3]:
    if isinstance(edge, EdgeLine):
        return [Vec3(edge.a), Vec3(edge.b)]
    if isinstance(edge, EdgeCircle):
        return [Vec3(edge.center)]
    if isinstance(edge, EdgeArc):
        return [Vec3(edge.center), Vec3(edge.center) + Vec3(edge.major)]
    if isinstance(edge, EdgeSpline):
        return [Vec3(p) for p in edge.cps]
    return []


def _curve_plane(edge: Edge, tol: float):
    """Plane the curve itself spans, or None if it is straight.

    ``_NONPLANAR`` means the curve (spline control polygon) is not planar,
    so no common face plane can contain it.
    """
    if isinstance(edge, EdgeCircle):
        nrm = Vec3(edge.normal)
        if abs(float(edge.radius)) <= tol or nrm.magnitude_square < 1e-30:
            return None
        return Vec3(edge.center), nrm.normalize()
    if isinstance(edge, EdgeArc):
        major = Vec3(edge.major)
        nrm = Vec3(edge.normal)
        if major.magnitude <= tol or nrm.magnitude_square < 1e-30:
            return None
        # P(t) = C + cos(t)*major + sin(t)*ratio*(n̂ × major)
        minor = nrm.normalize().cross(major) * float(edge.ratio)
        if minor.magnitude <= tol:
            return None
        nn = major.cross(minor)
        if nn.magnitude <= tol * max(major.magnitude, minor.magnitude, 1.0):
            return None
        return Vec3(edge.center), nn.normalize()
    if isinstance(edge, EdgeSpline):
        cps = [Vec3(p) for p in edge.cps]
        plane = _plane_from_points(cps, tol)
        if plane is None:
            return None
        origin, normal = plane
        if any(_dist_plane(p, origin, normal) > tol for p in cps):
            return _NONPLANAR
        return plane
    return None


def _curve_lies_in_plane(edge: Edge, origin: Vec3, normal: Vec3, tol: float) -> bool:
    """Whole curve in the plane — not a sample of points on the curve.

    A line is the segment between its ends. An arc/circle lies in the plane
    only when its own axes do. A spline lies in the plane only when every
    control point does (the curve is an affine combination of them).
    """
    if isinstance(edge, EdgeLine):
        return (
            _dist_plane(Vec3(edge.a), origin, normal) <= tol
            and _dist_plane(Vec3(edge.b), origin, normal) <= tol
        )
    if isinstance(edge, EdgeCircle):
        nrm = Vec3(edge.normal)
        if nrm.magnitude_square < 1e-30:
            return _dist_plane(Vec3(edge.center), origin, normal) <= tol
        # Rim leaves the plane by r*|n̂ × N| when the circle plane is tilted.
        lift = abs(float(edge.radius)) * nrm.normalize().cross(normal).magnitude
        return _dist_plane(Vec3(edge.center), origin, normal) <= tol and lift <= tol
    if isinstance(edge, EdgeArc):
        major = Vec3(edge.major)
        nrm = Vec3(edge.normal)
        if nrm.magnitude_square < 1e-30 or major.magnitude_square < 1e-30:
            return _dist_plane(Vec3(edge.center), origin, normal) <= tol
        minor = nrm.normalize().cross(major) * float(edge.ratio)
        return (
            _dist_plane(Vec3(edge.center), origin, normal) <= tol
            and abs(major.dot(normal)) <= tol
            and abs(minor.dot(normal)) <= tol
        )
    if isinstance(edge, EdgeSpline):
        return all(
            _dist_plane(Vec3(p), origin, normal) <= tol for p in edge.cps
        )
    return False


def loops_are_coplanar(loops: list[list[Edge]]) -> bool:
    """True when every boundary curve lies in one common plane.

    The plane is taken from a circle/arc's own plane or from a spline's
    control points. Sample points on a curve are never used: coplanar
    samples do not imply a coplanar curve.
    """
    edges: list[Edge] = [e for lp in (loops or []) for e in lp]
    if not edges:
        return False
    scale_pts: list[Vec3] = []
    for e in edges:
        scale_pts.extend(_edge_scale_points(e))
    tol = max(1e-4, 1e-6 * _bbox_diag(scale_pts))
    candidates: list[tuple[Vec3, Vec3]] = []
    for e in edges:
        owned = _curve_plane(e, tol)
        if owned is _NONPLANAR:
            return False
        if owned is not None:
            candidates.append(owned)
    if not candidates:
        anchors: list[Vec3] = []
        for e in edges:
            if isinstance(e, EdgeLine):
                anchors.append(Vec3(e.a))
                anchors.append(Vec3(e.b))
            elif isinstance(e, EdgeSpline):
                anchors.extend(Vec3(p) for p in e.cps)
        plane = _plane_from_points(anchors, tol)
        if plane is None:
            return False
        candidates.append(plane)
    for origin, normal in candidates:
        if all(_curve_lies_in_plane(e, origin, normal, tol) for e in edges):
            return True
    return False


def format_stp_analytic_face(face: dict[str, Any]) -> list[str]:
    """REGION, or any face whose boundary curves are coplanar → even-odd fill.

    REGION is already a planar face and is not retested. Other kinds use the
    region fill when ``loops_are_coplanar`` holds; curved shells keep the
    mesh, red wire, and FE edge equations.
    """
    loops = face.get("loops") or []
    kind = face.get("kind")
    L: list[str] = []
    # Planar REGION / closed curves: even-odd fill (holes), compact TeX.
    # Coplanar SURFACE boundaries take the same path (curve test, not samples).
    if kind == "region" or loops_are_coplanar(loops):
        L.extend(format_stp_dface_curves(loops))
        return L
    if kind == "cylinder":
        L.extend(_emit_cylinder_mesh(face))
        # Full 360°: each end circle own loop (avoid -- chords between circles)
        full = abs(float(face.get("th1", 0)) - float(face.get("th0", 0))) > 2 * math.pi - 0.15
        if full:
            L.extend(
                _emit_revolve_wire(
                    {
                        "loops": loops,
                        "axis": face.get("axis") or (0, 0, 1),
                        "full_turn": True,
                    }
                )
            )
        else:
            L.extend(_emit_loop_wire(loops))
        L.extend(_emit_loop_eq(loops))
        return L
    if kind == "revolve":
        L.extend(_emit_revolve_mesh(face))
        L.extend(_emit_revolve_wire(face))
        L.extend(_emit_loop_eq(loops))
        return L
    if kind == "ruled":
        L.extend(_emit_ruled_mesh(loops, face.get("extrude")))
        L.extend(_emit_loop_wire(loops))
        L.extend(_emit_loop_eq(loops))
        return L
    if kind == "spline":
        L.extend(
            f"  \\stpDmeshSeg{{{_fmt_xyz(a)}}}{{{_fmt_xyz(b)}}}"
            for a, b in _spline_mesh_segs(loops, face.get("spline") or {})
        )
        L.extend(_emit_loop_wire(loops))
        L.extend(_emit_loop_eq(loops))
        return L
    if kind == "plane":
        # Boundary curves were not coplanar — keep the UV isoline mesh.
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


def _edge_full_turn(edge: Edge) -> bool:
    """Closed circle or a 360° arc. Chained into a path, its sample origin
    is not the vertex the previous edge arrived at, so ``--`` draws a chord."""
    if isinstance(edge, EdgeCircle):
        return True
    if isinstance(edge, EdgeArc):
        return abs(float(edge.t1) - float(edge.t0)) >= 2 * math.pi - 0.15
    return False


def _wire_loops(edges: list[Edge]) -> list[list[Edge]]:
    """Draw each full turn on its own loop. The remaining edges stay in order."""
    if len(edges) < 2 or not any(_edge_full_turn(e) for e in edges):
        return [edges]
    chain: list[Edge] = []
    parts: list[list[Edge]] = []
    for e in edges:
        if _edge_full_turn(e):
            parts.append([e])
        else:
            chain.append(e)
    if chain:
        parts.append(chain)
    return parts


def _emit_loop_wire(
    loops: list[list[Edge]], *, skip_seam_lines: bool = False
) -> list[str]:
    """Stroke face boundary once (no fill).

    ``skip_seam_lines``: for full 360° cylinder, drop EdgeLine seams
    (often duplicated forward/back); keep circles / arcs.
    """
    if not loops:
        return []
    L = ["  \\begin{stpDwireEnv}"]
    for edges in loops:
        for part in _wire_loops(edges):
            L.append("    \\begin{stpDfaceLoop}")
            for e in part:
                if skip_seam_lines and isinstance(e, EdgeLine):
                    continue
                L.append(_emit_edge_tex(e))
            L.append("    \\end{stpDfaceLoop}")
    L.append("  \\end{stpDwireEnv}")
    return L


def _edge_is_revolve_latitude(edge: Edge, axis: Vec3) -> bool:
    """True if circular edge lies in a plane ⊥ revolve axis (a parallel)."""
    info = _circular_lat_info(edge)
    if info is None:
        return False
    _c, n, _r = info
    return abs(float(n.dot(axis))) > 0.92


def _emit_revolve_wire(face: dict[str, Any]) -> list[str]:
    """Stroke revolve boundary without false chords across full circles.

    Full 360°: each outer latitude Circle is its own loop (chaining two
    ``EdgeCircle`` in one path draws ``--`` chords between them). Seam
    meridians omitted; bridge-hole circles still stroked.
    Partial: outer trim loop (gens + arcs, bridges peeled) + hole loops.
    """
    loops = face.get("loops") or []
    if not loops:
        return []
    axis = Vec3(face.get("axis") or (0, 0, 1))
    if axis.magnitude_square > 1e-18:
        axis = axis.normalize()
    full = bool(face.get("full_turn"))
    origin = Vec3(face["origin"]) if face.get("origin") else None
    trim = _revolve_trim_loops(loops, origin=origin, axis=axis)
    L = ["  \\begin{stpDwireEnv}"]
    if full:
        seen: set[tuple] = set()
        # Outer latitudes only (skip seam generators); then hole circles
        for li, edges in enumerate(trim):
            for e in edges:
                if li == 0 and isinstance(e, EdgeLine):
                    continue
                if li == 0 and not _edge_is_revolve_latitude(e, axis):
                    continue  # meridian seam
                if isinstance(e, EdgeCircle):
                    key = (
                        "C",
                        round(e.center[0], 3),
                        round(e.center[1], 3),
                        round(e.center[2], 3),
                        round(e.radius, 3),
                    )
                elif isinstance(e, EdgeArc):
                    key = (
                        "A",
                        round(e.center[0], 3),
                        round(e.center[1], 3),
                        round(e.center[2], 3),
                        round(e.t0, 5),
                        round(e.t1, 5),
                    )
                else:
                    key = ("E", id(e))
                if key in seen:
                    continue
                seen.add(key)
                L.append("    \\begin{stpDfaceLoop}")
                L.append(_emit_edge_tex(e))
                L.append("    \\end{stpDfaceLoop}")
    else:
        for edges in trim:
            if not edges:
                continue
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


def _newell_area(pts: list[tuple]) -> float:
    """Unsigned Newell polygon area in 3D (mm²)."""
    n = len(pts)
    if n < 3:
        return 0.0
    nx = ny = nz = 0.0
    for i in range(n):
        x1, y1, z1 = float(pts[i][0]), float(pts[i][1]), float(pts[i][2])
        x2, y2, z2 = (
            float(pts[(i + 1) % n][0]),
            float(pts[(i + 1) % n][1]),
            float(pts[(i + 1) % n][2]),
        )
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)


def _shoelace2(poly: list[tuple[float, float]]) -> float:
    """Unsigned 2D shoelace area."""
    n = len(poly)
    if n < 3:
        return 0.0
    if (
        abs(poly[0][0] - poly[-1][0]) < 1e-12
        and abs(poly[0][1] - poly[-1][1]) < 1e-12
    ):
        n -= 1
    if n < 3:
        return 0.0
    a = 0.0
    j = n - 1
    for i in range(n):
        a += poly[j][0] * poly[i][1] - poly[i][0] * poly[j][1]
        j = i
    return abs(a) * 0.5


def _tri_area3(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float:
    ab = Vec3(b) - Vec3(a)
    ac = Vec3(c) - Vec3(a)
    return 0.5 * ab.cross(ac).magnitude


def _planar_loops_area(loops: list[list[Edge]], n: int = 64) -> float:
    """Outer − holes via Newell (planar / near-planar faces)."""
    polys = curve_loops_as_polylines(loops, n=n)
    if not polys or len(polys[0]) < 3:
        return 0.0
    area = _newell_area(polys[0])
    for hole in polys[1:]:
        if len(hole) >= 3:
            area -= _newell_area(hole)
    return max(0.0, area)


def _cylinder_loops_th_h(
    face: dict[str, Any],
) -> tuple[list[tuple[float, float]], list[list[tuple[float, float]]]] | None:
    """Outer + hole polygons in (θ, h) for a cylinder face."""
    origin = Vec3(face["origin"])
    axis = Vec3(face["axis"])
    if axis.magnitude_square < 1e-18:
        return None
    axis = axis.normalize()
    u, v = _cyl_basis(axis)
    loops = face.get("loops") or []
    if not loops:
        return None

    def _one(edges: list[Edge]) -> list[tuple[float, float]]:
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
        return list(zip(ths, [h for _, h in raw]))

    uvs = [_one(edges) for edges in loops]
    uvs = [uv for uv in uvs if len(uv) >= 3]
    if not uvs:
        return None
    uvs.sort(key=len, reverse=True)
    return uvs[0], uvs[1:]


def _cylinder_surface_area(face: dict[str, Any]) -> float:
    """Mantle area = r · Area(θ,h), outer minus holes."""
    r = float(face.get("radius") or 0.0)
    if r <= 1e-12:
        return 0.0
    packed = _cylinder_loops_th_h(face)
    if packed is None:
        # Fallback: full rectangular sector from mesh params
        th0 = float(face.get("th0", -math.pi))
        th1 = float(face.get("th1", math.pi))
        h0 = float(face.get("h0", 0.0))
        h1 = float(face.get("h1", 0.0))
        return r * abs(th1 - th0) * abs(h1 - h0)
    outer, holes = packed
    area_th = _shoelace2(outer)
    for h in holes:
        area_th -= _shoelace2(h)
    return max(0.0, r * area_th)


def _ruled_surface_area(
    loops: list[list[Edge]], n_s: int = 48, n_h: int = 24
) -> float:
    """Ruled / extrusion strip area via (s,t) grid, clipped to SAB trim + holes."""
    if not loops:
        return 0.0
    edges = loops[0]
    paired = _ruled_rail_pair(edges, max(32, n_s))
    if paired is None:
        return _planar_loops_area(loops)
    A, B, axis = paired

    n = min(len(A), len(B))
    if n < 2:
        return _planar_loops_area(loops)
    A, B = A[:n], B[:n]
    mean, dev = _translation_dev(A, B)
    if (
        not loops[1:]
        and mean.magnitude > 1e-6
        and dev <= max(1.0, 0.02 * float(mean.magnitude))
    ):
        area = 0.0
        for i in range(n - 1):
            area += _tri_area3(A[i], A[i + 1], B[i + 1])
            area += _tri_area3(A[i], B[i + 1], B[i])
        return max(0.0, area)
    hA = float(Vec3(A[0]).dot(axis))
    hB = float(Vec3(B[0]).dot(axis))
    outer_uv = _ruled_param_poly(edges, A, axis)
    hole_uvs = [
        huv
        for hole in loops[1:]
        if len(huv := _ruled_param_poly(hole, A, axis)) >= 3
    ]
    use_clip = len(outer_uv) >= 3

    def _at(s: float, t: float) -> tuple:
        s = max(0.0, min(1.0, s))
        t = max(0.0, min(1.0, t))
        i = min(n - 2, int(s * (n - 1)))
        u = s * (n - 1) - i
        pa = Vec3(A[i]) * (1.0 - u) + Vec3(A[i + 1]) * u
        pb = Vec3(B[i]) * (1.0 - u) + Vec3(B[i + 1]) * u
        return _v3(pa * (1.0 - t) + pb * t)

    area = 0.0
    for i in range(n_s):
        s0, s1 = i / n_s, (i + 1) / n_s
        for j in range(n_h):
            t0, t1 = j / n_h, (j + 1) / n_h
            sc, tc = 0.5 * (s0 + s1), 0.5 * (t0 + t1)
            if use_clip:
                hc = hA + (hB - hA) * tc
                if not _sh_inside(sc, hc, outer_uv, hole_uvs):
                    continue
            p00, p10 = _at(s0, t0), _at(s1, t0)
            p01, p11 = _at(s0, t1), _at(s1, t1)
            area += _tri_area3(p00, p10, p11) + _tri_area3(p00, p11, p01)
    return max(0.0, area)


def _revolve_surface_area(face: dict[str, Any]) -> float:
    """Revolve mantle ≈ ∫ 2π_frac · ρ ds along profile (mm²)."""
    profile = face.get("profile") or []
    if len(profile) < 2:
        return _planar_loops_area(face.get("loops") or [])
    th0, th1 = float(face.get("th0", -math.pi)), float(face.get("th1", math.pi))
    frac = abs(th1 - th0)
    if frac < 1e-9:
        return 0.0
    area = 0.0
    for i in range(len(profile) - 1):
        h0, r0 = profile[i]
        h1, r1 = profile[i + 1]
        ds = math.hypot(h1 - h0, r1 - r0)
        rho = 0.5 * (abs(r0) + abs(r1))
        area += rho * ds * frac
    return max(0.0, area)


def analytic_face_area_mm2(face: dict[str, Any]) -> float:
    """Shell mid-surface area (mm²) for mass: plane / cylinder / ruled / fallback."""
    loops = face.get("loops") or []
    kind = face.get("kind")
    if kind == "cylinder":
        return _cylinder_surface_area(face)
    if kind == "revolve":
        return _revolve_surface_area(face)
    if kind == "ruled":
        return _ruled_surface_area(loops)
    if kind in ("plane", "region"):
        return _planar_loops_area(loops)
    # wire / unknown: boundary Newell (OK near-planar; underestimates freeform)
    return _planar_loops_area(loops)
