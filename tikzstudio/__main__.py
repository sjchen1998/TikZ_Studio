import os
import socket
import threading
import time
import urllib.request

import uvicorn
import webview

from tikzstudio.server import app


def main():
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
    window = webview.create_window("TikZ Visual Studio", url, width=1440, height=900, text_select=True)
    window.events.closed += lambda: os._exit(0)
    webview.start()


if __name__ == "__main__":
    main()
