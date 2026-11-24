"""Beam LINE topology: split at intersections + weld hits; inherit XData attrs.

Used by satopdf importers and CAE model export. Coordinates are model units (mm).

A parent LINE with MY_CAE_SEC / MY_CAE_LOAD / endpoint BC·loads becomes one or more
child segments; section copies to every child. Distributed load keeps the same
intensity and direction, but its geometric span is rebound to each child's
endpoints (e.g. q on A→C splits at B into q on A→B and q on B→C). Endpoint-bound
attrs (point load / BC / moment / spring) stay only on the child that still owns
that original START or END node.
"""
from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence


Point = tuple[float, ...]  # 2D or 3D


def key_point(p: Sequence[float], tol: float = 1e-4, dim: int = 3) -> Point:
    """Snap coordinates to a grid so coincident joints merge."""
    coords = [float(p[i]) if i < len(p) else 0.0 for i in range(dim)]
    return tuple(round(c / tol) * tol for c in coords)


def _as_dim(p: Sequence[float], dim: int) -> tuple[float, ...]:
    return tuple(float(p[i]) if i < len(p) else 0.0 for i in range(dim))


def _sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    return tuple(a[i] - b[i] for i in range(len(a)))


def _add(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    return tuple(a[i] + b[i] for i in range(len(a)))


def _scale(v: Sequence[float], s: float) -> tuple[float, ...]:
    return tuple(v[i] * s for i in range(len(v)))


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(a[i] * b[i] for i in range(len(a)))


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(_dot(v, v))


def _cross3(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


@dataclass
class BeamAttrs:
    """XData payload carried from a parent LINE onto split children."""

    handle: str | None = None
    kind: str = "beam"  # "beam" | "rod"  (from MY_CAE_MEMBER_KIND)
    section: dict[str, Any] | None = None  # type / spec / material / …
    dist_load: dict[str, Any] | None = None
    # Endpoint-only records; each item has "end": "START"|"END"
    point_loads: list[dict[str, Any]] = field(default_factory=list)
    moments: list[dict[str, Any]] = field(default_factory=list)
    bcs: list[dict[str, Any]] = field(default_factory=list)
    springs: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_rod(self) -> bool:
        return (self.kind or "beam").strip().lower() == "rod"

    def inherit_for_child(
        self,
        *,
        keep_start: bool,
        keep_end: bool,
        child_a: Point | None = None,
        child_b: Point | None = None,
    ) -> "BeamAttrs":
        """Copy section/load; rebind q span to child ends; keep endpoint records
        only if that original end survives on this child."""

        def _filt(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for it in items:
                end = str(it.get("end", "")).upper()
                if end == "START" and keep_start:
                    out.append(deepcopy(it))
                elif end == "END" and keep_end:
                    out.append(deepcopy(it))
            return out

        dist = None
        if self.dist_load is not None and not self.is_rod:
            dist = deepcopy(self.dist_load)
            # Intensity + direction unchanged; geometric range → child segment
            if child_a is not None and child_b is not None:
                dist["start"] = tuple(child_a)
                dist["end"] = tuple(child_b)

        return BeamAttrs(
            handle=self.handle,
            kind=self.kind,
            section=deepcopy(self.section),
            dist_load=dist,
            point_loads=_filt(self.point_loads),
            moments=_filt(self.moments),
            bcs=_filt(self.bcs),
            springs=_filt(self.springs),
            extra=deepcopy(self.extra),
        )


@dataclass
class BeamSeg:
    a: Point
    b: Point
    attrs: BeamAttrs = field(default_factory=BeamAttrs)

    @property
    def length(self) -> float:
        return _norm(_sub(self.b, self.a))


def project_point_on_segment(
    p: Sequence[float],
    a: Sequence[float],
    b: Sequence[float],
    *,
    tol: float,
) -> tuple[float, Point] | None:
    """If p is within `tol` of segment ab, return (t, foot) with t in [0,1]."""
    dim = len(a)
    p = _as_dim(p, dim)
    ab = _sub(b, a)
    ab2 = _dot(ab, ab)
    if ab2 < 1e-18:
        if _norm(_sub(p, a)) <= tol:
            return 0.0, tuple(a)
        return None
    t = _dot(_sub(p, a), ab) / ab2
    if t < -1e-9 or t > 1.0 + 1e-9:
        return None
    t = min(1.0, max(0.0, t))
    foot = _add(a, _scale(ab, t))
    if _norm(_sub(p, foot)) > tol:
        return None
    return t, foot


def segment_intersection(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
    d: Sequence[float],
    *,
    tol: float,
) -> list[tuple[float, float, Point]]:
    """Intersections / T-joints / overlaps between segments ab and cd.

    Returns list of (t_on_ab, s_on_cd, point). Includes interior crossings and
    cases where an endpoint of one lies on the interior of the other.
    """
    dim = len(a)
    a, b, c, d = _as_dim(a, dim), _as_dim(b, dim), _as_dim(c, dim), _as_dim(d, dim)
    hits: list[tuple[float, float, Point]] = []

    def _add_hit(t: float, s: float, pt: Point) -> None:
        if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= s <= 1.0 + 1e-9:
            t = min(1.0, max(0.0, t))
            s = min(1.0, max(0.0, s))
            hits.append((t, s, pt))

    # Endpoint of one on the other (covers T-junctions + shared vertices)
    for pt, which in ((a, "a"), (b, "b"), (c, "c"), (d, "d")):
        if which in ("a", "b"):
            got = project_point_on_segment(pt, c, d, tol=tol)
            if got is None:
                continue
            s, foot = got
            t = 0.0 if which == "a" else 1.0
            # Skip pure shared endpoint (both ends) — no interior split needed,
            # but still record so callers can merge nodes; t/s at 0/1 are fine.
            _add_hit(t, s, foot)
        else:
            got = project_point_on_segment(pt, a, b, tol=tol)
            if got is None:
                continue
            t, foot = got
            s = 0.0 if which == "c" else 1.0
            _add_hit(t, s, foot)

    ab = _sub(b, a)
    cd = _sub(d, c)
    ab2 = _dot(ab, ab)
    cd2 = _dot(cd, cd)
    if ab2 < 1e-18 or cd2 < 1e-18:
        return _unique_hits(hits, tol)

    if dim == 2:
        # 2D line intersection
        den = ab[0] * cd[1] - ab[1] * cd[0]
        if abs(den) > 1e-12:
            ac = _sub(c, a)
            t = (ac[0] * cd[1] - ac[1] * cd[0]) / den
            s = (ac[0] * ab[1] - ac[1] * ab[0]) / den
            if 1e-9 < t < 1.0 - 1e-9 and 1e-9 < s < 1.0 - 1e-9:
                pt = _add(a, _scale(ab, t))
                _add_hit(t, s, pt)
        else:
            # Parallel / collinear: endpoint projections already cover overlaps
            pass
        return _unique_hits(hits, tol)

    # 3D: closest approach of skew lines; accept if distance ≤ tol
    ab3 = (ab[0], ab[1], ab[2] if len(ab) > 2 else 0.0)
    cd3 = (cd[0], cd[1], cd[2] if len(cd) > 2 else 0.0)
    ac3 = _sub(c, a)
    n = _cross3(ab3, cd3)
    n2 = _dot(n, n)
    if n2 > 1e-16:
        t = _dot(_cross3(ac3, cd3), n) / n2
        s = _dot(_cross3(ac3, ab3), n) / n2
        if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= s <= 1.0 + 1e-9:
            p_ab = _add(a, _scale(ab, min(1.0, max(0.0, t))))
            p_cd = _add(c, _scale(cd, min(1.0, max(0.0, s))))
            if _norm(_sub(p_ab, p_cd)) <= tol:
                mid = _scale(_add(p_ab, p_cd), 0.5)
                _add_hit(t, s, mid)
    else:
        # Parallel / nearly collinear — rely on endpoint-on-segment hits
        pass
    return _unique_hits(hits, tol)


def _unique_hits(
    hits: list[tuple[float, float, Point]], tol: float
) -> list[tuple[float, float, Point]]:
    out: list[tuple[float, float, Point]] = []
    for t, s, pt in hits:
        dup = False
        for _t2, _s2, q in out:
            if _norm(_sub(pt, q)) <= tol:
                dup = True
                break
        if not dup:
            out.append((t, s, pt))
    return out


def _near_endpoint(
    p: Sequence[float],
    a: Sequence[float],
    b: Sequence[float],
    *,
    tol: float,
) -> bool:
    """True if p coincides with a or b within `tol` (weld-at-end → no split)."""
    dim = len(a)
    p = _as_dim(p, dim)
    return _norm(_sub(p, a)) <= tol or _norm(_sub(p, b)) <= tol


def _collect_split_params(
    a: Point,
    b: Point,
    points: Iterable[Point],
    *,
    tol: float,
) -> list[tuple[float, Point]]:
    """Interior hit params on ab. Endpoints (and near-end within tol) skipped —
    a weld or joint already at a segment end must not split that segment."""
    length = _norm(_sub(b, a))
    if length < 1e-18:
        return []
    # Parametric guard scales with tol so near-end welds cannot spawn slivers
    t_eps = max(1e-9, min(0.5 - 1e-12, tol / length))
    hits: list[tuple[float, Point]] = []
    for p in points:
        if _near_endpoint(p, a, b, tol=tol):
            continue
        got = project_point_on_segment(p, a, b, tol=tol)
        if got is None:
            continue
        t, foot = got
        if _near_endpoint(foot, a, b, tol=tol):
            continue
        if not (t_eps < t < 1.0 - t_eps):
            continue
        hits.append((t, foot))
    hits.sort(key=lambda x: x[0])
    uniq: list[tuple[float, Point]] = []
    for t, foot in hits:
        if uniq and abs(t - uniq[-1][0]) < t_eps:
            continue
        uniq.append((t, foot))
    return uniq


def split_segment_at_points(
    seg: BeamSeg,
    points: Iterable[Point],
    *,
    tol: float,
    key_fn: Callable[[Sequence[float]], Point],
) -> list[BeamSeg]:
    """Split one segment at interior points; inherit attrs."""
    a0, b0 = key_fn(seg.a), key_fn(seg.b)
    if a0 == b0:
        return []
    hits = _collect_split_params(a0, b0, points, tol=tol)
    if not hits:
        attrs = seg.attrs.inherit_for_child(
            keep_start=True, keep_end=True, child_a=a0, child_b=b0
        )
        return [BeamSeg(a=a0, b=b0, attrs=attrs)]

    chain: list[Point] = [a0] + [key_fn(foot) for _, foot in hits] + [b0]
    # Drop consecutive duplicates after keying
    clean: list[Point] = []
    for p in chain:
        if not clean or p != clean[-1]:
            clean.append(p)
    if len(clean) < 2:
        return []

    out: list[BeamSeg] = []
    for i in range(len(clean) - 1):
        ca, cb = clean[i], clean[i + 1]
        if ca == cb:
            continue
        attrs = seg.attrs.inherit_for_child(
            keep_start=(ca == a0),
            keep_end=(cb == b0),
            child_a=ca,
            child_b=cb,
        )
        out.append(BeamSeg(a=ca, b=cb, attrs=attrs))
    return out


def _seg_grid_cells(a: Sequence[float], b: Sequence[float], tol: float, cell: float, dim: int):
    """Grid cells touched by segment ab, expanded by tol."""
    ranges: list[tuple[int, int]] = []
    span = 1
    for i in range(dim):
        lo = int(math.floor((min(a[i], b[i]) - tol) / cell))
        hi = int(math.floor((max(a[i], b[i]) + tol) / cell))
        ranges.append((lo, hi))
        span *= hi - lo + 1
        if span > 20000:
            break
    if span > 20000 or not ranges:
        return
    if dim <= 2:
        x0, x1 = ranges[0]
        y0, y1 = ranges[1] if dim > 1 else (0, 0)
        for ix in range(x0, x1 + 1):
            for iy in range(y0, y1 + 1):
                yield (ix, iy)
        return
    x0, x1 = ranges[0]
    y0, y1 = ranges[1]
    z0, z1 = ranges[2]
    for ix in range(x0, x1 + 1):
        for iy in range(y0, y1 + 1):
            for iz in range(z0, z1 + 1):
                yield (ix, iy, iz)


def _candidate_pairs(segs: Sequence[BeamSeg], tol: float) -> list[tuple[int, int]]:
    """Index pairs whose bounding boxes can meet. Replaces the all-pairs loop."""
    n = len(segs)
    if n < 2:
        return []
    dim = len(segs[0].a)
    lengths = [_norm(_sub(s.b, s.a)) for s in segs]
    lengths.sort()
    med = lengths[n // 2]
    cell = max(med, tol * 8.0, 1e-6)
    buckets: dict[tuple, list[int]] = {}
    for i, s in enumerate(segs):
        for key in _seg_grid_cells(s.a, s.b, tol, cell, dim):
            buckets.setdefault(key, []).append(i)
    pairs: set[tuple[int, int]] = set()
    for ids in buckets.values():
        m = len(ids)
        if m < 2:
            continue
        # A very full cell is still correct, just less selective
        for a in range(m):
            ia = ids[a]
            for b in range(a + 1, m):
                ib = ids[b]
                pairs.add((ia, ib) if ia < ib else (ib, ia))
    return list(pairs)


def _axis_box(seg: BeamSeg, tol: float, dim: int) -> tuple[list[float], list[float]]:
    """Axis-aligned box of a segment: min corner and max corner, grown by tol."""
    lo: list[float] = []
    hi: list[float] = []
    for i in range(dim):
        a, b = seg.a[i], seg.b[i]
        if a < b:
            lo.append(a - tol)
            hi.append(b + tol)
        else:
            lo.append(b - tol)
            hi.append(a + tol)
    return lo, hi


def _boxes_separated(
    a0: Sequence[float], a1: Sequence[float], b0: Sequence[float], b1: Sequence[float]
) -> bool:
    """True when the two boxes have no point in common.

    Rejection is cheaper than an overlap test: on any axis, if both of B's
    corners are left of A's min, or both are right of A's max, the boxes miss.
    """
    for i in range(len(a0)):
        if (b0[i] < a0[i] and b1[i] < a0[i]) or (b0[i] > a1[i] and b1[i] > a1[i]):
            return True
    return False


def _joint_points_and_cuts(
    segs: Sequence[BeamSeg],
    *,
    tol: float,
    key_fn: Callable[[Sequence[float]], Point],
) -> tuple[list[Point], list[list[Point]]]:
    """Shared joints, plus interior cut points stored per segment.

    Pair tests use a spatial grid, then a box-separation reject before the
    actual intersection. Cuts are only the hits that fall in a segment
    interior, so splitting does not rescan every other endpoint.
    """
    pts: list[Point] = []
    seen: set[Point] = set()
    cuts: list[list[Point]] = [[] for _ in segs]
    dim = len(segs[0].a) if segs else 3
    boxes = [_axis_box(s, tol, dim) for s in segs]

    def _add(p: Sequence[float]) -> Point:
        k = key_fn(p)
        if k not in seen:
            seen.add(k)
            pts.append(k)
        return k

    for s in segs:
        _add(s.a)
        _add(s.b)

    for i, j in _candidate_pairs(segs, tol):
        a0, a1 = boxes[i]
        b0, b1 = boxes[j]
        if _boxes_separated(a0, a1, b0, b1):
            continue
        si, sj = segs[i], segs[j]
        for _t, _s, pt in segment_intersection(si.a, si.b, sj.a, sj.b, tol=tol):
            on_i = project_point_on_segment(pt, si.a, si.b, tol=tol)
            on_j = project_point_on_segment(pt, sj.a, sj.b, tol=tol)
            if on_i is None or on_j is None:
                continue
            ti, tj = on_i[0], on_j[0]
            interior_i = 1e-9 < ti < 1 - 1e-9
            interior_j = 1e-9 < tj < 1 - 1e-9
            if not (interior_i or interior_j):
                continue
            k = _add(pt)
            if interior_i:
                cuts[i].append(k)
            if interior_j:
                cuts[j].append(k)
    return pts, cuts


def find_all_joint_points(
    segs: Sequence[BeamSeg],
    *,
    tol: float,
    key_fn: Callable[[Sequence[float]], Point],
) -> list[Point]:
    """Endpoints + true crossings / T-junctions between beams."""
    pts, _cuts = _joint_points_and_cuts(segs, tol=tol, key_fn=key_fn)
    return pts


def snap_points_to_beams(
    points: Iterable[Point],
    segs: Sequence[BeamSeg],
    *,
    tol: float,
    key_fn: Callable[[Sequence[float]], Point],
) -> list[Point]:
    """Project free points (welds, …) onto nearby beams; return snapped keys.

    If a point lies within `tol` of a beam endpoint, it snaps to that endpoint
    (shared joint node) rather than an interior foot.
    """
    out: list[Point] = []
    seen: set[Point] = set()
    for p in points:
        best = None
        best_d = tol + 1.0
        best_seg = None
        for s in segs:
            # Prefer true endpoints when the weld sits on a joint
            if _near_endpoint(p, s.a, s.b, tol=tol):
                d_a = _norm(_sub(_as_dim(p, len(s.a)), s.a))
                d_b = _norm(_sub(_as_dim(p, len(s.a)), s.b))
                foot = s.a if d_a <= d_b else s.b
                d = min(d_a, d_b)
                if d < best_d:
                    best_d = d
                    best = foot
                    best_seg = s
                continue
            got = project_point_on_segment(p, s.a, s.b, tol=tol)
            if got is None:
                continue
            _t, foot = got
            d = _norm(_sub(_as_dim(p, len(s.a)), foot))
            if d < best_d:
                best_d = d
                best = foot
                best_seg = s
        if best is not None and best_seg is not None:
            # Final clamp: never keep an interior snap that is still end-near
            if _near_endpoint(best, best_seg.a, best_seg.b, tol=tol):
                d_a = _norm(_sub(best, best_seg.a))
                d_b = _norm(_sub(best, best_seg.b))
                best = best_seg.a if d_a <= d_b else best_seg.b
            k = key_fn(best)
        else:
            k = key_fn(p)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def mesh_beams(
    segs: Sequence[BeamSeg],
    extra_points: Iterable[Point] | None = None,
    *,
    tol: float = 1e-3,
    key_tol: float = 1e-4,
    dim: int = 3,
) -> tuple[dict[Point, Point], list[BeamSeg]]:
    """Split beams at intersections + extra points; return (nodes, children).

    `extra_points` typically includes spot/seam weld samples. Points within
    `tol` of a beam interior are snapped onto it and force a split. A weld that
    lands on a segment endpoint does **not** split that segment (node reused).

    Rods (`attrs.kind == \"rod\"`) are never split — crossings and welds on a
    rod do not cut it. Rod endpoints still act as cutters for neighboring beams.
    """
    key_fn: Callable[[Sequence[float]], Point] = lambda p: key_point(p, key_tol, dim)

    # Normalize input endpoints
    base: list[BeamSeg] = []
    for s in segs:
        a, b = key_fn(s.a), key_fn(s.b)
        if a == b:
            continue
        base.append(BeamSeg(a=a, b=b, attrs=s.attrs))

    rods = [s for s in base if s.attrs.is_rod]

    # Joints among all geometry (rod–beam crossings still cut beams).
    # Interior hits are stored per segment so each beam is split only by
    # points that actually lie on it, not by every other endpoint.
    _joints, cuts = _joint_points_and_cuts(base, tol=tol, key_fn=key_fn)
    extras = snap_points_to_beams(extra_points or [], base, tol=tol, key_fn=key_fn)
    extra_list = list(extras)

    children: list[BeamSeg] = []
    for i, s in enumerate(base):
        if s.attrs.is_rod:
            continue
        pts = cuts[i]
        if extra_list:
            pts = list(pts) + extra_list
        children.extend(split_segment_at_points(s, pts, tol=tol, key_fn=key_fn))
    # Rods pass through intact (no split at welds / crossings)
    for s in rods:
        attrs = s.attrs.inherit_for_child(
            keep_start=True, keep_end=True, child_a=s.a, child_b=s.b
        )
        children.append(BeamSeg(a=s.a, b=s.b, attrs=attrs))

    # Dedup identical undirected edges (keep first attrs — same parent family)
    uniq: list[BeamSeg] = []
    seen_e: set[tuple[Point, Point]] = set()
    for c in children:
        key = tuple(sorted((c.a, c.b)))
        if key in seen_e:
            continue
        seen_e.add(key)
        uniq.append(c)

    nodes: dict[Point, Point] = {}
    for c in uniq:
        nodes[c.a] = c.a
        nodes[c.b] = c.b
    for p in extras:
        nodes[p] = p

    return nodes, uniq


def parse_beam_attrs_from_entity(e) -> BeamAttrs:
    """Read MY_CAE_* XData from a DXF LINE entity into BeamAttrs."""
    attrs = BeamAttrs(handle=str(getattr(e.dxf, "handle", "") or "") or None)

    def _pairs(app: str) -> list[tuple[int, Any]]:
        try:
            tags = e.get_xdata(app)
        except Exception:
            return []
        out = []
        for t in tags or []:
            code = getattr(t, "code", None)
            val = getattr(t, "value", t)
            if code is None and isinstance(t, (tuple, list)) and len(t) >= 2:
                code, val = t[0], t[1]
            if code is not None:
                out.append((int(code), val))
        return out

    # MY_CAE_MEMBER_KIND: BEAM | ROD (default beam)
    kind_xd = _pairs("MY_CAE_MEMBER_KIND")
    for c, v in kind_xd:
        if c == 1000 and isinstance(v, str):
            tag = str(v).strip().upper()
            if tag in ("ROD", "BEAM"):
                attrs.kind = tag.lower()
            break

    # MY_CAE_SEC: type, spec, material, (optional vectors…)
    sec = _pairs("MY_CAE_SEC")
    if sec:
        strs = [str(v) for c, v in sec if c == 1000 and isinstance(v, str)]
        if len(strs) >= 3:
            attrs.section = {
                "type": strs[0],
                "spec": strs[1],
                "material": strs[2],
            }
        vecs = [v for c, v in sec if c in (1010, 1011, 1012, 1013)]
        if len(vecs) >= 2:
            attrs.section = attrs.section or {}
            attrs.section["vy"] = [float(x) for x in vecs[0]]
            attrs.section["vz"] = [float(x) for x in vecs[1]]
        if len(vecs) >= 3:
            attrs.section = attrs.section or {}
            attrs.section["offset"] = [float(x) for x in vecs[2]]

    # MY_CAE_LOAD: Distributed, mag, unit, dir, vis
    ld = _pairs("MY_CAE_LOAD")
    if ld:
        mag = None
        unit = "N/mm"
        direction = None
        for c, v in ld:
            if c == 1040 and mag is None:
                mag = float(v)
            elif c == 1000 and str(v).upper() not in ("DISTRIBUTED",):
                unit = str(v)
            elif c == 1013 and direction is None:
                direction = [float(x) for x in v]
        if mag is not None:
            attrs.dist_load = {
                "magnitude": mag,
                "unit": unit,
                "direction": direction or [0.0, 0.0, -1.0],
            }

    # MY_CAE_POINT_LOAD records: START/END, mag, dir, vis[, unit]
    pl = _pairs("MY_CAE_POINT_LOAD")
    i = 0
    while i < len(pl):
        if (
            i + 3 < len(pl)
            and pl[i][0] == 1000
            and str(pl[i][1]).upper() in ("START", "END")
            and pl[i + 1][0] == 1040
            and pl[i + 2][0] == 1013
        ):
            rec = {
                "end": str(pl[i][1]).upper(),
                "magnitude": float(pl[i + 1][1]),
                "direction": [float(x) for x in pl[i + 2][1]],
            }
            step = 4
            if i + 4 < len(pl) and pl[i + 4][0] == 1000:
                rec["unit"] = str(pl[i + 4][1])
                step = 5
            elif i + 3 < len(pl) and pl[i + 3][0] == 1005:
                step = 4
            attrs.point_loads.append(rec)
            i += step
        else:
            i += 1

    # MY_CAE_BC: START/END + mode + mask …
    bc = _pairs("MY_CAE_BC")
    i = 0
    while i < len(bc):
        if bc[i][0] == 1000 and str(bc[i][1]).upper() in ("START", "END"):
            end = str(bc[i][1]).upper()
            mode = str(bc[i + 1][1]) if i + 1 < len(bc) else "GLOBAL"
            mask = None
            for j in range(i, min(i + 8, len(bc))):
                if bc[j][0] == 1000 and isinstance(bc[j][1], str):
                    s = str(bc[j][1])
                    if len(s) == 6 and set(s) <= {"0", "1"}:
                        mask = s
            attrs.bcs.append({"end": end, "mode": mode, "mask": mask or "111111"})
            i += 6
        else:
            i += 1

    # MY_CAE_MOMENT
    mm = _pairs("MY_CAE_MOMENT")
    i = 0
    while i < len(mm):
        if (
            i + 1 < len(mm)
            and mm[i][0] == 1000
            and str(mm[i][1]).upper() in ("START", "END")
            and mm[i + 1][0] == 1040
        ):
            attrs.moments.append(
                {"end": str(mm[i][1]).upper(), "magnitude": float(mm[i + 1][1])}
            )
            i += 4
        else:
            i += 1

    # MY_CAE_SPRING
    sp = _pairs("MY_CAE_SPRING")
    i = 0
    while i < len(sp):
        if sp[i][0] == 1000 and str(sp[i][1]).upper() in ("START", "END"):
            attrs.springs.append({"end": str(sp[i][1]).upper(), "raw": sp[i : i + 8]})
            i += 8
        else:
            i += 1

    return attrs


def _skip_beam_line(e) -> bool:
    layer = (getattr(e.dxf, "layer", "") or "").upper()
    if layer.startswith("CAE_VIS") or layer.startswith("CAE_LOAD"):
        return True
    # Seam-weld carrier lines are the weld path, not a beam.
    try:
        e.get_xdata("MY_CAE_SEAM_WELD")
        return True
    except Exception:
        return False


def _line_to_seg(e, a: Point, b: Point) -> BeamSeg | None:
    if a == b:
        return None
    attrs = parse_beam_attrs_from_entity(e)
    if attrs.is_rod:
        # Rod: keep section size/material only; drop orient/offset/q;
        # re-bind endpoint axial loads (+ tension / − compression).
        if attrs.section:
            attrs.section = {
                "type": attrs.section.get("type"),
                "spec": attrs.section.get("spec"),
                "material": attrs.section.get("material"),
            }
        attrs.dist_load = None
        attrs.moments = []
        ab = _sub(b, a)
        L = _norm(ab)
        if L > 1e-18:
            ex = _scale(ab, 1.0 / L)
            for pl in attrs.point_loads:
                end = str(pl.get("end", "")).upper()
                # Direction = toward the other end; magnitude stays signed
                pl["direction"] = (
                    list(ex) if end == "START" else list(_scale(ex, -1.0))
                )
                pl["axial"] = True
    elif attrs.dist_load is not None:
        # Initial span = full parent LINE; rebound on every split child
        attrs.dist_load["start"] = a
        attrs.dist_load["end"] = b
    return BeamSeg(a=a, b=b, attrs=attrs)


def collect_beam_segs_from_msp(msp, *, dim: int = 3, key_tol: float = 1e-4) -> list[BeamSeg]:
    """All non-VIS LINE entities as BeamSeg with XData attrs."""
    segs: list[BeamSeg] = []
    for e in msp:
        if e.dxftype() != "LINE" or _skip_beam_line(e):
            continue
        seg = _line_to_seg(
            e,
            key_point(e.dxf.start, key_tol, dim),
            key_point(e.dxf.end, key_tol, dim),
        )
        if seg is not None:
            segs.append(seg)
    return segs


def collect_beam_segs_from_inserts(doc, space, *, dim: int = 3, key_tol: float = 1e-4) -> list[BeamSeg]:
    """LINE entities inside modelspace INSERTs (associative ARRAY items)."""
    from .dxf_import import iter_inserted_entities

    segs: list[BeamSeg] = []
    for e, matrix in iter_inserted_entities(doc, space):
        if e.dxftype() != "LINE" or _skip_beam_line(e):
            continue
        seg = _line_to_seg(
            e,
            key_point(matrix.transform(e.dxf.start), key_tol, dim),
            key_point(matrix.transform(e.dxf.end), key_tol, dim),
        )
        if seg is not None:
            segs.append(seg)
    return segs


def expand_dist_loads(
    meshed: Sequence[BeamSeg],
    vis_loads: Iterable[dict[str, Any]] | None = None,
    *,
    tol: float = 1e-2,
) -> list[dict[str, Any]]:
    """Per-child distributed loads after split.

    Each record: {start, end, magnitude, unit, direction, source}.
    XData loads on meshed segs win; VIS loads are sliced onto collinear
    children that do not already carry XData q.
    """
    out: list[dict[str, Any]] = []
    covered: set[tuple[Point, Point]] = set()

    for s in meshed:
        ld = s.attrs.dist_load
        if not ld:
            continue
        start = tuple(ld.get("start", s.a))
        end = tuple(ld.get("end", s.b))
        out.append(
            {
                "start": start,
                "end": end,
                "magnitude": float(ld["magnitude"]),
                "unit": ld.get("unit") or "N/mm",
                "direction": list(ld.get("direction") or [0.0, 0.0, -1.0]),
                "source": "xdata",
                "handle": s.attrs.handle,
            }
        )
        covered.add(tuple(sorted((s.a, s.b))))

    for vis in vis_loads or []:
        va = tuple(vis["a"])
        vb = tuple(vis["b"])
        mag = float(vis["mag"])
        direction = list(vis["dir"])
        for s in meshed:
            key = tuple(sorted((s.a, s.b)))
            if key in covered:
                continue
            # Child lies on the VIS load span
            on_a = project_point_on_segment(s.a, va, vb, tol=tol)
            on_b = project_point_on_segment(s.b, va, vb, tol=tol)
            if on_a is None or on_b is None:
                continue
            out.append(
                {
                    "start": s.a,
                    "end": s.b,
                    "magnitude": mag,
                    "unit": vis.get("unit") or "N/mm",
                    "direction": direction,
                    "source": "vis",
                    "handle": None,
                }
            )
            covered.add(key)

    return out
