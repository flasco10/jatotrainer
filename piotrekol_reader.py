"""Client for the bundled GPL-licensed Piotrekol reader process."""
import atexit
import json
from pathlib import Path, PureWindowsPath
import subprocess
import sys
import threading
import time

HELPER = "Jatotrainer.OsuReader.exe"


def selection(data):
    if not isinstance(data, dict):
        return None
    folder, filename = data.get("folder"), data.get("file")
    if not all(isinstance(value, str) and value and value not in (".", "..")
               and PureWindowsPath(value).name == value for value in (folder, filename)):
        return None
    if not filename.lower().endswith(".osu"):
        return None
    bid = data.get("bid")
    return dict(path=None, folder=folder, file=filename, songs=None,
                bid=max(0, bid) if type(bid) is int else 0, artist=None, title=None,
                mapper=None, version=None, md5=data.get("md5"))


class PiotrekolReader:
    def __init__(self):
        self._started = False
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._process = None
        self._snapshot = None
        self._updated = 0.0

    def poll(self):
        if sys.platform != "win32":
            return None
        with self._lock:
            if not self._started:
                self._started = True
                threading.Thread(target=self._listen, daemon=True).start()
        self._ready.wait(.7)
        with self._lock:
            if self._snapshot and time.monotonic() - self._updated < 3:
                return self._snapshot.copy()
        return None

    def _update(self, result):
        with self._lock:
            self._snapshot = result
            self._updated = time.monotonic()
        self._ready.set()

    def _listen(self):
        helper = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent / HELPER
        if not helper.is_file() and not getattr(sys, "frozen", False):
            helper = helper.parent / "build-tools" / "reader" / HELPER
        while not self._stop.is_set():
            try:
                if not helper.is_file():
                    return
                with subprocess.Popen([str(helper)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                      creationflags=subprocess.CREATE_NO_WINDOW) as proc:
                    with self._lock:
                        self._process = proc
                    try:
                        while not self._stop.is_set():
                            proc.stdin.write("read\n")
                            proc.stdin.flush()
                            line = proc.stdout.readline()
                            if not line:
                                break
                            self._update(selection(json.loads(line)))
                            self._stop.wait(.45)
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
            except (OSError, ValueError):
                pass  # tosu and the gameplay window title remain available.
            finally:
                with self._lock:
                    self._process = None
                self._update(None)
            self._stop.wait(2)

    def close(self):
        self._stop.set()
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()


reader = PiotrekolReader()
atexit.register(reader.close)
