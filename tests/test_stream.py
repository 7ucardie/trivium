"""Parsing the real `claude -p --output-format stream-json` and `codex exec --json` output."""

import json
from pathlib import Path

from conftest import FakeProc
from test_runtime import CFG, FakeEngine
from trivium import repl, session, stream

FIXTURES = Path(__file__).parent / "fixtures"


def lines(name):
    return (FIXTURES / name).read_text().splitlines(True)


def test_claude_stream_yields_text_and_thinking():
    events = list(stream.claude_events(lines("claude-stream.jsonl")))
    text = "".join(t for k, t in events if k == "text")
    assert text.split() == ["1", "2", "3", "4", "5"]
    assert ("status", "thinking") in events and not any(k == "error" for k, _ in events)


def test_claude_result_only_and_errors():
    result = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "final"})
    assert list(stream.claude_events([result])) == [("text", "final")]
    failed = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True})
    assert list(stream.claude_events([failed])) == [("error", "error_max_turns")]
    assert list(stream.claude_events(["Error: model not found\n"])) == [("status", "Error: model not found")]


def test_codex_stream_and_failures():
    events = list(stream.codex_events(lines("codex-stream.jsonl")))
    assert events == [("text", "1\n2\n3\n4\n5\n")]  # the stdin notice is dropped
    steps = [json.dumps({"type": "item.started", "item": {"type": "reasoning"}}),
             json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "rg retry"}}),
             json.dumps({"type": "turn.failed", "error": {"message": "usage limit reached"}})]
    assert list(stream.codex_events(steps)) == [
        ("status", "thinking"), ("status", "running rg retry"), ("error", "usage limit reached")]


def test_one_shot_uses_streaming_flags_and_reports_exit_codes(monkeypatch, tmp_path):
    router = session.Router(cfg=CFG, engine=FakeEngine())
    seen = []
    monkeypatch.setattr(session.subprocess, "Popen",
                        lambda cmd, **kw: seen.append(cmd) or FakeProc(lines("claude-stream.jsonl")))
    events = list(router.one_shot("claude-sonnet", "count", str(tmp_path)))
    assert seen[0][:3] == ["claude", "--model", "claude-sonnet-5"] and "--include-partial-messages" in seen[0]
    assert events[0] == ("status", "starting claude (claude-sonnet-5)")
    monkeypatch.setattr(session.subprocess, "Popen", lambda cmd, **kw: FakeProc([], code=2))
    assert list(router.one_shot("codex-sol", "x", str(tmp_path)))[-1] == ("error", "codex exited with code 2")


def test_print_events_shows_status_then_text(capsys):
    got = repl.print_events(iter([("status", "thinking"), ("text", "hello"), ("text", " world"), ("status", "late")]))
    out = capsys.readouterr().out
    assert got and "thinking" in out and out.rstrip().endswith("hello world") and "late" not in out
    assert repl.print_events(iter([("status", "thinking"), ("error", "usage limit")])) is False
    assert "usage limit" in capsys.readouterr().out
