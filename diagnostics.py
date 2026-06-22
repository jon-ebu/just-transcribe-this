import faulthandler
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import psutil

log = logging.getLogger(__name__)


def _diag_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return Path(base) / name


def setup_crash_handler() -> None:
    crash_path = _diag_path("crash.log")
    crash_file = open(crash_path, "a", buffering=1)  # line-buffered
    crash_file.write(f"\n=== Session started {datetime.now().isoformat()} ===\n")

    # Catches C-level crashes: segfaults, SIGABRT from native libs (CTranslate2, etc.)
    faulthandler.enable(file=crash_file)

    original_hook = sys.excepthook

    def _crash_hook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_file.write(f"\n[CRASH] {datetime.now().isoformat()}\n{msg}\n")
        crash_file.flush()
        log.critical("Unhandled exception — written to crash.log")
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _crash_hook
    log.info(f"Crash log: {crash_path}")


class MemoryMonitor(threading.Thread):
    """Logs process memory and CPU to memory.log every `interval` seconds.

    Flushed after every write so the log survives hard crashes.
    """

    def __init__(self, interval: int = 30):
        super().__init__(daemon=True, name="MemoryMonitor")
        self.interval = interval
        self._stop = threading.Event()
        self._path = _diag_path("memory.log")
        self._proc = psutil.Process()

    def run(self) -> None:
        with open(self._path, "a", buffering=1) as f:
            f.write(f"\n=== Session started {datetime.now().isoformat()} ===\n")
            f.flush()
            # Warm up CPU percent (first call always returns 0.0)
            self._proc.cpu_percent(interval=None)
            while not self._stop.wait(self.interval):
                mem = self._proc.memory_info()
                cpu = self._proc.cpu_percent(interval=None)
                line = (
                    f"{datetime.now().isoformat()} "
                    f"RSS={mem.rss / 1_048_576:.1f}MB "
                    f"VMS={mem.vms / 1_048_576:.1f}MB "
                    f"CPU={cpu:.1f}%"
                )
                f.write(line + "\n")
                f.flush()
                log.debug(line)

    def stop(self) -> None:
        self._stop.set()
