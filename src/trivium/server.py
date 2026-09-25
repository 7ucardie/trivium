"""Keep the model warm: `ask serve` runs this; `ask` talks to it and falls back to loading in-process."""

from __future__ import annotations

import codecs
import json
import os
import subprocess
import sys
import time
from collections import deque
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

HOST = "127.0.0.1"


def make_server(engine, port: int, backend: str = "semif", cfg: dict | None = None) -> HTTPServer:
    import threading
    from collections import OrderedDict
    from importlib.resources import files
    from urllib.parse import parse_qs, urlparse

    from . import config, log, security, session, status

    cfg = cfg or config.load()
    router = session.Router(cfg=cfg, engine=engine)
    runtime = getattr(engine, "runtime", None) or getattr(getattr(engine, "semif", None), "runtime", "n/a")
    stats = {"started": time.time(), "routes": 0, "generates": 0, "errors": 0, "route_ms": deque(maxlen=500)}
    stats_lock = threading.Lock()
    api_token = security.token()
    extra_origins = cfg["router"].get("allowed_origins") or []
    decisions: OrderedDict[str, dict] = OrderedDict()  # decisions made through the API, by id

    def count(key: str, ms: float | None = None) -> None:
        with stats_lock:
            stats[key] += 1
            if ms is not None:
                stats["route_ms"].append(ms)

    def info() -> dict:
        with stats_lock:
            return {"model": engine.metadata["source"], "backend": backend, "runtime": runtime,
                    "load_seconds": engine.load_seconds, **stats, "route_ms": list(stats["route_ms"])}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        # --- plumbing ---------------------------------------------------------------------------

        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin and origin in extra_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _json(self, code: int, body) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                raise PermissionError("POST bodies must be application/json")
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def _allowed(self, api: bool) -> bool:
            if not security.host_ok(self.headers.get("Host"), self.server.server_address[1]):
                self._json(403, {"error": "unexpected Host header"})
                return False
            if not security.origin_ok(self.headers.get("Origin"), self.server.server_address[1], extra_origins):
                self._json(403, {"error": "origin not allowed"})
                return False
            if api and not security.token_ok(self.headers.get(security.TOKEN_HEADER), api_token):
                self._json(401, {"error": f"missing or wrong {security.TOKEN_HEADER}"})
                return False
            return True

        def _stream(self, chunks, content_type: str = "text/plain; charset=utf-8") -> None:
            # Start the generator before the headers, so a backend that cannot answer (Laya,
            # llama.cpp) gives a clean 400 instead of a broken stream.
            chunks = iter(chunks)
            first = next(chunks, "")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            for text in _chain(first, chunks):
                self.wfile.write(text.encode())
                self.wfile.flush()

        def _page(self, html: str) -> None:
            data = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            # The dashboard holds the token: never let another site frame it.
            self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.end_headers()
            self.wfile.write(data)

        # --- routes -----------------------------------------------------------------------------

        def do_OPTIONS(self):
            origin = self.headers.get("Origin")
            if not security.host_ok(self.headers.get("Host"), self.server.server_address[1]) or origin not in extra_origins:
                self.send_response(403)
                self.end_headers()
                return
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", f"Content-Type, {security.TOKEN_HEADER}")
            self.end_headers()

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/favicon.ico":
                self.send_response(204)
                return self.end_headers()
            if not self._allowed(api=url.path.startswith("/api/")):
                return
            if url.path == "/health":
                return self._json(200, {"model": engine.metadata["source"], "backend": backend,
                                        "runtime": runtime, "load_seconds": engine.load_seconds})
            if url.path == "/":
                template = (files("trivium") / "web" / "dashboard.html").read_text()
                return self._page(template.replace("__TRIVIUM_TOKEN__", api_token))
            if url.path == "/status":
                return self._page(status.render(info(), status.recent_decisions(log.LOG)))
            if url.path == "/api/status":
                return self._json(200, info())
            if url.path == "/api/decisions":
                limit = int(parse_qs(url.query).get("limit", ["25"])[0])
                return self._json(200, status.recent_decisions(log.LOG, min(limit, 200)))
            if url.path == "/api/projects":
                return self._json(200, session.recent_projects())
            if url.path == "/api/targets":
                return self._json(200, [router.target_info(t) for t in cfg["targets"]])
            self._json(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            if not self._allowed(api=path.startswith("/api/")):
                return
            try:
                body = self._body()
                if path == "/route":
                    started = time.perf_counter()
                    probs, timing = engine.route(body["state"], body["questions"])
                    count("routes", (time.perf_counter() - started) * 1000)
                    return self._json(200, {"probabilities": probs, "timing": timing})
                if path == "/generate":
                    count("generates")
                    return self._stream(engine.generate(body["prompt"], body.get("max_tokens", 2048)))
                if path == "/api/decide":
                    started = time.perf_counter()
                    d = router.decide(body["prompt"], body.get("cwd") or os.path.expanduser("~"))
                    count("routes", (time.perf_counter() - started) * 1000)
                    decisions[d["id"]] = d
                    while len(decisions) > 500:
                        decisions.popitem(last=False)
                    return self._json(200, d)
                if path == "/api/pick":
                    d = self._decision(body)
                    return self._json(200, router.pick(d["id"], body["target"]))
                if path == "/api/rate":
                    router.rate(body["id"], body["verdict"], body.get("should"))
                    return self._json(200, {"ok": True})
                if path == "/api/run":
                    d = self._decision(body)
                    target = body.get("target") or d["target"]["name"]
                    if target not in cfg["targets"]:
                        raise ValueError(f"unknown target {target!r}")
                    if body.get("mode") == "terminal":
                        script = router.open_in_terminal(target, d["prompt"], d["cwd"])
                        return self._json(200, {"opened": True, "target": target, "script": str(script)})
                    count("generates")
                    # One JSON object per line: {"kind": "text" | "status" | "error", "text": ...}
                    events = (json.dumps({"kind": k, "text": t}) + "\n"
                              for k, t in router.one_shot(target, d["prompt"], d["cwd"]))
                    return self._stream(events, "application/x-ndjson")
                self._json(404, {"error": "not found"})
            except PermissionError as error:
                self._json(415, {"error": str(error)})
            except LookupError as error:
                self._json(404, {"error": str(error)})
            except (ValueError, RuntimeError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
                count("errors")
                self._json(400, {"error": str(error)})

        def _decision(self, body: dict) -> dict:
            d = decisions.get(body.get("id", ""))
            if d is None:
                raise LookupError("unknown decision id; route the prompt again")
            return d

        def log_request(self, code="-", size="-"):
            # The pages poll the API and `ask` checks /health on every call: keep those quiet.
            quiet = self.command == "GET" and str(code) in ("200", "204")
            if not quiet:
                super().log_request(code, size)

        def log_message(self, fmt, *args):
            sys.stderr.write(f"trivium: {fmt % args}\n")

    # Threads, so a long one-shot answer does not block routing. The engines lock around every
    # forward pass, so the model still runs one request at a time.
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    httpd.daemon_threads = True
    return httpd


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
          f"(loaded in {engine.load_seconds:.1f}s)\n  dashboard: http://{HOST}:{port}/", file=sys.stderr)
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
