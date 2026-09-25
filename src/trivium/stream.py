"""Turn `claude -p` and `codex exec` progress into events a front end can show while it waits.

Plain `claude -p` prints nothing until the whole answer is done, and a model that thinks for a minute
looks like no answer at all. So one-shot runs use the CLIs' JSON streams and yield (kind, text):
  ("text", ...)    answer text, as it arrives
  ("status", ...)  what the tool is doing: thinking, running a command, editing files
  ("error", ...)   why there is no answer
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

Event = tuple[str, str]


def claude_flags() -> list[str]:
    return ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]


def claude_events(lines: Iterable[str]) -> Iterator[Event]:
    streamed = False
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                yield "status", line.strip()[:200]
            continue
        kind = e.get("type")
        if kind == "system" and e.get("subtype") == "status" and e.get("status") == "requesting":
            yield "status", "waiting for the model"
        elif kind == "stream_event":
            ev = e.get("event") or {}
            if ev.get("type") == "content_block_start":
                block = ev.get("content_block") or {}
                if block.get("type") == "thinking":
                    yield "status", "thinking"
                elif block.get("type") in ("tool_use", "server_tool_use"):
                    yield "status", f"using {block.get('name', 'a tool')}"
            elif ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    streamed = True
                    yield "text", delta["text"]
        elif kind == "result":
            if e.get("is_error") or e.get("subtype") not in (None, "success"):
                yield "error", str(e.get("result") or e.get("subtype") or "claude reported an error")
            elif not streamed and e.get("result"):
                yield "text", e["result"]  # no partial messages arrived: show the final answer


def codex_events(lines: Iterable[str]) -> Iterator[Event]:
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            text = line.strip()
            if text and text != "Reading additional input from stdin...":
                yield "status", text[:200]
            continue
        kind = e.get("type", "")
        item = e.get("item") or {}
        itype = item.get("type")
        if kind in ("item.started", "item.updated"):
            if itype == "reasoning":
                yield "status", "thinking"
            elif itype == "command_execution":
                yield "status", f"running {item.get('command', 'a command')}"[:200]
            elif itype == "file_change":
                yield "status", "editing files"
            elif itype in ("web_search", "mcp_tool_call"):
                yield "status", f"using {itype.replace('_', ' ')}"
        elif kind == "item.completed":
            if itype == "agent_message" and item.get("text"):
                yield "text", item["text"] + "\n"
            elif itype == "error":
                yield "error", item.get("message", "codex reported an error")
        elif kind == "turn.failed":
            yield "error", (e.get("error") or {}).get("message", "codex turn failed")
        elif kind == "error":
            yield "error", e.get("message", "codex reported an error")
