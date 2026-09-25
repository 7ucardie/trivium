"""Who may talk to the local server.

`ask serve` can start `claude` and `codex`, so a web page open in the browser must not be able to use
it. Three checks:
  - Host must be 127.0.0.1 or localhost on our port, which stops DNS-rebinding attacks.
  - POST bodies must be application/json, which makes browsers send a CORS preflight that we only
    answer for allowed origins; a page on another site cannot even send the request.
  - /api needs the token from ~/.local/state/trivium/api-token. The dashboard gets it inside its own
    page, which other origins cannot read. Another tool, such as your own dashboard, can read the file.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from . import log

TOKEN_HEADER = "X-Trivium-Token"


def token_path() -> Path:
    return Path(os.environ.get("TRIVIUM_TOKEN_FILE", log.LOG.parent / "api-token"))


def token() -> str:
    path = token_path()
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    # Create it readable by the owner only.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value + "\n")
    return value


def allowed_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def own_origins(port: int) -> set[str]:
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


def host_ok(host: str | None, port: int) -> bool:
    return (host or "") in allowed_hosts(port)


def origin_ok(origin: str | None, port: int, extra: list[str]) -> bool:
    """No Origin (curl, the ask CLI) or one of ours or one configured in router.allowed_origins."""
    return origin is None or origin in own_origins(port) or origin in set(extra)


def token_ok(sent: str | None, expected: str) -> bool:
    return bool(sent) and hmac.compare_digest(sent, expected)
