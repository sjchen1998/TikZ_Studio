# TikZ Studio

[中文](#中文) · [English](#english)

## 中文

在本机编辑 TikZ 和 circuitikz。左边是源码，右边用 XeLaTeX 或 pdfLaTeX 编译出预览。点预览上的坐标就能改图，不用先把投影算成平面坐标。

### 绘图

打开模板，或在当前图上继续加内容。面板会跟着图的类型切换：

| 图 | 面板 | 能直接加的内容 |
| --- | --- | --- |
| 电路 | 电路 | 电阻、电容、电感、电源、开关、二极管、三极管、运放、弹簧、阻尼 |
| 框图 | 框图 | 方框、箭头、圆角、判断、椭圆 |
| 函数曲线 | 曲线 | 函数、散点、柱状、阶梯、平滑、面积 |
| 平面图 | 二维 | 点、线段、函数、坐标轴、刻度 |
| 含 tikz-3dplot 的图 | 三维 | 线段、箭头、圆、圆弧 |

内置模板有 RC 滤波、Buck、运放、框图、曲线、二维坐标、CMS 三维、高斯分布和频率响应。

工具栏的「导入 DXF」读取直线、多段线、圆、圆弧、椭圆、样条和文字，转成 TikZ 再编译。单位按 DXF 里的记录换算成厘米；图太大时缩到大约 16cm，并把左下角移到原点。源码开头的注释写着单位和比例。

三维圆和圆弧写在指定平面上。平面可以是 `xy`、`xz`、`yz`，也可以写一个法向，或写两个方向。第一个方向是 0°。圆心可以用 `(0,0,1.55)`，也可以用图里已有的名字，例如 `(O)`。

每个面板都能加直线、文字、箭头、矩形、圆、弧，以及二维坐标、三维坐标、二维回转和三维回转。元件库里没有的符号，可以用 `{{1}}`、`{{2}}`、`{{文字}}`、`{{角度}}` 做成自己的按钮。

### 改图

预览上的点分成三种：红点是数值坐标，蓝点是名字或相对位置，紫点是比例点。拖动红点会写回源码。相同数值可以联动，一条语句上的坐标可以一起平移。吸附网格可选 0.05、0.1 或 0.25。

Ctrl 或 Shift 点击可以多选。也可以拖出方框，或点全选。选中后用 ΔX、ΔY 平移，或填缩放、旋转再点变换。

全选后的缩放作用在整幅图上：坐标、圆和弧的半径、`--++` 的长度，以及 `\tdplotsetcoord` 里的向量长度一起变。只框选一部分时，改的是框里的数值坐标。

选中坐标时，状态栏显示行号，源码里对应行会高亮。点空白处即取消选择。

预览可以放大查看。结果可导出 PDF、600 dpi PNG 或 SVG。编译失败时会退回上一份能通过的源码，也可以手动撤销。

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

Edit TikZ and circuitikz on this computer. The source is on the left. XeLaTeX or pdfLaTeX draws the preview on the right. Click a coordinate in the preview to change the figure, without first turning a projection into plane coordinates.

### Drawing

Open a template, or keep adding to the current figure. The panel follows the kind of picture:

| Picture | Panel | What you can add |
| --- | --- | --- |
| Circuit | Circuit | Resistor, capacitor, inductor, source, switch, diode, transistor, op-amp, spring, damper |
| Block diagram | Blocks | Box, arrow, rounded box, decision, ellipse |
| Function plot | Plot | Function, scatter, bar, const, smooth, filled area |
| Plane figure | 2D | Point, segment, function, axes, ticks |
| Picture using tikz-3dplot | 3D | Segment, arrow, circle, arc |

Built-in templates: RC filter, Buck converter, op-amp, block diagram, plot, 2D axes, CMS in 3D, Gaussian, and frequency response.

**Import DXF** on the toolbar reads lines, polylines, circles, arcs, ellipses, splines, and text, turns them into TikZ, and compiles. Units recorded in the DXF become centimeters. A figure larger than about 16 cm is scaled down, and its lower-left corner moves to the origin. A comment at the top of the source records the unit and the scale.

A 3D circle or arc lies on a chosen plane. The plane can be `xy`, `xz`, or `yz`, one normal, or two directions. The first direction is 0°. The center can be `(0,0,1.55)`, or a name already in the figure, such as `(O)`.

Every panel can add a line, text, an arrow, a rectangle, a circle, an arc, 2D axes, 3D axes, a 2D turn, and a 3D turn. A symbol that is not in the library can become your own button with `{{1}}`, `{{2}}`, `{{文字}}`, and `{{角度}}`.

### Editing

Points on the preview are of three kinds. A red point is a numeric coordinate, a blue point is a name or a relative position, and a purple point is a ratio. Dragging a red point writes the source. Equal numbers can move together, and the coordinates in one statement can shift as a group. The snap grid can be 0.05, 0.1, or 0.25.

Ctrl-click or Shift-click adds to the selection. You can also drag a box, or choose Select all. Then move the selection with ΔX and ΔY, or enter a scale and a rotation and apply the transform.

After Select all, scale applies to the whole picture: coordinates, circle and arc radii, lengths written with `--++`, and vector lengths in `\tdplotsetcoord`. A box around part of the figure changes the numeric coordinates inside that box.

The status bar shows the line number of the selected coordinate, and that line is highlighted in the source. Click empty space to clear the selection.

Zoom the preview to look more closely. Export the result as PDF, a 600 dpi PNG, or SVG. If compilation fails, the editor returns to the last source that compiled. You can also undo by hand.

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
