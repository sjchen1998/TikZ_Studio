import os, sys, socket, threading, time, urllib.request, webview, uvicorn
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import app
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    _, PORT = s.getsockname()
if __name__ == "__main__":
    threading.Thread(target=lambda: uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error"), daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    for _ in range(50):
        try: urllib.request.urlopen(url, timeout=0.3); break
        except Exception: time.sleep(0.05)
    w = webview.create_window("TikZ Visual Studio", url, width=1440, height=900, text_select=True)
    w.events.closed += lambda: os._exit(0)
    webview.start()
