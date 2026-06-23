import atexit
import gc
import logging
import os
import signal
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from faster_whisper import WhisperModel
from waitress import serve

from diagnostics import MemoryMonitor, setup_crash_handler
from version import __version__

PORT_START = 5001
PORT_RANGE = 9  # try 5001–5009

def _log_path():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return Path(base) / "backend.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(_log_path()),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# Resolve paths whether running normally or as a PyInstaller bundle
def _bundle_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def _data_path(rel):
    # Writable data lives next to the executable when frozen, else next to this file
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return Path(base) / rel

def _find_port() -> int:
    for port in range(PORT_START, PORT_START + PORT_RANGE):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OSError(f"All ports {PORT_START}–{PORT_START + PORT_RANGE - 1} are in use")


def _claim_singleton() -> None:
    """Kill any previous backend instance and write our PID, preventing port collisions."""
    pid_file = _data_path("backend.pid")
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, signal.SIGTERM)
                log.info(f"Sent SIGTERM to stale backend PID {old_pid}")
                time.sleep(0.5)
                try:
                    os.kill(old_pid, 0)  # still alive?
                    os.kill(old_pid, signal.SIGKILL)
                    time.sleep(0.3)
                except ProcessLookupError:
                    pass
        except (ValueError, ProcessLookupError, OSError):
            pass
    pid_file.write_text(str(os.getpid()))
    atexit.register(lambda: pid_file.unlink(missing_ok=True))


TRANSCRIPTIONS_DIR = _data_path("transcriptions")
TRANSCRIPTIONS_DIR.mkdir(exist_ok=True)

VALID_MODELS = {"tiny", "base", "small", "medium"}
cfg = {"save_history": True, "model_size": "base"}

app = Flask(__name__, static_folder=_bundle_path("static"), static_url_path="/")
CORS(app)  # allow requests from Tauri's webview origin

setup_crash_handler()
_mem_monitor = MemoryMonitor(interval=30)
_mem_monitor.start()

log.info(f"Just Transcribe This v{__version__}")
log.info("Loading Whisper model (base)...")
model = WhisperModel("base", device="cpu", compute_type="int8")
log.info("Model ready.")


def _load_model(size: str):
    global model
    del model
    gc.collect()
    log.info(f"Loading Whisper model ({size})...")
    model = WhisperModel(size, device="cpu", compute_type="int8")
    log.info("Model ready.")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/version")
def get_version():
    return jsonify({"version": __version__})


@app.route("/config", methods=["GET"])
def get_config():
    return jsonify(cfg)


@app.route("/config", methods=["POST"])
def set_config():
    data = request.get_json(force=True)
    if "save_history" in data:
        cfg["save_history"] = bool(data["save_history"])
    if "model_size" in data:
        size = data["model_size"]
        if size not in VALID_MODELS:
            return jsonify({"error": f"Invalid model. Choose from: {', '.join(VALID_MODELS)}"}), 400
        if size != cfg["model_size"]:
            cfg["model_size"] = size
            _load_model(size)
    return jsonify(cfg)


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    audio_file = request.files["file"]
    if not audio_file.filename:
        return jsonify({"error": "Empty filename"}), 400

    tmp_path = Path(f"/tmp/whisper_{audio_file.filename}")
    audio_file.save(tmp_path)
    try:
        segments, _ = model.transcribe(str(tmp_path), beam_size=5)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        txt_name = None
        if cfg["save_history"]:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = Path(audio_file.filename).stem
            txt_name = f"{timestamp}_{stem}.txt"
            (TRANSCRIPTIONS_DIR / txt_name).write_text(text)
        return jsonify({"text": text, "filename": txt_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        tmp_path.unlink(missing_ok=True)


@app.route("/history", methods=["GET"])
def get_history():
    limit  = request.args.get("limit",  50,  type=int)
    offset = request.args.get("offset", 0,   type=int)
    all_files = sorted(TRANSCRIPTIONS_DIR.glob("*.txt"), reverse=True)
    page = all_files[offset : offset + limit]
    return jsonify({
        "total": len(all_files),
        "items": [{"filename": f.name, "text": f.read_text()} for f in page],
    })


@app.route("/history", methods=["DELETE"])
def clear_history():
    for f in TRANSCRIPTIONS_DIR.glob("*.txt"):
        f.unlink()
    return jsonify({"ok": True})


if __name__ == "__main__":
    _claim_singleton()
    port = _find_port()
    if port != PORT_START:
        log.warning(f"Port {PORT_START} still in use after cleanup; binding {port} instead")
    serve(app, host="127.0.0.1", port=port)
