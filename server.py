#!/usr/bin/env python3
"""
arXiv Daily Digest: local web app.

Runs a small HTTP server on localhost. Open it in a browser, edit your
keywords/categories/connections path in the Settings panel, and click
Refresh whenever you want new papers -- no need to re-run a script from
the terminal each time.

Everything (the arXiv fetch and your LinkedIn connections file) is read
and served only on localhost; nothing leaves your machine.

Usage:
    python3 server.py
    python3 server.py --port 8765 --no-browser

See README.md for how to keep this running in the background (e.g. as a
macOS LaunchAgent) so the page is always there when you open it.
"""

import argparse
import json
import sys
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from arxiv_core import DEFAULT_CATEGORIES, load_keywords, parse_keywords_text, fetch_and_filter
from ai_insights import generate_suggestions

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CACHE_PATH = BASE_DIR / "cache.json"
AI_CACHE_PATH = BASE_DIR / "ai_insights.json"
INDEX_PATH = BASE_DIR / "index.html"

DEFAULT_CONFIG = {
    "keywords": [],
    "connections_path": "",
    "categories": ",".join(DEFAULT_CATEGORIES),
    "days": 3,  # arXiv posts nothing over the weekend, so 1 day often finds
                # nothing on a Monday morning; 3 comfortably spans that gap.
    "max_results": 2000,
}


def _resolve(path_str):
    """Resolve a possibly-relative path against BASE_DIR rather than
    whatever the current working directory happens to be (matters when the
    server is launched from a LaunchAgent or a different shell)."""
    if not path_str:
        return path_str
    p = Path(path_str).expanduser()
    return str(p if p.is_absolute() else BASE_DIR / p)


_lock = threading.Lock()


def load_config():
    if CONFIG_PATH.exists():
        try:
            config = {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text())}
        except (json.JSONDecodeError, OSError):
            config = dict(DEFAULT_CONFIG)
    else:
        config = dict(DEFAULT_CONFIG)

    legacy_path = config.pop("keywords_path", None)
    if not config.get("keywords") and legacy_path:
        # migrate old file-path-based keyword storage into the inline list
        config["keywords"] = load_keywords(_resolve(legacy_path))

    return config


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "generated_at": None,
        "keywords": [],
        "connections_loaded": 0,
        "papers": [],
        "total_fetched": 0,
        "within_lookback": 0,
        "most_recent_published": None,
        "days": None,
    }


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def do_refresh():
    from datetime import datetime

    config = load_config()
    keywords = config["keywords"]
    categories = [c.strip() for c in config["categories"].split(",") if c.strip()]
    result = fetch_and_filter(
        categories,
        config["days"],
        config["max_results"],
        keywords,
        _resolve(config["connections_path"]) or None,
    )
    cache = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "keywords": keywords,
        "connections_loaded": result["connections_loaded"],
        "papers": result["papers"],
        "total_fetched": result["total_fetched"],
        "within_lookback": result["within_lookback"],
        "most_recent_published": result["most_recent_published"],
        "days": config["days"],
    }
    save_cache(cache)
    return cache


def load_ai_cache():
    if AI_CACHE_PATH.exists():
        try:
            return json.loads(AI_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"date": None, "status": "none", "suggestions": [], "error": None}


def save_ai_cache(data):
    AI_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_ai_job_lock = threading.Lock()
_ai_job_running = False


def run_daily_ai_job():
    global _ai_job_running
    today = date.today().isoformat()
    try:
        with _lock:
            cache = do_refresh()
        suggestions = generate_suggestions(cache["papers"])
        save_ai_cache({"date": today, "status": "ready", "suggestions": suggestions, "error": None})
    except Exception as exc:
        save_ai_cache({"date": today, "status": "error", "suggestions": [], "error": str(exc)})
    finally:
        with _ai_job_lock:
            _ai_job_running = False


def get_or_start_ai_job():
    """Kicks off the Claude suggestions job at most once per calendar day --
    the first page load (or poll) of a new day starts it in the
    background; subsequent calls just report its status."""
    global _ai_job_running
    today = date.today().isoformat()
    cache = load_ai_cache()
    with _ai_job_lock:
        if cache.get("date") != today and not _ai_job_running:
            _ai_job_running = True
            cache = {"date": today, "status": "running", "suggestions": [], "error": None}
            save_ai_cache(cache)
            threading.Thread(target=run_daily_ai_job, daemon=True).start()
    return cache


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = INDEX_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/config":
            self._json(200, load_config())
        elif path == "/api/papers":
            self._json(200, load_cache())
        elif path == "/api/ai-insights":
            self._json(200, get_or_start_ai_job())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        if path == "/api/config":
            try:
                incoming = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON"})
                return
            if isinstance(incoming.get("keywords"), str):
                incoming["keywords"] = parse_keywords_text(incoming["keywords"])
            config = {**DEFAULT_CONFIG, **load_config(), **incoming}
            with _lock:
                save_config(config)
            self._json(200, config)
        elif path == "/api/refresh":
            try:
                with _lock:
                    cache = do_refresh()
                self._json(200, cache)
            except Exception as exc:
                self._json(502, {"error": str(exc)})
        else:
            self._json(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser(description="Run the arXiv Daily Digest local web app.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab.")
    args = ap.parse_args()

    if not CONFIG_PATH.exists():
        initial = dict(DEFAULT_CONFIG)
        seed_keywords_file = BASE_DIR / "keywords.txt"
        if seed_keywords_file.exists():
            initial["keywords"] = load_keywords(str(seed_keywords_file))
        save_config(initial)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"arXiv Daily Digest running at {url} (Ctrl+C to stop)", file=sys.stderr)

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.", file=sys.stderr)


if __name__ == "__main__":
    main()
