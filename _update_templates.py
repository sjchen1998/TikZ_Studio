"""Regenerate struct2d/struct3d templates in web/data.js from example DXFs."""
from __future__ import annotations

import re
from pathlib import Path

from tikzstudio.dxf_to_satopdf2d import dxf_to_satopdf2d
from tikzstudio.dxf_to_satopdf3d import dxf_to_satopdf3d

ROOT = Path(__file__).resolve().parent


def replace_tpl(src: str, key: str, body: str) -> str:
    pat = re.compile(
        rf"(  {re.escape(key)}: String\.raw`)"
        r"[\s\S]*?"
        r"(`,\n  [a-zA-Z])",
        re.M,
    )
    m = pat.search(src)
    if not m:
        raise SystemExit(f"cannot find template {key}")
    if "`" in body:
        raise SystemExit(f"backtick in {key} body — cannot embed in String.raw")
    # Normalize newlines for JS source
    body = body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return src[: m.start()] + m.group(1) + body + m.group(2) + src[m.end() :]


def main() -> None:
    c2, n2 = dxf_to_satopdf2d(path=ROOT / "example" / "2d_example.dxf")
    c3, n3 = dxf_to_satopdf3d(
        path=ROOT / "example" / "3d_examlpe_hole.dxf",
        fragment=True,
        scale=0.002,
    )
    print("2D:", n2)
    print("3D:", n3)

    data_path = ROOT / "web" / "data.js"
    data = data_path.read_text(encoding="utf-8")
    data = replace_tpl(data, "struct2d", c2)
    data = replace_tpl(data, "struct3d", c3)
    data_path.write_text(data, encoding="utf-8")
    print("updated", data_path)

    tex3, _ = dxf_to_satopdf3d(
        path=ROOT / "example" / "3d_examlpe_hole.dxf",
        fragment=False,
        scale=0.002,
    )
    sa3d = ROOT / "texmf" / "tex" / "latex" / "local" / "satopdf-SA3D.tex"
    sa3d.write_text(tex3, encoding="utf-8")
    print("updated", sa3d)

    # 2D frame reference (fragment wrapped for standalone compile optional)
    frame = ROOT / "texmf" / "tex" / "latex" / "local" / "satopdf-frame.tex"
    frame_body = (
        "% Auto-generated from 2d_example.dxf\n"
        "\\documentclass[border=10pt]{standalone}\n"
        "\\usepackage{satopdf}\n"
        "\\begin{document}\n"
        + c2
        + "\\end{document}\n"
    )
    # Only overwrite if it looks like a satopdf frame demo
    if frame.exists():
        frame.write_text(frame_body, encoding="utf-8")
        print("updated", frame)


if __name__ == "__main__":
    main()
