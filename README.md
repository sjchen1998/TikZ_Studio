# TikZ Studio

[中文](#中文) · [English](#english)

## 中文

在本机编辑 TikZ 和 circuitikz。左边是源码，右边用 XeLaTeX 或 pdfLaTeX 编译出预览。可在预览上放置元件、拖动坐标写回源码，不必先把三维投影手工算成平面数。界面可在中文与英文之间切换。

本项目以 [GPL-3.0](LICENSE) 发布。更细的操作说明见：

- [TikZ_Studio_cn.pdf](TikZ_Studio_cn.pdf) / [TikZ_Studio_en.pdf](TikZ_Studio_en.pdf) — 应用使用说明（含编辑详解）
- [lisp/LoadXData_cn.pdf](lisp/LoadXData_cn.pdf) / [lisp/LoadXData_en.pdf](lisp/LoadXData_en.pdf) — AutoCAD `LoadXData.lsp` 说明
- [texmf/tex/latex/local/satopdf.pdf](texmf/tex/latex/local/satopdf.pdf) — `satopdf` 宏包文档

### 界面与基本循环

| 区域 | 内容 |
| --- | --- |
| 左：工具栏 | 编译、撤销、打开 `.tex`、导入 DXF、保存、模板、编译器、语言 |
| 左：元件栏 | 随图类型切换；`＋` 打开元件库 |
| 左：编辑器 | TeX 源码；选中预览点会高亮对应行 |
| 右：预览条 | 缩放、点识别、红/蓝/紫、联动、整体平移、吸附、导出 |
| 右：编辑条 | 全选、放置提示、尺寸样式、X/Y 或 ΔX/ΔY、应用、删除、变换 |
| 右：画布 | SVG 预览与可拖动句柄 |

典型流程：选模板 → 点元件栏进入放置 → 在画布点够点数（或填表）→ **确认** / Enter / **右键** 结束 → 编译刷新句柄 → 拖红点或框选变换 → 导出。

- 取消放置：`Esc` 或「取消」
- 编辑器内编译：`Ctrl+Enter`
- 编译失败：自动退回上一份能通过的源码；也可点「撤销」

切换模板会**替换**当前缓冲区，请先保存。

### 绘图

面板随图类型切换：

| 图 | 面板 | 常住内容 |
| --- | --- | --- |
| 电路 | 电路 | 文字、线、R/C/L、电源、开关，以及尺寸、半径、直径、角度 |
| 框图 | 框图 | 文字、方框、圆角、椭圆、圆柱、梯形、判断、箭头、折线箭头、透明填充 |
| 函数曲线 | 曲线 | 函数、散点、标注，以及尺寸类标注 |
| 平面图 | 二维 | 点、线段、函数，以及尺寸类标注 |
| 含 tikz-3dplot 的图 | 三维 | 线段、箭头、圆、圆弧，以及尺寸类标注 |

内置模板：RC 滤波、Buck、运放、框图、2D/3D 结构分析、曲线、二维坐标、CMS 三维、高斯分布、频率响应。2D/3D 结构分析使用工程内 `satopdf`（`texmf/tex/latex/local/`，经 `TEXINPUTS` 自动找到）。

**放置通则：** 工具需要 0 / 1 / 2（或更多）次点击；0 点工具在编辑条填表后确认。点击优先吸附命名端口/坐标。生成代码插在 `\end{tikzpicture}` / `\end{circuitikz}` / `\end{axis}` 前。

框图中带文字的形状要填**代号**；重复会提示「代号已存在」。编译后具名节点显示吸附点。折线箭头可多转折，开启正交吸附时接近水平/竖直会对齐；右键或「确认」结束。

尺寸：点起点、终点、文字位置；放置时可按 `H`/`V`/`R`（水平/竖直/对齐）、`I`/`O`（箭头内外）、`1`/`2`（抑起/终点）。半径/直径先点圆或弧，再点文字位置。角度先点两条直线，再点文字位置。

通用图形（直线、矩形、圆、弧、椭圆线、虚线、网格等）可从栏或 `＋` 加入。自定义按钮可用 `{{1}}`、`{{2}}`、`{{文字}}`、`{{角度}}`。

三维圆/弧画在指定平面：`xy` / `xz` / `yz`、一个法向或两个方向（第一方向为 0°）。圆心可以是 `(0,0,1.55)` 或已有名字如 `(O)`。

### 改图

| 颜色 | 含义 |
| --- | --- |
| 红点 | 数值坐标，拖动写回源码 |
| 蓝点 | 名字或相对位置 |
| 紫点 | 比例点 |

- **联动**：相同数值一起动；**整体平移**：同一语句（到 `;`）内坐标成组平移
- 吸附网格：自由 / 0.05 / 0.1 / 0.25
- `Ctrl`/`Shift` 点击多选；空白处拖拽框选；「全选」或 `Ctrl+A`（焦点不在输入框时）
- 多选后 X/Y 变为 ΔX/ΔY；可填缩放、旋转再点「变换」
- 全选后的缩放作用于整幅图（坐标、圆/弧半径、`--++` 长度、`\tdplotsetcoord` 向量长）；局部框选只改框内数值
- `planeaxes`、网格点、尺寸类构造点不进多选；轴范围在输入框改
- 关闭「点识别」可加快大图；滚轮以光标为中心缩放预览

导出：PDF、600 dpi PNG、SVG。桌面版「保存」弹出另存为。

### 导入 DXF 与 CAE 流程

「导入 DXF」按**当前模板**分流，并会按文件内容自动升级：

- **2D/3D 结构分析** → `satopdf`（含约束与载荷）；3D 将板壳 `REGION`/`SURFACE`/`3DFACE`/`MESH` 等转为方程边 `\stpDfaceEnv`（line/arc/circle/spline），面载荷落在形心
- **其它模板** → 仅几何（线、多段线、圆、弧、椭圆、样条、文字），忽略 `CAE_VIS_*`；大图缩到约 A0 比例尺
- **自动识别**：若 DXF 含 `REGION`/`SURFACE` 等板壳（或 CAE XData），即使当前是几何模板也会改走 3D/2D 结构导入，无需先手动切换模板

推荐 CAE 管线：AutoCAD 中加载 `lisp/LoadXData.lsp`（`(load "LoadXData.lsp")`，需把 `lisp/` 加入支持路径）标注梁/杆/板壳/焊缝 → 导出 DXF → 在本应用「导入 DXF」→ 编辑导出。

### 快捷键（摘要）

| 操作 | 作用 |
| --- | --- |
| `Ctrl+Enter`（编辑器） | 编译 |
| `Esc` | 取消放置 / 关闭元件库 |
| 放置时右键 | 确认放置 |
| `Ctrl`/`Shift` 点句柄 | 多选 |
| `Ctrl+A`（非输入框） | 全选句柄 |
| 预览滚轮 | 缩放 |
| `H`/`V`/`R`、`I`/`O`、`1`/`2` | 尺寸放置时的样式 |

### 运行

需要 Python、TeX Live（XeLaTeX、pdfLaTeX、ctex、circuitikz、tikz-3dplot、pgfplots），以及：

```
pip install -r requirements.txt
```

桌面窗口：

```
python -m tikzstudio
```

或仅网页（默认 `http://127.0.0.1:8765`）：

```
python -m tikzstudio.server
```

`start_tikz_studio.bat` 从脚本所在目录启动；项目换文件夹后仍可直接双击。

---

## English

Edit TikZ and circuitikz on this computer. Source is on the left; XeLaTeX or pdfLaTeX draws the preview on the right. Place components on the canvas, drag coordinates back into the source, and switch the UI between Chinese and English — without converting a 3D projection to plane numbers by hand.

Released under [GPL-3.0](LICENSE). Full manuals:

- [TikZ_Studio_en.pdf](TikZ_Studio_en.pdf) / [TikZ_Studio_cn.pdf](TikZ_Studio_cn.pdf) — application guide (editing in detail)
- [lisp/LoadXData_en.pdf](lisp/LoadXData_en.pdf) / [lisp/LoadXData_cn.pdf](lisp/LoadXData_cn.pdf) — AutoCAD `LoadXData.lsp`
- [texmf/tex/latex/local/satopdf.pdf](texmf/tex/latex/local/satopdf.pdf) — `satopdf` package docs

### Window and basic loop

| Area | Contents |
| --- | --- |
| Left: toolbar | Compile, Undo, Open `.tex`, Import DXF, Save, Template, compiler, language |
| Left: component bar | Follows picture kind; `+` opens the library |
| Left: editor | TeX source; selecting a preview point highlights its line |
| Right: preview bar | Zoom, point pick, red/blue/purple, Link, Move-all, snap, export |
| Right: edit bar | Select-all, place prompts, dimension style, X/Y or dX/dY, Apply, Delete, Transform |
| Right: canvas | SVG preview with draggable handles |

Typical loop: pick a template → click a tool → click the required points (or fill a form) → **Confirm** / Enter / **right-click** → compile to refresh handles → drag red points or box-transform → export.

- Cancel place: `Esc` or Cancel
- Compile from the editor: `Ctrl+Enter`
- Failed compile: reverts to the last good source; Undo also available

Changing the template **replaces** the buffer — save first if needed.

### Drawing

The panel follows the picture kind:

| Picture | Panel | Always on the bar |
| --- | --- | --- |
| Circuit | Circuit | Text, wire, R/C/L, sources, switch, plus dimension / radius / diameter / angle |
| Block diagram | Blocks | Text, box, rounded, ellipse, cylinder, trapezoid, decision, arrow, polyline arrow, transparent fill |
| Function plot | Plot | Function, scatter, label, plus dimension tools |
| Plane figure | 2D | Point, segment, function, plus dimension tools |
| Picture using tikz-3dplot | 3D | Segment, arrow, circle, arc, plus dimension tools |

Built-in templates: RC filter, Buck, op-amp, block diagram, 2D/3D SA, plot, 2D axes, CMS in 3D, Gaussian, frequency response. 2D/3D SA uses in-tree `satopdf` under `texmf/tex/latex/local/` (via `TEXINPUTS`).

**Placement:** tools need 0 / 1 / 2 (or more) clicks; 0-point tools use the edit-bar form then Confirm. Clicks prefer named ports/coordinates. Snippets insert before `\end{tikzpicture}` / `\end{circuitikz}` / `\end{axis}`.

Block shapes with text need an **ID**; duplicates show “ID already exists”. After compile, named nodes expose snap ports. Polyline arrows take multiple corners; with ortho-snap, near-horizontal/vertical segments lock; finish with right-click or Confirm.

Dimensions: start, end, then label. While placing: `H`/`V`/`R` (horizontal / vertical / aligned), `I`/`O` (arrows in/out), `1`/`2` (hide start/end). Radius/diameter: pick a circle or arc, then the label. Angle: two lines, then the label.

Shared graphics (line, rectangle, circle, arc, ellipse path, dashed, grid, …) come from the bar or `+`. Custom buttons use `{{1}}`, `{{2}}`, `{{text}}`, `{{angle}}`.

A 3D circle/arc lies on `xy` / `xz` / `yz`, one normal, or two directions (first direction is 0°). Centre: `(0,0,1.55)` or a name such as `(O)`.

### Editing

| Colour | Meaning |
| --- | --- |
| Red | Numeric coordinate — drag rewrites the source |
| Blue | Name or relative position |
| Purple | Ratio point |

- **Link:** equal numbers move together; **Move all:** shift every numeric pair on the same statement (through `;`)
- Snap grid: free / 0.05 / 0.1 / 0.25
- `Ctrl`/`Shift`-click to multi-select; drag empty canvas to box-select; Select all or `Ctrl+A` (when focus is not in an input)
- With a multi-selection, X/Y become dX/dY; enter scale/rotation and Transform
- After Select all, scale affects the whole picture (coordinates, circle/arc radii, `--++` lengths, `\tdplotsetcoord` vector lengths); a partial box only rewrites numbers inside it
- `planeaxes`, grid points, and dimension construction points stay out of multi-select; edit axis ranges in the fields
- Turn off Point pick for large figures; mouse wheel zooms toward the cursor

Export PDF, 600 dpi PNG, or SVG. Desktop Save opens Save As for `.tex`.

### DXF import and CAE pipeline

**Import DXF** follows the **active template**, with content-based auto-upgrade:

- **2D/3D SA** → `satopdf` (supports and loads); 3D maps shell `REGION`/`SURFACE`/`3DFACE`/`MESH` to equation edges `\stpDfaceEnv` (line/arc/circle/spline)
- **Other templates** → geometry only (lines, polylines, circles, arcs, ellipses, splines, text); skip `CAE_VIS_*`; sheet scale fits A0
- **Auto-detect**: shell or CAE DXFs are routed to struct3d/struct2d even from a geometry template

Recommended CAE path: in AutoCAD, add `lisp/` to the support path and `(load "LoadXData.lsp")` to annotate beams/rods/shells/welds → export DXF → Import DXF here → edit and export.

### Shortcuts (summary)

| Input | Action |
| --- | --- |
| `Ctrl+Enter` (editor) | Compile |
| `Esc` | Cancel place / close library |
| Right-click while placing | Confirm place |
| `Ctrl`/`Shift`-click handle | Multi-select |
| `Ctrl+A` (outside inputs) | Select all handles |
| Wheel on preview | Zoom |
| `H`/`V`/`R`, `I`/`O`, `1`/`2` | Dimension style while placing |

### Running

Install Python and TeX Live (XeLaTeX, pdfLaTeX, ctex, circuitikz, tikz-3dplot, pgfplots), then:

```
pip install -r requirements.txt
```

Desktop window:

```
python -m tikzstudio
```

Browser only (default `http://127.0.0.1:8765`):

```
python -m tikzstudio.server
```

`start_tikz_studio.bat` starts from its own folder; move the project and double-click again.
