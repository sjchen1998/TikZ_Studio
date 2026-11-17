import os
import socket
import threading
import time
import urllib.request

import uvicorn
import webview

from tikzstudio.server import app, ensure_editorconfig, render_export


class Desk:
    def __init__(self):
        self._dir = ""

    def _save_dir(self):
        folder = self._dir
        if not folder or not os.path.isdir(folder):
            home = os.path.expanduser("~")
            docs = os.path.join(home, "Documents")
            folder = docs if os.path.isdir(docs) else home
        return folder

    def save_tex(self, code):
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE,
            directory=self._save_dir(),
            save_filename="tikz.tex",
            file_types=("TeX (*.tex)", "All files (*.*)"),
        )
        if not picked:
            return {"ok": False, "cancelled": True}
        path = picked[0]
        if not path.lower().endswith(".tex"):
            path += ".tex"
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(code if isinstance(code, str) else "")
        except OSError as e:
            return {"ok": False, "err": str(e)}
        self._dir = os.path.dirname(path)
        return {"ok": True, "name": os.path.basename(path), "path": path}

    def export_file(self, code, compiler, fmt):
        fmt = (fmt or "pdf").lower()
        labels = {"pdf": "PDF (*.pdf)", "png": "PNG (*.png)", "svg": "SVG (*.svg)"}
        names = {"pdf": "tikz.pdf", "png": "tikz_600dpi.png", "svg": "tikz.svg"}
        if fmt not in labels:
            return {"ok": False, "err": "未知格式"}
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE,
            directory=self._save_dir(),
            save_filename=names[fmt],
            file_types=(labels[fmt],),
        )
        if not picked:
            return {"ok": False, "cancelled": True}
        path = picked[0]
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        data, err, _name = render_export(code, compiler, fmt)
        if err:
            return {"ok": False, "err": err}
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            return {"ok": False, "err": str(e)}
        self._dir = os.path.dirname(path)
        return {"ok": True, "name": os.path.basename(path), "path": path}


def main():
    ensure_editorconfig()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        _, port = s.getsockname()
    threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=port, log_level="error"),
        daemon=True,
    ).start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(50):
        try:
            urllib.request.urlopen(url, timeout=0.3)
            break
        except Exception:
            time.sleep(0.05)
    window = webview.create_window("TikZ Visual Studio", url, width=1440, height=900, text_select=True, js_api=Desk())
    window.events.closed += lambda: os._exit(0)
    webview.start()


if __name__ == "__main__":
    main()
