"""Pathogenic Matrix companion server (Python stdlib only).

Watches the mod's state file (and accepts POSTs from the mod), scores the
visible choices, and pushes updates to the dashboard over Server-Sent Events.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .recommend import Catalog, merge_catalogs, recommend

JSON = dict[str, Any]

APP_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "static"
DEMO_CATALOG = APP_DIR.parent / "data" / "catalog.demo.json"
DEFAULT_PORT = 48710
STATE_FILE = "matrix_state.json"
CATALOG_FILE = "matrix_catalog.json"
LOG_DIR = "matrix_logs"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def default_user_dir() -> Path:
    env = os.environ.get("PATHOGENIC_USER_DIR")
    if env:
        return Path(env)
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return base / "Godot" / "app_userdata" / "Pathogenic"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Godot" / "app_userdata" / "Pathogenic"
    return home / ".local" / "share" / "godot" / "app_userdata" / "Pathogenic"


def load_json(path: Path) -> JSON | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class RecommendationLog:
    """Appends what the app recommended, keyed by the mod's choice_id."""

    def __init__(self, log_dir: Path | None) -> None:
        self._path = None
        self._last: dict[str, list[str]] = {}
        if log_dir is not None:
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                self._path = log_dir / f"recommend_{int(time.time())}.jsonl"
            except OSError:
                self._path = None

    @property
    def path(self) -> Path | None:
        return self._path

    def record(self, state: JSON | None, rec: JSON) -> None:
        if self._path is None:
            return
        for g in rec.get("groups", []):
            cid = g.get("choice_id")
            ranking = [p["key"] for p in g["picks"]]
            if not cid or self._last.get(cid) == ranking:
                continue
            self._last[cid] = ranking
            entry = {
                "ev": "recommendation",
                "ts": time.time(),
                "session": (state or {}).get("session"),
                "choice_id": cid,
                "kind": g.get("kind"),
                "ranking": [
                    {k: p[k] for k in ("key", "label", "score", "score_per_cost", "reasons", "warnings")}
                    for p in g["picks"]
                ],
            }
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")


class Hub:
    def __init__(self, demo_catalog: JSON | None, rec_log: RecommendationLog) -> None:
        self._demo = demo_catalog
        self._live: JSON | None = None
        self.catalog: Catalog = merge_catalogs(demo_catalog, None)
        self.state: JSON | None = None
        self.rec: JSON = recommend(None, self.catalog)
        self.updated = 0.0
        self.version = 0
        self._rec_log = rec_log
        self._cond = threading.Condition()

    def set_catalog(self, live: JSON | None) -> None:
        with self._cond:
            self._live = live
            self.catalog = merge_catalogs(self._demo, live)
            self._recompute()

    def set_state(self, state: JSON) -> None:
        with self._cond:
            self.state = state
            self._recompute()

    def _recompute(self) -> None:
        self.rec = recommend(self.state, self.catalog)
        self.updated = time.time()
        self.version += 1
        self._rec_log.record(self.state, self.rec)
        self._cond.notify_all()

    def snapshot(self, include_catalog: bool = True) -> JSON:
        with self._cond:
            snap: JSON = {
                "state": self.state,
                "rec": self.rec,
                "updated": self.updated,
                "version": self.version,
                "catalog_source": self.catalog.source,
            }
            if include_catalog:
                snap["catalog"] = self.catalog.to_json()
            return snap

    def wait_for_change(self, version: int, timeout: float) -> int:
        with self._cond:
            self._cond.wait_for(lambda: self.version != version, timeout=timeout)
            return self.version


class FileWatcher(threading.Thread):
    def __init__(self, hub: Hub, user_dir: Path, interval: float = 0.2) -> None:
        super().__init__(daemon=True)
        self.hub = hub
        self.state_path = user_dir / STATE_FILE
        self.catalog_path = user_dir / CATALOG_FILE
        self.interval = interval
        self._mtimes: dict[Path, float] = {}
        self._stop = threading.Event()

    def _changed(self, path: Path) -> bool:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        if self._mtimes.get(path) == mtime:
            return False
        self._mtimes[path] = mtime
        return True

    def poll_once(self) -> None:
        if self._changed(self.catalog_path):
            live = load_json(self.catalog_path)
            if live:
                self.hub.set_catalog(live)
        if self._changed(self.state_path):
            state = load_json(self.state_path)
            if state:
                self.hub.set_state(state)

    def run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()


def replay(hub: Hub, log_path: Path, speed: float, stop: threading.Event) -> None:
    """Feed a mod session log (session_*.jsonl) into the hub as if live."""
    prev_ts = None
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            if stop.is_set():
                return
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("ev") == "catalog" and isinstance(ev.get("catalog"), dict):
                hub.set_catalog(ev["catalog"])
            state = ev.get("state")
            if not isinstance(state, dict):
                continue
            ts = float(ev.get("ts", 0))
            if prev_ts is not None and speed > 0:
                stop.wait(min(2.0, max(0.0, ts - prev_ts) / speed))
            prev_ts = ts
            hub.set_state(state)


def make_handler(hub: Hub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "PathogenicMatrix/0.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/state":
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                state = json.loads(self.rfile.read(length))
            except ValueError:
                self._send(HTTPStatus.BAD_REQUEST, b"bad json", "text/plain")
                return
            if not isinstance(state, dict):
                self._send(HTTPStatus.BAD_REQUEST, b"expected object", "text/plain")
                return
            hub.set_state(state)
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/events":
                self._events()
            elif path == "/state":
                self._json(hub.snapshot())
            elif path == "/recommend":
                self._json(hub.snapshot(include_catalog=False)["rec"])
            else:
                self._static(path)

        def _events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            version = -1
            sent_catalog_source = None
            try:
                while True:
                    new_version = hub.wait_for_change(version, timeout=15.0)
                    if new_version == version:
                        self.wfile.write(b": keepalive\n\n")
                    else:
                        version = new_version
                        snap = hub.snapshot(include_catalog=False)
                        if snap["catalog_source"] != sent_catalog_source:
                            snap = hub.snapshot(include_catalog=True)
                            sent_catalog_source = snap["catalog_source"]
                        self.wfile.write(f"data: {json.dumps(snap)}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR not in target.parents or not target.is_file():
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            self._send(HTTPStatus.OK, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pathogenic Matrix companion server")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--user-dir",
        type=Path,
        default=None,
        help="Folder the mod writes to (default: Pathogenic's Godot user:// folder)",
    )
    ap.add_argument("--replay", type=Path, help="Replay a mod session log instead of watching the game")
    ap.add_argument("--speed", type=float, default=4.0, help="Replay speed multiplier (0 = as fast as possible)")
    ap.add_argument("--open", action="store_true", help="Open the dashboard in your browser")
    args = ap.parse_args(argv)

    user_dir: Path = args.user_dir or default_user_dir()
    rec_log = RecommendationLog(None if args.replay else user_dir / LOG_DIR)
    hub = Hub(load_json(DEMO_CATALOG), rec_log)
    stop = threading.Event()

    watcher = None
    if args.replay:
        threading.Thread(target=replay, args=(hub, args.replay, args.speed, stop), daemon=True).start()
    else:
        watcher = FileWatcher(hub, user_dir)
        watcher.start()

    server = ThreadingHTTPServer((args.host, args.port), make_handler(hub))
    server.daemon_threads = True
    url = f"http://localhost:{args.port}/"
    print(f"Pathogenic Matrix running at {url}")
    print(f"Replaying {args.replay}" if args.replay else f"Watching {user_dir / STATE_FILE}")
    if rec_log.path:
        print(f"Recommendation log: {rec_log.path}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if watcher:
            watcher.stop()
        server.server_close()
    return 0
