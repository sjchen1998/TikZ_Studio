# TikZ Studio

[中文](#中文) · [English](#english)

## 中文

在本机编辑 TikZ 和 circuitikz。左边是源码，右边用 XeLaTeX 或 pdfLaTeX 编译出预览。点预览上的坐标就能改图，不用先把投影算成平面坐标。界面可在中文与英文之间切换。

本项目以 [GPL-3.0](LICENSE) 发布。

### 绘图

打开模板，或在当前图上继续加内容。面板会跟着图的类型切换：

| 图 | 面板 | 常住内容 |
| --- | --- | --- |
| 电路 | 电路 | 文字、线、R/C/L、电源、开关，以及尺寸、半径、直径、角度 |
| 框图 | 框图 | 文字、方框、圆角、椭圆、圆柱、梯形、判断、箭头、折线箭头、透明填充 |
| 函数曲线 | 曲线 | 函数、散点、标注，以及尺寸类标注 |
| 平面图 | 二维 | 点、线段、函数，以及尺寸类标注 |
| 含 tikz-3dplot 的图 | 三维 | 线段、箭头、圆、圆弧，以及尺寸类标注 |

内置模板有 RC 滤波、Buck、运放、框图、2D/3D 结构分析、曲线、二维坐标、CMS 三维、高斯分布和频率响应。2D/3D 结构分析使用工程内 `satopdf` 宏包（`texmf/tex/latex/local/`，编译时通过 `TEXINPUTS` 自动找到）。

框图里的方框、圆角、椭圆、圆柱、梯形、判断要填**代号**；代号重复时会提示「代号已存在」。带代号的节点编译后会显示吸附点，画箭头或折线箭头时可吸附到端口。折线箭头支持多转折点，接近水平或竖直时会正交吸附；右键或「确认」结束。尺寸、半径、直径、角度、回转与坐标轴等可从「＋」按需加入。

每个面板还能加直线、矩形、圆、弧、椭圆线、虚线、网格等通用图形（具体项随面板略有不同）。元件库里没有的符号，可以用 `{{1}}`、`{{2}}`、`{{文字}}`、`{{角度}}` 做成自己的按钮。

工具栏的「导入 DXF」按当前模板分流：在 **2D/3D 结构分析** 下生成 `satopdf` 图（含约束与载荷）；**3D** 还会把板壳 `REGION`/`3DFACE`/`MESH` 画成 `\stpDface`，并把 `SETSHELLLOAD` Face（`P_face`/`F_total`）画成 `\stpDfaceload`。其它模板只导入直线、多段线、圆、圆弧、椭圆、样条和文字等几何，忽略 `CAE_VIS_*` 载荷/约束块。单位按 DXF 记录换算；普通几何导入会缩到大约 16cm 并把左下角移到原点。

三维圆和圆弧写在指定平面上。平面可以是 `xy`、`xz`、`yz`，也可以写一个法向，或写两个方向。第一个方向是 0°。圆心可以用 `(0,0,1.55)`，也可以用图里已有的名字，例如 `(O)`。

### 改图

预览上的点分成三种：红点是数值坐标，蓝点是名字或相对位置，紫点是比例点。拖动红点会写回源码。相同数值可以联动，一条语句上的坐标可以一起平移。吸附网格可选自由、0.05、0.1 或 0.25。

Ctrl 或 Shift 点击可以多选。也可以拖出方框，或点全选。选中后用 ΔX、ΔY 平移，或填缩放、旋转再点变换。坐标轴（`planeaxes`）与网格上的点不进框选/多选/全选，坐标轴只能在输入框里改范围。尺寸、半径、直径、角度相关点同样受保护。

全选后的缩放作用在整幅图上：坐标、圆和弧的半径、`--++` 的长度，以及 `\tdplotsetcoord` 里的向量长度一起变。只框选一部分时，改的是框里的数值坐标。

选中坐标时，状态栏显示行号，源码里对应行会高亮。点空白处即取消选择。

预览可以放大查看。结果可导出 PDF、600 dpi PNG 或 SVG。桌面版保存 `.tex` 时会弹出另存为对话框。编译失败时会退回上一份能通过的源码，也可以手动撤销。

### 运行

需要本机已安装 Python、TeX Live（含 XeLaTeX、ctex、circuitikz、tikz-3dplot、pgfplots），以及：

```
pip install -r requirements.txt
```

桌面窗口：

```
python -m tikzstudio
```

或只开网页，默认地址是 `http://127.0.0.1:8765`：

```
python -m tikzstudio.server
```

`start_tikz_studio.bat` 从自己所在的目录启动桌面窗口。整个项目换到别的文件夹后，直接双击即可。

## English

Edit TikZ and circuitikz on this computer. The source is on the left. XeLaTeX or pdfLaTeX draws the preview on the right. Click a coordinate in the preview to change the figure, without first turning a projection into plane coordinates. The UI can switch between Chinese and English.

This project is released under [GPL-3.0](LICENSE).

### Drawing

Open a template, or keep adding to the current figure. The panel follows the kind of picture:

| Picture | Panel | Always on the bar |
| --- | --- | --- |
| Circuit | Circuit | Text, wire, R/C/L, sources, switch, plus dimension / radius / diameter / angle |
| Block diagram | Blocks | Text, box, rounded, ellipse, cylinder, trapezoid, decision, arrow, polyline arrow, transparent fill |
| Function plot | Plot | Function, scatter, label, plus dimension tools |
| Plane figure | 2D | Point, segment, function, plus dimension tools |
| Picture using tikz-3dplot | 3D | Segment, arrow, circle, arc, plus dimension tools |

Built-in templates: RC filter, Buck converter, op-amp, block diagram, 2D/3D SA, plot, 2D axes, CMS in 3D, Gaussian, and frequency response. 2D/3D SA uses the in-tree `satopdf` package under `texmf/tex/latex/local/` (found via `TEXINPUTS` at compile time).

Block shapes that carry text need an **ID**. A duplicate ID shows “ID already exists”. Named nodes expose snap ports after compile, so arrows and polyline arrows can latch onto them. A polyline arrow accepts multiple corners, snaps near horizontal or vertical while placing or dragging, and finishes with right-click or Confirm. Dimension tools, turns, and axis helpers can be added from **＋** when needed.

Every panel can also add shared graphics such as a line, rectangle, circle, arc, ellipse line, dashed line, or grid (exact items vary by panel). A symbol that is not in the library can become your own button with `{{1}}`, `{{2}}`, `{{文字}}`, and `{{角度}}`.

**Import DXF** follows the active template: under **2D/3D SA** it builds a `satopdf` figure (supports and loads included); **3D** also maps shell `REGION`/`3DFACE`/`MESH` to `\stpDface` and `SETSHELLLOAD` Face (`P_face`/`F_total`) to `\stpDfaceload`. Otherwise it imports geometry only (lines, polylines, circles, arcs, ellipses, splines, text) and skips `CAE_VIS_*` load/BC blocks. Geometry imports scale large drawings to about 16 cm and shift the lower-left corner to the origin.

A 3D circle or arc lies on a chosen plane. The plane can be `xy`, `xz`, or `yz`, one normal, or two directions. The first direction is 0°. The center can be `(0,0,1.55)`, or a name already in the figure, such as `(O)`.

### Editing

Points on the preview are of three kinds. A red point is a numeric coordinate, a blue point is a name or a relative position, and a purple point is a ratio. Dragging a red point writes the source. Equal numbers can move together, and the coordinates in one statement can shift as a group. The snap grid can be free, 0.05, 0.1, or 0.25.

Ctrl-click or Shift-click adds to the selection. You can also drag a box, or choose Select all. Then move the selection with ΔX and ΔY, or enter a scale and a rotation and apply the transform. Points on packaged axes (`planeaxes`) and on grids stay out of box / multi / select-all; axes ranges are edited in the input fields. Dimension, radius, diameter, and angle points are protected the same way.

After Select all, scale applies to the whole picture: coordinates, circle and arc radii, lengths written with `--++`, and vector lengths in `\tdplotsetcoord`. A box around part of the figure changes the numeric coordinates inside that box.

The status bar shows the line number of the selected coordinate, and that line is highlighted in the source. Click empty space to clear the selection.

Zoom the preview to look more closely. Export the result as PDF, a 600 dpi PNG, or SVG. On the desktop build, Save opens a Save As dialog for `.tex`. If compilation fails, the editor returns to the last source that compiled. You can also undo by hand.

### Running

Install Python and TeX Live, including XeLaTeX, ctex, circuitikz, tikz-3dplot, and pgfplots. Then:

```
pip install -r requirements.txt
```

Desktop window:

```
python -m tikzstudio
```

Or the page only, at `http://127.0.0.1:8765`:

```
python -m tikzstudio.server
```

`start_tikz_studio.bat` starts the desktop window from the folder that contains the script. Move the project to another folder and double-click the script.
