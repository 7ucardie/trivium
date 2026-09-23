"""Append-only decision log: the training and calibration data for later."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

LOG = Path(os.environ.get("TRIVIUM_LOG", Path.home() / ".local" / "state" / "trivium" / "decisions.jsonl"))


def append(record: dict) -> str:
    record = {"id": record.get("id") or uuid.uuid4().hex[:12], "ts": time.time(), **record}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record["id"]


def last_decision() -> dict | None:
    if not LOG.exists():
        return None
    for line in reversed(LOG.read_text().splitlines()):
        record = json.loads(line)
        if record.get("type") == "decision":
            return record
    return None
