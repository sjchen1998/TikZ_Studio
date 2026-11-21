# -*- coding: utf-8 -*-
"""Extract and tessellate shell-face loops from DXF (REGION / curves / poly).

Supports:
  - REGION (ACIS): outer + hole loops; straight / ellipse(circle) / NUBS edges
  - CIRCLE, ARC, ELLIPSE, closed SPLINE, closed LWPOLYLINE (incl. bulge arcs)
  - MESH / 3DFACE / HATCH (boundary paths)

Loops are returned as tessellated 3D polylines (list of (x,y,z)), outer first
(largest |area|), then holes.  Suitable for \\stpDface{outer;hole;…}.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

from ezdxf.math import BSpline, Vec3

_KEY_TOL = 1e-6
_CIRCLE_SEGS = 72
_ARC_MIN_SEGS = 12
_SPLINE_SEGS = 96


def _k(p, tol=_KEY_TOL) -> tuple[float, float, float]:
    x, y, z = float(p[0]), float(p[1]), float(p[2] if len(p) > 2 else 0.0)
    return (round(x / tol) * tol, round(y / tol) * tol, round(z / tol) * tol)


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


def _shoelace_area_xy(pts: list[tuple]) -> float:
    if len(pts) < 3:
        return 0.0
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        a += x1 * y2 - x2 * y1
    return 0.5 * a


def order_outer_then_holes(loops: list[list[tuple]]) -> list[list[tuple]]:
    """Largest |area| loop first (outer); remaining are holes."""
    scored = []
    for lp in loops:
        ring = _uniq_ring(lp)
        if len(ring) < 3:
            continue
        scored.append((abs(_shoelace_area_xy(ring)), ring))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [r for _, r in scored]


def _rot90_around_normal(v: Vec3, n: Vec3) -> Vec3:
    return n.normalize().cross(v)


def tessellate_ellipse(
    center: Vec3,
    normal: Vec3,
    major: Vec3,
    ratio: float,
    t0: float,
    t1: float,
    *,
    closed: bool = False,
) -> list[tuple]:
    """Sample ACIS ellipse-curve: C + cos(t)*major + sin(t)*ratio*(n×major_unit* |major|)."""
    if major.magnitude_square < 1e-30:
        return []
    n = normal if normal.magnitude_square > 1e-30 else Vec3(0, 0, 1)
    minor = _rot90_around_normal(major, n) * float(ratio)
    # Normalize sweep into (t0, t1] direction
    if closed or abs((t1 - t0) - 2 * math.pi) < 1e-6 or abs(t1 - t0) < 1e-9:
        t0, t1 = -math.pi, math.pi
        closed = True
    sweep = t1 - t0
    # If nearly full turn
    if abs(abs(sweep) - 2 * math.pi) < 1e-4 or (
        closed and abs(sweep) < 1e-9
    ):
        t0, t1 = -math.pi, math.pi
        sweep = 2 * math.pi
        closed = True
    # Guard absurd parameter ranges (mis-identified curves)
    if abs(sweep) > 2 * math.pi + 0.5:
        sweep = math.copysign(2 * math.pi, sweep) if sweep else 2 * math.pi
        t1 = t0 + sweep
        closed = True
    nseg = max(_ARC_MIN_SEGS, int(round(_CIRCLE_SEGS * abs(sweep) / (2 * math.pi))))
    nseg = min(nseg, _CIRCLE_SEGS)
    if closed:
        nseg = max(nseg, _CIRCLE_SEGS)
    pts = []
    for i in range(nseg + (0 if closed else 1)):
        t = t0 + sweep * (i / nseg)
        p = center + major * math.cos(t) + minor * math.sin(t)
        pts.append(_k(p))
    return _uniq_ring(pts) if closed else pts


def tessellate_bspline(
    control_points: list[Vec3],
    *,
    degree: int,
    knots: list[float] | None = None,
    nseg: int = _SPLINE_SEGS,
) -> list[tuple]:
    if len(control_points) < 2:
        return [_k(p) for p in control_points]
    order = max(2, min(int(degree) + 1, len(control_points)))
    try:
        if knots is not None and len(knots) >= order + len(control_points):
            bsp = BSpline(control_points, order=order, knots=knots)
        else:
            bsp = BSpline(control_points, order=order)
        return [_k(p) for p in bsp.approximate(nseg)]
    except Exception:
        return [_k(p) for p in control_points]


# ---------------------------------------------------------------------------
# SAB text dump parser (ellipse / NUBS survive as records; high-level = unsupported)
# ---------------------------------------------------------------------------

_REC_HDR = re.compile(r"^-+ record:\s*(\d+)\s*$")


def _parse_sab_records(sab: bytes) -> dict[int, dict[str, Any]]:
    from ezdxf.acis import api as acis

    lines = list(acis.dump_sab_as_text(sab))
    records: dict[int, dict[str, Any]] = {}
    cur_id: int | None = None
    cur: dict[str, Any] | None = None
    for line in lines:
        m = _REC_HDR.match(line.strip())
        if m:
            if cur_id is not None and cur is not None:
                records[cur_id] = cur
            cur_id = int(m.group(1))
            cur = {"id": cur_id, "type": None, "fields": []}
            continue
        if cur is None:
            continue
        s = line.strip()
        if s.startswith("ENTITY_TYPE ="):
            et = s.split("=", 1)[1].strip()
            if cur["type"] is None:
                cur["type"] = et
            cur["fields"].append(("ENTITY_TYPE", et))
        elif s.startswith("LOCATION_VEC ="):
            cur["fields"].append(("LOCATION_VEC", _parse_vec(s.split("=", 1)[1])))
        elif s.startswith("DIRECTION_VEC ="):
            cur["fields"].append(("DIRECTION_VEC", _parse_vec(s.split("=", 1)[1])))
        elif s.startswith("DOUBLE ="):
            cur["fields"].append(("DOUBLE", float(s.split("=", 1)[1].strip())))
        elif s.startswith("INT ="):
            cur["fields"].append(("INT", int(float(s.split("=", 1)[1].strip()))))
        elif s.startswith("POINTER ="):
            val = s.split("=", 1)[1].strip()
            cur["fields"].append(("POINTER", None if val == "-1" else int(val)))
        elif s.startswith("BOOL_TRUE"):
            cur["fields"].append(("BOOL", True))
        elif s.startswith("BOOL_FALSE"):
            cur["fields"].append(("BOOL", False))
        elif s.startswith("ENUM ="):
            cur["fields"].append(("ENUM", int(float(s.split("=", 1)[1].strip()))))
        elif s.startswith("STR ="):
            cur["fields"].append(("STR", s.split("=", 1)[1].strip()))
        else:
            cur["fields"].append(("RAW", s))
    if cur_id is not None and cur is not None:
        records[cur_id] = cur
    return records


def _parse_vec(s: str) -> Vec3:
    s = s.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    parts = [float(x.strip()) for x in s.split(",")]
    while len(parts) < 3:
        parts.append(0.0)
    return Vec3(parts[0], parts[1], parts[2])


def _point_location(records: dict[int, dict], point_id: int | None) -> Vec3 | None:
    if point_id is None or point_id not in records:
        return None
    for kind, val in records[point_id]["fields"]:
        if kind == "LOCATION_VEC":
            return val
    return None


def _vertex_point_id(records: dict[int, dict], vertex_id: int | None) -> int | None:
    if vertex_id is None or vertex_id not in records:
        return None
    ptrs = [v for k, v in records[vertex_id]["fields"] if k == "POINTER"]
    # vertex: attrib, edge-ish, ..., point pointer is last non-null typically
    for p in reversed(ptrs):
        if p is not None and p in records and records[p]["type"] == "point":
            return p
    return None


def _ellipse_from_record(rec: dict) -> tuple[Vec3, Vec3, Vec3, float] | None:
    locs = [v for k, v in rec["fields"] if k == "LOCATION_VEC"]
    dirs = [v for k, v in rec["fields"] if k == "DIRECTION_VEC"]
    doubles = [v for k, v in rec["fields"] if k == "DOUBLE"]
    if not locs or len(dirs) < 2:
        return None
    ratio = float(doubles[0]) if doubles else 1.0
    return locs[0], dirs[0], dirs[1], ratio


def _nubs_from_intcurve_record(rec: dict) -> tuple[int, list[float], list[Vec3]] | None:
    """Parse degree, knot vector, control points from intcurve-curve SAB fields."""
    fields = rec["fields"]
    i = 0
    while i < len(fields):
        if fields[i] == ("ENTITY_TYPE", "nubs"):
            break
        i += 1
    else:
        return None
    i += 1
    try:
        if fields[i][0] != "INT":
            return None
        degree = int(fields[i][1])
        i += 1
        while i < len(fields) and fields[i][0] == "ENUM":
            i += 1
        nums: list[tuple[str, Any]] = []
        while i < len(fields) and fields[i][0] in ("INT", "DOUBLE"):
            nums.append(fields[i])
            i += 1
        j = 0
        knots: list[float] = []
        while j + 2 < len(nums):
            if not (
                nums[j][0] == "INT"
                and nums[j + 1][0] == "DOUBLE"
                and nums[j + 2][0] == "INT"
            ):
                break
            if all(x[0] == "DOUBLE" for x in nums[j + 3 :]):
                break
            mult = int(nums[j][1])
            knots.extend([float(nums[j + 1][1])] * max(1, mult))
            j += 2
        if j < len(nums) and nums[j][0] == "INT":
            j += 1
        dbls = [float(x[1]) for x in nums[j:] if x[0] == "DOUBLE"]
        n_pts = len(dbls) // 3
        if n_pts < 2:
            return None
        cps = [
            Vec3(dbls[k], dbls[k + 1], dbls[k + 2]) for k in range(0, 3 * n_pts, 3)
        ]
        return degree, knots, cps
    except Exception:
        return None


def _intcurve_is_ref_only(rec: dict) -> bool:
    """True when intcurve stores only an ACIS ``ref`` (no inline NUBS)."""
    types = [b for a, b in rec.get("fields", []) if a == "ENTITY_TYPE"]
    return "ref" in types and "nubs" not in types


def _nubs_cps_aligned(
    rec: dict, start: Vec3, end: Vec3
) -> tuple[int, list[Vec3], list[float] | None] | None:
    """Extract NUBS control points aligned to edge ends.

    Prefer endpoint-anchored double-stream extraction (ACIS dumps interleave
    knots with coordinates). Attach a knot vector only when a full parse
    yields the same control-point count and a valid knot length.
    """
    fields = rec["fields"]
    i = 0
    while i < len(fields) and fields[i] != ("ENTITY_TYPE", "nubs"):
        i += 1
    if i >= len(fields):
        return None
    i += 1
    if i >= len(fields) or fields[i][0] != "INT":
        return None
    degree = int(fields[i][1])
    i += 1
    while i < len(fields) and fields[i][0] == "ENUM":
        i += 1
    # Doubles only until the next ENTITY_TYPE (ignore fit-point trailer)
    dbls: list[float] = []
    while i < len(fields) and fields[i][0] != "ENTITY_TYPE":
        if fields[i][0] == "DOUBLE":
            dbls.append(float(fields[i][1]))
        i += 1
    if len(dbls) < 6:
        return None

    def _near(a: float, b: float) -> bool:
        return abs(a - b) <= max(1e-3, 1e-4 * max(1.0, abs(b)))

    # Anchor at whichever endpoint appears first in the double stream (NUBS
    # storage order), then trim to the other end and orient to start→end.
    anchor = None
    for off in range(0, len(dbls) - 2):
        if _near(dbls[off], start.x) and _near(dbls[off + 1], start.y):
            anchor = off
            break
        if _near(dbls[off], end.x) and _near(dbls[off + 1], end.y):
            anchor = off
            break
    if anchor is None:
        return None
    usable = dbls[anchor:]
    n_pts = len(usable) // 3
    if n_pts < 2:
        return None
    cps = [Vec3(usable[k], usable[k + 1], usable[k + 2]) for k in range(0, 3 * n_pts, 3)]
    while len(cps) > 2 and cps[-1].magnitude < 1e-6:
        cps.pop()
    # Trim after first control point near the opposite endpoint
    opp = end if cps[0].distance(start) <= cps[0].distance(end) else start
    for idx in range(1, len(cps)):
        if _near(cps[idx].x, opp.x) and _near(cps[idx].y, opp.y):
            cps = cps[: idx + 1]
            break
    # Orient so cps run start → end (coedge traversal)
    reversed_cps = False
    if cps and cps[0].distance(start) > cps[0].distance(end):
        cps = list(reversed(cps))
        reversed_cps = True

    # Knots only when a full NUBS parse matches this control polygon exactly.
    knots: list[float] | None = None
    parsed = _nubs_from_intcurve_record(rec)
    if parsed is not None:
        _deg, kn, pcps = parsed
        order = max(2, min(int(degree) + 1, len(cps)))
        if kn and len(pcps) == len(cps) and len(kn) >= order + len(cps):
            same = all((a - b).magnitude < 1e-3 for a, b in zip(pcps, cps))
            flipped = all(
                (a - b).magnitude < 1e-3 for a, b in zip(pcps, reversed(cps))
            )
            if same or flipped:
                knots = list(kn)
                if flipped ^ reversed_cps:
                    lo, hi = knots[0], knots[-1]
                    knots = [lo + hi - k for k in reversed(knots)]

    return degree, cps, knots


def _nubs_cps_from_ref_intcurve(
    records: dict[int, dict],
    ref_curve_id: int,
    start: Vec3,
    end: Vec3,
) -> tuple[int, list[Vec3], list[float] | None] | None:
    """Resolve ACIS intcurve ``ref`` by translating a sibling NUBS on the same body.

    AutoCAD often stores one extruded end profile as a full ``exact_int_cur`` /
    ``nubs`` and the opposite end as ``ref`` only.  The shared shape is recovered
    by finding another intcurve whose edge ends are a pure translation of
    ``start``/``end``, then applying that translation to its control points.
    """
    # Map curve_id → one edge's vertex endpoints
    curve_ends: dict[int, tuple[Vec3, Vec3]] = {}
    for rid, r in records.items():
        if r.get("type") != "edge":
            continue
        ed = _sab_edge(records, rid)
        if not ed or ed.get("curve") is None:
            continue
        cid = int(ed["curve"])
        if cid in curve_ends or cid == ref_curve_id:
            continue
        sp = _sab_vertex_point(records, ed["start_vtx"])
        ep = _sab_vertex_point(records, ed["end_vtx"])
        if sp is None or ep is None:
            continue
        crec = records.get(cid)
        if not crec or crec.get("type") != "intcurve-curve":
            continue
        if "nubs" not in [b for a, b in crec.get("fields", []) if a == "ENTITY_TYPE"]:
            continue
        curve_ends[cid] = (sp, ep)

    tol = 1e-3
    for cid, (a, b) in curve_ends.items():
        # Same orientation: a→b maps to start→end
        t1 = start - a
        t2 = end - b
        # Reversed: a→b maps to end→start
        t3 = start - b
        t4 = end - a
        use_rev = False
        T: Vec3 | None = None
        if (t1 - t2).magnitude < tol and t1.magnitude > 1e-9:
            T = t1
            use_rev = False
        elif (t1 - t2).magnitude < tol and t1.magnitude <= 1e-9:
            # identical ends — use directly
            T = Vec3(0, 0, 0)
            use_rev = False
        elif (t3 - t4).magnitude < tol:
            T = t3
            use_rev = True
        else:
            continue
        src_start, src_end = (b, a) if use_rev else (a, b)
        aligned = _nubs_cps_aligned(records[cid], src_start, src_end)
        if aligned is None:
            continue
        degree, cps, knots = aligned
        out = [p + T for p in cps]
        if out[0].distance(start) > out[0].distance(end):
            out = list(reversed(out))
            if knots:
                lo, hi = knots[0], knots[-1]
                knots = [lo + hi - k for k in reversed(knots)]
        out[0] = start
        out[-1] = end
        return degree, out, knots
    return None


def _tessellate_curve_record(
    records: dict[int, dict],
    curve_id: int | None,
    t0: float,
    t1: float,
    start: Vec3,
    end: Vec3,
) -> list[tuple]:
    if curve_id is None or curve_id not in records:
        return [_k(start), _k(end)] if start.distance(end) > 1e-9 else [_k(start)]
    rec = records[curve_id]
    ctype = rec["type"]
    if ctype == "straight-curve":
        return [_k(start), _k(end)]
    if ctype == "ellipse-curve":
        ell = _ellipse_from_record(rec)
        if ell is None:
            return [_k(start), _k(end)]
        center, normal, major, ratio = ell
        closed = start.distance(end) < 1e-6
        pts = tessellate_ellipse(
            center, normal, major, ratio, t0, t1, closed=closed
        )
        return pts if pts else [_k(start)]
    if ctype == "intcurve-curve":
        aligned = _nubs_cps_aligned(rec, start, end)
        if aligned is None and _intcurve_is_ref_only(rec):
            aligned = _nubs_cps_from_ref_intcurve(records, int(curve_id), start, end)
        if aligned is None:
            return [_k(start), _k(end)]
        degree, cps, knots = aligned
        if len(cps) < 2:
            return [_k(start), _k(end)]
        try:
            pts = tessellate_bspline(
                cps, degree=min(degree, len(cps) - 1), knots=knots
            )
            if start.distance(end) < 1e-6 and len(pts) >= 3:
                return _uniq_ring(pts)
            # Ensure ends snap to edge vertices
            if pts:
                pts[0] = _k(start)
                pts[-1] = _k(end)
            return pts
        except Exception:
            return [_k(p) for p in cps]
    if start.distance(end) < 1e-6:
        return [_k(start)]
    return [_k(start), _k(end)]


def _field_ptrs(rec: dict) -> list[int | None]:
    return [v for k, v in rec["fields"] if k == "POINTER"]


def _field_bools(rec: dict) -> list[bool]:
    return [v for k, v in rec["fields"] if k == "BOOL"]


def _field_doubles(rec: dict) -> list[float]:
    return [v for k, v in rec["fields"] if k == "DOUBLE"]


def _sab_edge(records: dict[int, dict], edge_id: int) -> dict[str, Any] | None:
    """Parse SAB edge: start_vtx, t0, end_vtx, t1, coedge, curve."""
    if edge_id not in records or records[edge_id]["type"] != "edge":
        return None
    ptrs = _field_ptrs(records[edge_id])
    doubles = _field_doubles(records[edge_id])
    # ptrs: attrib, start_vtx, end_vtx, coedge, curve  (attrib often None)
    useful = [p for p in ptrs]  # keep Nones for position
    # Collect in order skipping leading Nones for attrib/owner
    seq = list(useful)
    # Find first vertex pointer
    i0 = next(
        (
            i
            for i, p in enumerate(seq)
            if p is not None and records.get(p, {}).get("type") == "vertex"
        ),
        None,
    )
    if i0 is None:
        return None
    sv = seq[i0]
    ev = seq[i0 + 1] if i0 + 1 < len(seq) else sv
    if ev is not None and records.get(ev, {}).get("type") != "vertex":
        ev = sv
    # curve = last pointer that is a *-curve
    curve = None
    for p in reversed(seq):
        if p is None:
            continue
        t = records.get(p, {}).get("type")
        if t in ("straight-curve", "ellipse-curve", "intcurve-curve"):
            curve = p
            break
    if curve is None:
        for p in reversed(seq):
            if p is not None and records.get(p, {}).get("type") not in (
                "vertex",
                "coedge",
                "edge",
                None,
            ):
                curve = p
                break
    t0 = float(doubles[0]) if len(doubles) > 0 else 0.0
    t1 = float(doubles[1]) if len(doubles) > 1 else 1.0
    return {"start_vtx": sv, "end_vtx": ev, "t0": t0, "t1": t1, "curve": curve}


def _sab_coedge(records: dict[int, dict], cid: int) -> dict[str, Any] | None:
    """Parse SAB coedge: next, prev, partner, edge, sense, loop."""
    if cid not in records or records[cid]["type"] != "coedge":
        return None
    ptrs = _field_ptrs(records[cid])
    bools = _field_bools(records[cid])
    # ptrs: attrib, next, prev, partner, edge, loop, ...
    seq = list(ptrs)
    i0 = next((i for i, p in enumerate(seq) if p is not None), 0)
    nxt = seq[i0] if i0 < len(seq) else None
    prev = seq[i0 + 1] if i0 + 1 < len(seq) else None
    partner = seq[i0 + 2] if i0 + 2 < len(seq) else None
    edge = seq[i0 + 3] if i0 + 3 < len(seq) else None
    # edge must be type edge — scan
    edge = next(
        (
            p
            for p in seq
            if p is not None and records.get(p, {}).get("type") == "edge"
        ),
        edge,
    )
    loop = next(
        (
            p
            for p in seq
            if p is not None and records.get(p, {}).get("type") == "loop"
        ),
        None,
    )
    sense = bools[0] if bools else False
    return {
        "next": nxt,
        "prev": prev,
        "partner": partner,
        "edge": edge,
        "sense": sense,
        "loop": loop,
    }


def _sab_loop_list(records: dict[int, dict], face_id: int) -> list[int]:
    """All loop ids belonging to face, following next pointers from each seed."""
    seeds = []
    for rid, rec in records.items():
        if rec["type"] != "loop":
            continue
        ptrs = [p for p in _field_ptrs(rec) if p is not None]
        if face_id in ptrs:
            seeds.append(rid)
    # Also chain via next
    seen: set[int] = set()
    ordered: list[int] = []
    for seed in seeds:
        lid = seed
        while lid is not None and lid not in seen:
            seen.add(lid)
            ordered.append(lid)
            ptrs = _field_ptrs(records[lid])
            # next_loop = first non-null pointer that is a loop (other than self)
            nxt = next(
                (
                    p
                    for p in ptrs
                    if p is not None
                    and p != lid
                    and records.get(p, {}).get("type") == "loop"
                ),
                None,
            )
            lid = nxt
    return ordered


def _sab_vertex_point(records: dict[int, dict], vtx_id: int | None) -> Vec3:
    pid = _vertex_point_id(records, vtx_id)
    loc = _point_location(records, pid)
    return loc if loc is not None else Vec3(0, 0, 0)


def _tessellate_sab_loop(records: dict[int, dict], loop_id: int) -> list[tuple]:
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
    ring: list[tuple] = []
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
        sp = _sab_vertex_point(records, ed["start_vtx"])
        ep = _sab_vertex_point(records, ed["end_vtx"])
        t0, t1 = ed["t0"], ed["t1"]
        # coedge.sense True → traverse edge opposite to edge start→end
        if co["sense"]:
            sp, ep = ep, sp
            t0, t1 = t1, t0
        seg = _tessellate_curve_record(records, ed["curve"], t0, t1, sp, ep)
        if not ring:
            ring.extend(seg)
        else:
            if not seg:
                pass
            elif ring[-1] == seg[0]:
                ring.extend(seg[1:])
            elif ring[-1] == seg[-1]:
                ring.extend(list(reversed(seg))[1:])
            else:
                # gap — still append (keeps going; rare SAB glitch)
                ring.extend(seg)
        cid = co["next"]
        if cid == start_co:
            break
    return _uniq_ring(ring)


def loops_from_region_sab(entity) -> list[list[tuple]]:
    """REGION / SURFACE → tessellated loops via SAB dump topology only."""
    sab = getattr(entity, "sab", None) or getattr(entity, "acis_data", None)
    if not sab:
        return []
    try:
        records = _parse_sab_records(sab)
    except Exception:
        return []
    faces = [rid for rid, r in records.items() if r["type"] == "face"]
    out_loops: list[list[tuple]] = []
    for face_id in faces:
        for loop_id in _sab_loop_list(records, face_id):
            ring = _tessellate_sab_loop(records, loop_id)
            if len(ring) >= 3:
                out_loops.append(ring)
    return order_outer_then_holes(out_loops)


# ---------------------------------------------------------------------------
# Direct curve entities (non-REGION)
# ---------------------------------------------------------------------------

def loop_from_circle(e) -> list[tuple] | None:
    c = Vec3(e.dxf.center)
    r = float(e.dxf.radius)
    n = Vec3(e.dxf.extrusion) if hasattr(e.dxf, "extrusion") else Vec3(0, 0, 1)
    major = Vec3(r, 0, 0)
    if abs(n.z) < 0.9:
        major = _rot90_around_normal(Vec3(0, 0, 1), n).normalize() * r
        if major.magnitude_square < 1e-18:
            major = Vec3(r, 0, 0)
    return tessellate_ellipse(c, n, major, 1.0, -math.pi, math.pi, closed=True)


def loop_from_arc(e) -> list[tuple] | None:
    c = Vec3(e.dxf.center)
    r = float(e.dxf.radius)
    a0 = math.radians(float(e.dxf.start_angle))
    a1 = math.radians(float(e.dxf.end_angle))
    n = Vec3(e.dxf.extrusion) if hasattr(e.dxf, "extrusion") else Vec3(0, 0, 1)
    major = Vec3(r, 0, 0)
    pts = tessellate_ellipse(c, n, major, 1.0, a0, a1, closed=False)
    return pts if len(pts) >= 2 else None


def loop_from_ellipse(e) -> list[tuple] | None:
    c = Vec3(e.dxf.center)
    major = Vec3(e.dxf.major_axis)
    ratio = float(e.dxf.ratio)
    n = Vec3(e.dxf.extrusion) if hasattr(e.dxf, "extrusion") else Vec3(0, 0, 1)
    try:
        a0 = float(e.start_param)
        a1 = float(e.end_param)
    except Exception:
        a0, a1 = 0.0, 2 * math.pi
    closed = bool(getattr(e, "is_closed", lambda: abs((a1 - a0) % (2 * math.pi)) < 1e-6)())
    return tessellate_ellipse(c, n, major, ratio, a0, a1, closed=closed or abs(a1 - a0) > 2 * math.pi - 1e-3)


def loop_from_spline(e) -> list[tuple] | None:
    try:
        pts = [_k(p) for p in e.flattening(0.5)]
    except Exception:
        try:
            cps = [Vec3(p) for p in e.control_points]
            pts = tessellate_bspline(cps, degree=int(e.dxf.degree))
        except Exception:
            return None
    pts = _uniq_ring(pts)
    if bool(getattr(e, "closed", False)) or (
        len(pts) >= 3 and Vec3(pts[0]).distance(Vec3(pts[-1])) < 1e-4
    ):
        return pts if len(pts) >= 3 else None
    return None


def loop_from_lwpolyline(e) -> list[tuple] | None:
    if not bool(e.closed):
        return None
    elev = float(getattr(e.dxf, "elevation", 0.0) or 0.0)
    pts: list[tuple] = []
    try:
        flattened = list(e.flattening(distance=0.5))
        pts = [_k((p[0], p[1], elev if len(p) < 3 else p[2])) for p in flattened]
    except Exception:
        pts = [_k((x, y, elev)) for x, y, *_ in e.get_points("xy")]
    pts = _uniq_ring(pts)
    return pts if len(pts) >= 3 else None


def loops_from_hatch(e) -> list[list[tuple]]:
    loops: list[list[tuple]] = []
    try:
        paths = list(e.paths)
    except Exception:
        return []
    for path in paths:
        pts: list[tuple] = []
        try:
            if hasattr(path, "vertices"):
                pts = [_k((v[0], v[1], 0.0)) for v in path.vertices]
            elif hasattr(path, "edges"):
                # approximate by edge endpoints / bulge flattening via polyline path
                for edge in path.edges:
                    name = edge.__class__.__name__.lower()
                    if "line" in name:
                        pts.append(_k((edge.start[0], edge.start[1], 0.0)))
                        pts.append(_k((edge.end[0], edge.end[1], 0.0)))
                    elif "arc" in name or "ellipse" in name:
                        # sample
                        try:
                            for p in edge.flattening(0.5):
                                pts.append(_k((p[0], p[1], 0.0)))
                        except Exception:
                            pts.append(_k((edge.start[0], edge.start[1], 0.0)))
                    elif "spline" in name:
                        try:
                            for p in edge.flattening(0.5):
                                pts.append(_k((p[0], p[1], 0.0)))
                        except Exception:
                            pass
        except Exception:
            continue
        ring = _uniq_ring(pts)
        if len(ring) >= 3:
            loops.append(ring)
    return order_outer_then_holes(loops)


def loops_from_mesh_entity(e) -> list[list[tuple]]:
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
    return []


def face_loops_from_entity(e) -> list[list[tuple]]:
    """Unified entry: one entity → [outer, *holes] tessellated rings."""
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
        loops = loops_from_region_sab(e)
        if loops:
            return loops
        # fallback empty mesh path
        return []
    if t in ("3DFACE", "MESH"):
        return loops_from_mesh_entity(e)
    if t == "LWPOLYLINE":
        lp = loop_from_lwpolyline(e)
        return [lp] if lp else []
    if t == "CIRCLE":
        lp = loop_from_circle(e)
        return [lp] if lp else []
    if t == "ELLIPSE":
        lp = loop_from_ellipse(e)
        return [lp] if lp and len(lp) >= 3 else []
    if t == "SPLINE":
        lp = loop_from_spline(e)
        return [lp] if lp else []
    if t == "HATCH":
        return loops_from_hatch(e)
    return []


def format_stp_dface(nid: dict, loops: list[list[tuple]]) -> str:
    """Build \\stpDface{{outer…},{hole…}} (nodes must already exist in nid).

    Also accepted by the package: single loop ``N0,N1,N2`` or semicolon
    ``outer;hole`` (normalized in TeX).
    """
    parts = []
    for loop in loops:
        names = ",".join(nid[p] for p in loop if p in nid)
        if names.count(",") >= 2:  # ≥3 nodes
            parts.append("{" + names + "}")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0][1:-1]  # bare single loop for backward-compatible docs
    return ",".join(parts)
