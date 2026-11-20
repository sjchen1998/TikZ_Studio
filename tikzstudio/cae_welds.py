"""Parse MY_CAE_SPOT_WELD / MY_CAE_SEAM_WELD from DXF for satopdf / CAE export."""
from __future__ import annotations

import math
from typing import Callable


def _tag_pairs(tags) -> list[tuple]:
    out = []
    for t in tags or []:
        code = getattr(t, "code", None)
        val = getattr(t, "value", t)
        if code is None and isinstance(t, (tuple, list)) and len(t) >= 2:
            code, val = t[0], t[1]
        out.append((code, val))
    return out


def _is_vis_layer(layer: str) -> bool:
    u = (layer or "").upper()
    return u.startswith("CAE_VIS") or u.startswith("CAE_LOAD")


def _lerp(a, b, t: float):
    return tuple(a[i] + t * (b[i] - a[i]) for i in range(len(a)))


def sample_segment(a, b, spacing: float) -> list[tuple]:
    """Inclusive samples from a→b at approximately `spacing` (model units)."""
    ax, ay, az = float(a[0]), float(a[1]), float(a[2] if len(a) > 2 else 0.0)
    bx, by, bz = float(b[0]), float(b[1]), float(b[2] if len(b) > 2 else 0.0)
    a3, b3 = (ax, ay, az), (bx, by, bz)
    length = math.dist(a3, b3)
    if length < 1e-9:
        return [a3]
    sp = spacing if spacing and spacing > 0 else length
    n = max(1, int(math.floor(length / sp + 1e-9)))
    return [_lerp(a3, b3, i / n) for i in range(n + 1)]


def densify_polyline(verts: list[tuple], spacing: float) -> list[tuple]:
    if not verts:
        return []
    if len(verts) == 1:
        v = verts[0]
        return [(float(v[0]), float(v[1]), float(v[2] if len(v) > 2 else 0.0))]
    out: list[tuple] = []
    for i in range(len(verts) - 1):
        seg = sample_segment(verts[i], verts[i + 1], spacing)
        out.extend(seg if i == 0 else seg[1:])
    return out


def path_pts_from_entity(e, spacing: float) -> list[tuple]:
    """LINE / LWPOLYLINE / ARC → ordered 3D points (WCS)."""
    typ = e.dxftype()
    if typ == "LINE":
        return sample_segment(e.dxf.start, e.dxf.end, spacing)
    if typ == "LWPOLYLINE":
        elev = float(getattr(e.dxf, "elevation", 0.0) or 0.0)
        verts = []
        for x, y, *_rest in e.get_points("xy"):
            verts.append((float(x), float(y), elev))
        return densify_polyline(verts, spacing)
    if typ == "ARC":
        cen = e.dxf.center
        r = float(e.dxf.radius)
        a0 = math.radians(float(e.dxf.start_angle))
        a1 = math.radians(float(e.dxf.end_angle))
        if a1 < a0:
            a1 += 2.0 * math.pi
        arc_len = abs(a1 - a0) * r
        sp = spacing if spacing and spacing > 0 else 5.0
        n = max(8, int(math.floor(arc_len / sp + 1e-9)))
        z = float(cen[2]) if len(cen) > 2 else 0.0
        pts = []
        for i in range(n + 1):
            a = a0 + (a1 - a0) * (i / n)
            pts.append((float(cen[0]) + r * math.cos(a), float(cen[1]) + r * math.sin(a), z))
        return pts
    return []


def parse_spot_welds(msp, key_fn: Callable) -> list[dict]:
    """POINT (+ optional INSERT) with MY_CAE_SPOT_WELD → [{xyz, diameter, fe_type}]."""
    spots: list[dict] = []
    for e in msp:
        if e.dxftype() != "POINT":
            continue
        if _is_vis_layer(e.dxf.layer or ""):
            continue
        try:
            tags = e.get_xdata("MY_CAE_SPOT_WELD")
        except Exception:
            continue
        vals = _tag_pairs(tags)
        if len(vals) < 3:
            continue
        # 1000 SPOT, 1040 dia, 1000 feType, 1005 vis
        dia = 5.0
        fe = "ACM"
        if vals[0][0] == 1000 and str(vals[0][1]).upper() == "SPOT":
            if vals[1][0] == 1040:
                dia = float(vals[1][1])
            if len(vals) > 2 and vals[2][0] == 1000:
                fe = str(vals[2][1] or "ACM").upper()
        else:
            for code, val in vals:
                if code == 1040:
                    dia = float(val)
                elif code == 1000 and str(val).upper() not in ("SPOT",):
                    fe = str(val).upper()
        loc = e.dxf.location
        xyz = key_fn((float(loc[0]), float(loc[1]), float(loc[2] if len(loc) > 2 else 0.0)))
        spots.append({"xyz": xyz, "diameter": dia, "fe_type": fe})
    return spots


def parse_seam_welds(msp, key_fn: Callable) -> list[dict]:
    """LINE/LWPOLYLINE/ARC with MY_CAE_SEAM_WELD → [{pts, weld_type, leg_size, spacing}]."""
    seams: list[dict] = []
    for e in msp:
        typ = e.dxftype()
        if typ not in ("LINE", "LWPOLYLINE", "ARC"):
            continue
        if _is_vis_layer(e.dxf.layer or ""):
            continue
        try:
            tags = e.get_xdata("MY_CAE_SEAM_WELD")
        except Exception:
            continue
        vals = _tag_pairs(tags)
        if len(vals) < 3:
            continue
        # 1000 type, 1040 leg, 1040 spacing, 1005 vis
        weld_type = "FILLET"
        leg = 4.0
        spacing = 5.0
        if vals[0][0] == 1000:
            weld_type = str(vals[0][1] or "FILLET").upper()
        nums = [float(v) for c, v in vals if c == 1040]
        if len(nums) >= 1:
            leg = nums[0]
        if len(nums) >= 2:
            spacing = nums[1]
        raw = path_pts_from_entity(e, spacing)
        pts = [key_fn(p) for p in raw]
        # drop consecutive duplicates
        clean: list[tuple] = []
        for p in pts:
            if not clean or p != clean[-1]:
                clean.append(p)
        if len(clean) < 2:
            continue
        seams.append(
            {
                "pts": clean,
                "weld_type": weld_type,
                "leg_size": leg,
                "spacing": spacing,
            }
        )
    return seams


def emit_weld_tex_2d(
    spot_welds: list[dict],
    seam_welds: list[dict],
    nid: dict,
    *,
    label_spots: bool = True,
) -> list[str]:
    """TeX lines using \\stpSpotWeld / \\stpSeamWeld(Path)."""
    L: list[str] = []
    n_spot = len(spot_welds)
    for i, sw in enumerate(spot_welds):
        name = nid.get(sw["xyz"])
        if not name:
            continue
        dia = sw.get("diameter")
        lab = ""
        if label_spots and dia and (n_spot <= 4 or i in (0, n_spot - 1)):
            lab = f"$\\varnothing {float(dia):g}$"
        if lab:
            L.append(f"  \\stpSpotWeld{{{name}}}[\\stpWeldR][{lab}]")
        else:
            L.append(f"  \\stpSpotWeld{{{name}}}")
    for sm in seam_welds:
        pts = [p for p in sm["pts"] if p in nid]
        if len(pts) < 2:
            continue
        names = [nid[p] for p in pts]
        leg = sm.get("leg_size")
        lab = f"$a={float(leg):g}$" if leg else ""
        if len(names) == 2:
            if lab:
                L.append(f"  \\stpSeamWeld{{{names[0]}}}{{{names[1]}}}[{lab}]")
            else:
                L.append(f"  \\stpSeamWeld{{{names[0]}}}{{{names[1]}}}")
        else:
            joined = ",".join(names)
            if lab:
                L.append(f"  \\stpSeamWeldPath{{{joined}}}[{lab}]")
            else:
                L.append(f"  \\stpSeamWeldPath{{{joined}}}")
    return L


def emit_weld_tex_3d(
    spot_welds: list[dict],
    seam_welds: list[dict],
    nid: dict,
    *,
    label_spots: bool = True,
) -> list[str]:
    """TeX lines using \\stpDspotWeld / \\stpDseamWeld(Path)."""
    L: list[str] = []
    n_spot = len(spot_welds)
    for i, sw in enumerate(spot_welds):
        name = nid.get(sw["xyz"])
        if not name:
            continue
        dia = sw.get("diameter")
        lab = ""
        if label_spots and dia and (n_spot <= 4 or i in (0, n_spot - 1)):
            lab = f"$\\varnothing {float(dia):g}$"
        if lab:
            L.append(f"  \\stpDspotWeld{{{name}}}[\\stpWeldR][{lab}]")
        else:
            L.append(f"  \\stpDspotWeld{{{name}}}")
    for sm in seam_welds:
        pts = [p for p in sm["pts"] if p in nid]
        if len(pts) < 2:
            continue
        names = [nid[p] for p in pts]
        leg = sm.get("leg_size")
        lab = f"$a={float(leg):g}$" if leg else ""
        if len(names) == 2:
            if lab:
                L.append(f"  \\stpDseamWeld{{{names[0]}}}{{{names[1]}}}[{lab}]")
            else:
                L.append(f"  \\stpDseamWeld{{{names[0]}}}{{{names[1]}}}")
        else:
            joined = ",".join(names)
            if lab:
                L.append(f"  \\stpDseamWeldPath{{{joined}}}[{lab}]")
            else:
                L.append(f"  \\stpDseamWeldPath{{{joined}}}")
    return L
