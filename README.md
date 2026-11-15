# TikZ Studio

本地 TikZ / circuitikz 编辑器。左侧改代码，右侧编译预览，可以点选坐标、框选后平移和缩放。

## 运行

需要本机已安装 Python、XeLaTeX，以及下面这些包：

```
pip install -r requirements.txt
```

桌面窗口：

```
python desktop_app.py
```

或只开网页，默认地址 `http://127.0.0.1:8765`：

```
python server.py
```

`start_tikz_studio.bat` 从 `C:\tools\TikZ_Studio` 启动桌面窗口。换目录后请改这一行。
