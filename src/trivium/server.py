"""Keep the model warm: `ask serve` runs this; `ask` talks to it and falls back to loading in-process."""

from __future__ import annotations

import codecs
import json
import sys
import time
from collections import deque
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"


def make_server(engine, port: int, backend: str = "semif") -> HTTPServer:
    from . import log, status

    runtime = getattr(engine, "runtime", None) or getattr(getattr(engine, "semif", None), "runtime", "n/a")
    stats = {"started": time.time(), "routes": 0, "generates": 0, "errors": 0, "route_ms": deque(maxlen=500)}

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                return self._json(200, {"model": engine.metadata["source"], "backend": backend,
                                        "runtime": runtime, "load_seconds": engine.load_seconds})
            if self.path == "/":
                info = {"model": engine.metadata["source"], "backend": backend, "runtime": runtime,
                        "load_seconds": engine.load_seconds, **stats, "route_ms": list(stats["route_ms"])}
                page = status.render(info, status.recent_decisions(log.LOG)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                return self.wfile.write(page)
            if self.path == "/favicon.ico":
                self.send_response(204)
                return self.end_headers()
            self._json(404, {"error": "not found"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                if self.path == "/route":
                    started = time.perf_counter()
                    probs, timing = engine.route(body["state"], body["questions"])
                    stats["routes"] += 1
                    stats["route_ms"].append((time.perf_counter() - started) * 1000)
                    return self._json(200, {"probabilities": probs, "timing": timing})
                if self.path == "/generate":
                    # Start the generator before sending headers, so a backend that cannot
                    # generate (Laya) returns a clean 400 instead of a broken stream.
                    chunks = iter(engine.generate(body["prompt"], body.get("max_tokens", 2048)))
                    first = next(chunks, "")
                    stats["generates"] += 1
                    # HTTP/1.0 with no Content-Length: stream until we close the connection.
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    for text in _chain(first, chunks):
                        self.wfile.write(text.encode())
                        self.wfile.flush()
                    return
                self._json(404, {"error": "not found"})
            except (ValueError, KeyError, RuntimeError) as error:
                stats["errors"] += 1
                self._json(400, {"error": str(error)})

        def log_request(self, code="-", size="-"):
            # The status page refreshes itself and `ask` checks /health on every call: keep those quiet.
            if self.command == "GET" and self.path in ("/", "/health", "/favicon.ico") and str(code) in ("200", "204"):
                return
            super().log_request(code, size)

        def log_message(self, fmt, *args):
            sys.stderr.write(f"trivium: {fmt % args}\n")

    # Single-threaded on purpose: one Metal forward pass at a time.
    return HTTPServer((HOST, port), Handler)


def port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def _chain(first: str, rest):
    yield first
    yield from rest


def serve(engine, port: int, backend: str = "semif") -> None:
    httpd = make_server(engine, port, backend)
    print(f"trivium: serving {engine.metadata['source']} on http://{HOST}:{port} "
          f"(loaded in {engine.load_seconds:.1f}s) · status page: http://{HOST}:{port}/", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


class Remote:
    """Same interface as Engine, over HTTP."""

    def __init__(self, port: int):
        self.base = f"http://{HOST}:{port}"
        self.metadata = {"source": "remote"}
        self.backend = None

    def alive(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/health", timeout=0.5) as r:
                health = json.load(r)
                self.metadata = {"source": health["model"]}
                # Servers from before this field existed could only run semif.
                self.backend = health.get("backend", "semif")
                return r.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def _post(self, path: str, body: dict, timeout: float):
        request = urllib.request.Request(
            f"{self.base}{path}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(request, timeout=timeout)

    def route(self, state: dict, questions: dict) -> tuple[dict, dict]:
        try:
            with self._post("/route", {"state": state, "questions": questions}, timeout=60) as r:
                body = json.load(r)
        except urllib.error.HTTPError as error:
            raise ValueError(json.load(error).get("error", str(error))) from error
        return body["probabilities"], body["timing"]

    def generate(self, prompt: str, max_tokens: int = 2048):
        try:
            response = self._post("/generate", {"prompt": prompt, "max_tokens": max_tokens}, timeout=600)
        except urllib.error.HTTPError as error:
            raise RuntimeError(json.load(error).get("error", str(error))) from error
        with response as r:
            decoder = codecs.getincrementaldecoder("utf-8")()
            while chunk := r.read1(256):
                yield decoder.decode(chunk)
