# TikZ Studio patches to upstream `stanli`

Upstream: [hackl/TikZ-StructuralAnalysis](https://github.com/hackl/TikZ-StructuralAnalysis) / CTAN `stanli` (v3.0, 2016–2018).  
Local package: `stanli.sty` under `texmf/tex/latex/local/`.

TikZ Studio loads **`\usepackage{stanli}`** only.

## Naming: `sa2` = 2D, `sa3` = 3D

TeX control words cannot contain digits, so `\sa2point` is implemented as `\sa` + dispatcher → `\csname sa2point\endcsname`.  
**Write `\sa2...` / `\sa3...` in source** — it works. TikZ style names (`sa2HugeLine`, `sa3Coords`, …) contain digits normally.

| Role | Prefix | Example |
|------|--------|---------|
| 2D commands & styles | `sa2` | `\sa2point`, `sa2HugeLine` |
| 3D commands & styles | `sa3` | `\sa3point`, `sa3HugeLine`, `sa3Coords` |

No short aliases (`\point`, `\dpoint`, `force`, …).

### 2D commands

- `\\sa2addon`
- `\\sa2axis`
- `\\sa2beam`
- `\\sa2dimensioning`
- `\\sa2hinge`
- `\\sa2influenceline`
- `\\sa2internalforces`
- `\\sa2lineload`
- `\\sa2load`
- `\\sa2notation`
- `\\sa2point`
- `\\sa2scaling`
- `\\sa2support`
- `\\sa2temperature`

Styles: `sa2HugeLine` … `sa2TinyLine`, `sa2Force`, `sa2Spring`, `sa2CoilSpring`, `sa2Hatching`, `sa2HatchingSpring`.

### 3D commands

- `\\sa3addon`
- `\\sa3axis`
- `\\sa3beam`
- `\\sa3dimensioning`
- `\\sa3hinge`
- `\\sa3internalforces`
- `\\sa3lineload`
- `\\sa3load`
- `\\sa3notation`
- `\\sa3point`
- `\\sa3scaling`
- `\\sa3setaxis`
- `\\sa3setcoords`
- `\\sa3showpoint`
- `\\sa3subaddon`
- `\\sa3subdimensioning`
- `\\sa3subinternalforces`
- `\\sa3sublineload`
- `\\sa3support`

Styles: `sa3HugeLine` … `sa3TinyLine`, `sa3Force`, `sa3Spring`, `sa3AxisArrow`, `sa3Coords`.

---

## Other patches vs upstream

1. **Space-leak hardening** — `\newcommandx` bodies end with `%`.
2. **Modern TikZ** — `\tikzset`; `arrows.meta`; axis tip `Latex[open]`; drop unused `automata` / `verbatim`.
3. **Stray `;` after `\sub…` helpers** removed.
4. **Author manual** — `stanli.tex` / `stanli.pdf` updated to `\sa2*` / `\sa3*` naming; compile with **LuaLaTeX** (`lualatex` → `makeindex` → `lualatex` ×2).

## Project wiring

| File | Change |
|------|--------|
| `tikzstudio/server.py` | `\usepackage{stanli}` |
| `web/data.js` | 2D → `\sa2*`; 3D → `\sa3*` + `[sa3Coords]` |
| `Example.tex` | Same naming |
| `stanli.pdf` | Rebuilt author manual |
