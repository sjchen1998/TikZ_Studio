"""Beam/shell section → cross-section area, volume and mass from CAE DXF XData.

MY_CAE_SEC on LINE: type, spec, material, …
MY_CAE_SHELL_PROP on REGION/MESH/…: theory, thick, offset, material, …
Coordinates and section dimensions are mm; mass in kg.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

# kg/mm³
_DENSITY_KG_PER_MM3: dict[str, float] = {
    "Q235B": 7.85e-6,
    "Q355B": 7.85e-6,
    "45STEEL": 7.85e-6,
    "AL6061": 2.70e-6,
    "CONCRETE": 2.40e-6,
}

# Approximate area (mm²) for common Chinese channel / angle when dims are incomplete
_CHANNEL_AREA_MM2 = {
    "[5": 692.8,
    "[6.3": 845.0,
    "[8": 1024.0,
    "[10": 1274.0,
    "[12": 1530.0,
    "[12.6": 1570.0,
    "[14": 1850.0,
    "[16": 2190.0,
    "[18": 2570.0,
    "[20A": 2883.0,
    "[20A]": 2883.0,
    "[20B": 3284.0,
    "[22A": 3183.0,
    "[25A": 3491.0,
    "[28A": 4002.0,
    "[30A": 4402.0,
    "[32A": 4850.0,
    "[36A": 6090.0,
    "[40A": 7500.0,
}


def material_density(mat: str) -> float:
    key = re.sub(r"[^A-Za-z0-9]", "", (mat or "")).upper()
    if key in _DENSITY_KG_PER_MM3:
        return _DENSITY_KG_PER_MM3[key]
    if "AL" in key or "ALUM" in key:
        return _DENSITY_KG_PER_MM3["AL6061"]
    if "CONC" in key:
        return _DENSITY_KG_PER_MM3["CONCRETE"]
    # default structural steel
    return _DENSITY_KG_PER_MM3["Q355B"]


def _nums(spec: str) -> list[float]:
    return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+", spec or "")]


def section_area_mm2(sec_type: str, sec_spec: str) -> float | None:
    """Cross-section area (mm²) from SETSEC type + size string. None if unknown."""
    t = (sec_type or "").strip()
    s = (sec_spec or "").strip()
    tl = t.lower()
    nums = _nums(s)

    if tl == "circle":
        # D50 / 50 → diameter
        if not nums:
            return None
        d = nums[0]
        return math.pi * (0.5 * d) ** 2

    if tl == "pipe":
        # D114x4.5 → OD, thickness
        if len(nums) < 2:
            return None
        od, th = nums[0], nums[1]
        ri = max(0.0, 0.5 * od - th)
        return math.pi * ((0.5 * od) ** 2 - ri**2)

    if tl == "rect":
        if len(nums) < 2:
            return None
        return nums[0] * nums[1]

    if tl == "recttube":
        # HxWxT
        if len(nums) < 3:
            return None
        h, w, th = nums[0], nums[1], nums[2]
        inner_h = max(0.0, h - 2 * th)
        inner_w = max(0.0, w - 2 * th)
        return h * w - inner_h * inner_w

    if tl == "ibeam":
        # HM200x150x6x9 → H, B, tw, tf
        if len(nums) >= 4:
            h, b, tw, tf = nums[0], nums[1], nums[2], nums[3]
            return 2.0 * b * tf + max(0.0, h - 2.0 * tf) * tw
        if len(nums) >= 2:
            # rough plate estimate
            return nums[0] * nums[1] * 0.15
        return None

    if tl == "angle":
        # L100x10 or L100x80x10
        if len(nums) >= 3:
            a, b, th = nums[0], nums[1], nums[2]
            return (a + b - th) * th
        if len(nums) >= 2:
            a, th = nums[0], nums[1]
            return (2.0 * a - th) * th
        return None

    if tl == "channel":
        key = s.upper().replace(" ", "")
        for k, area in _CHANNEL_AREA_MM2.items():
            if key.startswith(k.upper()) or key == k.upper():
                return area
        if len(nums) >= 3:
            h, b, th = nums[0], nums[1], nums[2]
            return h * th + 2.0 * max(0.0, b - th) * th
        return None

    if tl == "custom":
        if nums:
            return nums[0]  # treat first number as area mm² if provided
        return None

    return None


def _tag_pairs(tags) -> list[tuple[int, Any]]:
    out = []
    for t in tags or []:
        code = getattr(t, "code", None)
        val = getattr(t, "value", t)
        if code is None and isinstance(t, (tuple, list)) and len(t) >= 2:
            code, val = t[0], t[1]
        if code is not None:
            out.append((int(code), val))
    return out


def _parse_sec_xdata(tags) -> tuple[str, str, str] | None:
    pairs = _tag_pairs(tags)
    strs = [str(v) for c, v in pairs if c == 1000 and isinstance(v, str)]
    if len(strs) < 3:
        return None
    return strs[0], strs[1], strs[2]


def _parse_shell_prop_xdata(tags) -> tuple[float, str] | None:
    """Return (thickness_mm, material)."""
    pairs = _tag_pairs(tags)
    thick = None
    mat = None
    for c, v in pairs:
        if c == 1040 and thick is None:
            thick = float(v)
        elif c == 1000 and isinstance(v, str) and v.upper() not in (
            "SHELL_3D",
            "PLANE_STRESS",
            "PLANE_STRAIN",
        ):
            mat = v
    if thick is None or mat is None:
        return None
    return thick, mat


def _dist(a, b) -> float:
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(3)))


def polygon_area_3d(pts: Iterable[tuple]) -> float:
    """Newell polygon area (mm²)."""
    pts = list(pts)
    n = len(pts)
    if n < 3:
        return 0.0
    nx = ny = nz = 0.0
    for i in range(n):
        x1, y1, z1 = (float(pts[i][0]), float(pts[i][1]), float(pts[i][2]))
        x2, y2, z2 = (
            float(pts[(i + 1) % n][0]),
            float(pts[(i + 1) % n][1]),
            float(pts[(i + 1) % n][2]),
        )
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)


def format_sci_tex(value: float, digits: int = 3) -> str:
    """1.234e+06 → 1.23\\times 10^{6}"""
    if value == 0.0:
        return "0"
    exp = int(math.floor(math.log10(abs(value))))
    mant = value / (10**exp)
    if abs(mant - round(mant)) < 10 ** (-digits):
        mant_s = f"{mant:.{0}f}"
    else:
        mant_s = f"{mant:.{digits}g}"
    if exp == 0:
        return mant_s
    return rf"{mant_s}\times 10^{{{exp}}}"


def format_mass_tex(mass_kg: float) -> str:
    if mass_kg >= 1000.0:
        return rf"{mass_kg / 1000.0:.3g}\,\mathrm{{t}}"
    if mass_kg >= 1.0:
        return rf"{mass_kg:.3g}\,\mathrm{{kg}}"
    return rf"{mass_kg * 1000.0:.3g}\,\mathrm{{g}}"


def format_volume_tex(vol_mm3: float) -> str:
    # 1 m³ = 1e9 mm³; prefer m³ for frame-scale volumes
    if vol_mm3 >= 1e6:
        return rf"{format_sci_tex(vol_mm3 / 1e9)}\,\mathrm{{m}}^{{3}}"
    if vol_mm3 >= 1e3:
        return rf"{format_sci_tex(vol_mm3 / 1e3)}\,\mathrm{{cm}}^{{3}}"
    return rf"{format_sci_tex(vol_mm3)}\,\mathrm{{mm}}^{{3}}"


def format_length_mm_tex(val: float) -> str:
    """TeX length for overall dims; CAE coords are mm."""
    if abs(val - round(val)) < 1e-6:
        return rf"{int(round(val))}\,\mathrm{{mm}}"
    return rf"{val:.4g}\,\mathrm{{mm}}"


def emit_struct_info_tex(vol_mm3: float, mass_kg: float) -> str:
    """TikZ lines placing V/m at the upper-right of the current picture bbox."""
    v = format_volume_tex(vol_mm3)
    m = format_mass_tex(mass_kg)
    return (
        f"  % Structure mass properties (UR of current figure bbox)\n"
        f"  \\stpStructInfo{{$V={v}$}}{{$m={m}$}}"
    )


def accumulate_from_dxf(
    doc,
    *,
    face_loops_fn=None,
) -> dict:
    """Sum beam + shell volume/mass from modelspace XData.

    face_loops_fn(entity) -> list[list[xyz]] optional; used for shell area.
    """
    msp = doc.modelspace()
    vol = 0.0
    mass = 0.0
    n_beam = 0
    n_shell = 0
    skipped = 0

    for e in msp:
        if e.dxftype() != "LINE":
            continue
        layer = (e.dxf.layer or "").upper()
        if layer.startswith("CAE_VIS") or layer.startswith("CAE_LOAD"):
            continue
        try:
            tags = e.get_xdata("MY_CAE_SEC")
        except Exception:
            continue
        parsed = _parse_sec_xdata(tags)
        if not parsed:
            continue
        sec_type, sec_spec, mat = parsed
        area = section_area_mm2(sec_type, sec_spec)
        if area is None or area <= 0:
            skipped += 1
            continue
        a, b = e.dxf.start, e.dxf.end
        length = _dist((a.x, a.y, a.z), (b.x, b.y, b.z))
        v = area * length
        dens = material_density(mat)
        vol += v
        mass += v * dens
        n_beam += 1

    for e in msp:
        layer = (e.dxf.layer or "").upper()
        if layer.startswith("CAE_VIS") or layer.startswith("CAE_LOAD"):
            continue
        if e.dxftype() not in (
            "REGION",
            "SURFACE",
            "3DSOLID",
            "3DFACE",
            "MESH",
            "LWPOLYLINE",
        ):
            continue
        try:
            tags = e.get_xdata("MY_CAE_SHELL_PROP")
        except Exception:
            continue
        prop = _parse_shell_prop_xdata(tags)
        if not prop:
            continue
        thick, mat = prop
        if face_loops_fn is None:
            skipped += 1
            continue
        raw = face_loops_fn(e) or []
        # Accept polyline loops or curve-edge loops (via curve_loops_as_polylines)
        if raw and raw[0] and hasattr(raw[0][0], "kind"):
            from .cae_face_curves import curve_loops_as_polylines

            loops = curve_loops_as_polylines(raw)
        else:
            loops = raw
        # Outer minus holes (outer first, then holes)
        if not loops:
            skipped += 1
            continue
        area = abs(polygon_area_3d(loops[0]))
        for hole in loops[1:]:
            area -= abs(polygon_area_3d(hole))
        if area <= 0:
            skipped += 1
            continue
        v = area * float(thick)
        dens = material_density(mat)
        vol += v
        mass += v * dens
        n_shell += 1

    return {
        "volume_mm3": vol,
        "mass_kg": mass,
        "n_beam": n_beam,
        "n_shell": n_shell,
        "skipped": skipped,
    }
