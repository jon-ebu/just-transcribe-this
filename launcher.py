import threading
import time
import webbrowser

from backend import app, PORT
from waitress import serve


def _open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    serve(app, host="127.0.0.1", port=PORT)
