"""Server, CLI, Laya mapping, calibration and service, all without a real model."""

import io
import json
import os
import pathlib
import plistlib
import re
import sys
import threading
import types

import pytest

from trivium import calibrate, cli, config, launch, policy, server, service

REAL_RESOLVE = launch.resolve  # conftest replaces it for every test

CFG = config.load(config.config_path())


class FakeEngine:
    """Answers from a fixed table keyed by a word in the prompt; generates a canned reply."""

    load_seconds = 0.0

    def __init__(self, answers=None, source="fake", can_generate=True):
        self.answers = answers or {}
        self.metadata = {"source": source}
        self.can_generate = can_generate
        self.calls = []

    def route(self, state, questions):
        self.calls.append(set(questions))
        request = state["request"]
        picked = next((v for k, v in self.answers.items() if k in request), {})
        probs = {}
        for q, spec in questions.items():
            options = list(spec["options"])
            choice = picked.get(q, options[0])
            rest = (1 - 0.9) / (len(options) - 1)
            probs[q] = {o: (0.9 if o == choice else rest) for o in options}
        return probs, {"total_seconds": 0.001}

    def generate(self, prompt, max_tokens=2048):
        if not self.can_generate:
            raise RuntimeError("cannot generate")
        yield from ["local ", "answer"]


QUICK = {"kind": "quick_answer", "difficulty": "trivial", "tools": "none"}
CODE = {"kind": "code_change", "difficulty": "moderate", "tools": "workspace"}


@pytest.fixture
def running_server():
    engine = FakeEngine({"409": QUICK})
    httpd = server.make_server(engine, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield engine, server.Remote(httpd.server_address[1])
    httpd.shutdown()


def test_remote_round_trip(running_server):
    engine, remote = running_server
    assert remote.alive() and remote.metadata["source"] == "fake"
    probs, _ = remote.route({"request": "what is 409", "context": "x"}, CFG["questions"])
    assert max(probs["kind"], key=probs["kind"].get) == "quick_answer"
    assert "".join(remote.generate("hi")) == "local answer"


def test_remote_generate_error_is_clean():
    httpd = server.make_server(FakeEngine(can_generate=False), 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with pytest.raises(RuntimeError, match="cannot generate"):
            "".join(server.Remote(httpd.server_address[1]).generate("hi"))
    finally:
        httpd.shutdown()


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    engine = FakeEngine({"409": QUICK, "retry": CODE})
    monkeypatch.setattr(cli, "backend", lambda cfg, name=None: engine)
    monkeypatch.setattr(cli.log, "LOG", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(cli.state, "repo_name", lambda cwd: "demo")
    return engine, tmp_path / "decisions.jsonl"


def test_why_logs_decision(fake_cli, capsys):
    _, log_file = fake_cli
    assert cli.run(["--dry", "add retry to the client"]) == 0
    assert "codex-sol" in capsys.readouterr().err
    record = json.loads(log_file.read_text().splitlines()[-1])
    assert record["target"] == "codex-sol" and record["backend"] == "semif"


def test_local_answer_streams(fake_cli, capsys):
    assert cli.run(["-p", "what does 409 mean"]) == 0
    assert "local answer" in capsys.readouterr().out


@pytest.mark.skipif(os.name == "nt", reason="Windows has no exec; it runs the CLI and waits")
def test_interactive_launch_uses_execvp(fake_cli, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.os, "execvp", lambda f, argv: seen.update(argv=argv))
    cli.run(["add retry to the client"])
    assert seen["argv"][:3] == ["codex", "-m", "gpt-6-sol"]


def test_one_shot_streams_codex_events(fake_cli, monkeypatch, capsys):
    from conftest import FakeProc
    from trivium import session

    fixture = (pathlib.Path(__file__).parent / "fixtures" / "codex-stream.jsonl").read_text().splitlines(True)
    seen = {}
    monkeypatch.setattr(session.subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd) or FakeProc(fixture))
    assert cli.run(["-p", "add retry to the client"]) == 0
    assert seen["cmd"][:4] == ["codex", "exec", "--json", "-m"]
    assert "1\n2\n3\n4\n5" in capsys.readouterr().out


def test_rate_appends_feedback(fake_cli):
    _, log_file = fake_cli
    cli.run(["--dry", "add retry"])
    assert cli.cmd_rate(["bad", "--should", "opus"]) == 0
    feedback = json.loads(log_file.read_text().splitlines()[-1])
    assert feedback["type"] == "feedback" and feedback["should"] == "claude-opus"


def test_eval_reports_accuracy(fake_cli, tmp_path, capsys):
    rows = [{"prompt": "what does 409 mean", "repo": None, "expect": QUICK},
            {"prompt": "add retry", "repo": "demo", "expect": CODE}]
    f = tmp_path / "eval.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows))
    assert cli.cmd_eval([str(f)]) == 0
    assert re.search(r"target\s+100.0%", capsys.readouterr().out)


def test_calibrate_prints_block(fake_cli, tmp_path, capsys):
    rows = [{"prompt": "what does 409 mean", "repo": None, "expect": QUICK}] * 3
    f = tmp_path / "eval.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows))
    assert cli.cmd_calibrate([str(f)]) == 0
    out = capsys.readouterr().out
    assert "calibration:\n  semif:" in out and "    kind:" in out


def test_removed_hybrid_backend_says_what_to_do():
    with pytest.raises(ValueError, match="hybrid backend .* was removed on 2026-11-24.*router.backend to semif"):
        config.validate({**CFG, "router": {**CFG["router"], "backend": "hybrid"}})
    # leftovers of the old backend do not stop Trivium from starting
    config.validate({**CFG, "router": {**CFG["router"], "hybrid_laya": ["tools"]},
                     "calibration": {"hybrid": {"kind": 0.6}}})


def test_laya_engine_maps_questions(monkeypatch):
    seen = {}

    class Agent:
        def predict(self, state, questions):
            seen.update(questions)
            return {"answers": {q: {"probabilities": {o: 1 / len(v["criteria"]) for o in v["criteria"]}}
                                for q, v in questions.items()}}

    monkeypatch.setitem(sys.modules, "laya", types.SimpleNamespace(load=lambda *a, **k: Agent()))
    from trivium.laya_engine import LayaEngine

    probs, _ = LayaEngine({}).route({"request": "x"}, CFG["questions"])
    assert seen["kind"]["type"] == "choice" and seen["kind"]["criteria"] == CFG["questions"]["kind"]["options"]
    assert set(probs["tools"]) == {"none", "workspace"}


def test_temper_and_fit():
    sharp = [({"a": 0.99, "b": 0.01}, "a")] * 5 + [({"a": 0.99, "b": 0.01}, "b")] * 5
    t = calibrate.fit(sharp)
    assert t > 1.0  # over-confident scores get softened
    assert calibrate.ece(sharp, t) < calibrate.ece(sharp, 1.0)
    assert policy.temper({"a": 0.5, "b": 0.5}, 3.0) == pytest.approx({"a": 0.5, "b": 0.5})


def test_summarize_applies_temperature():
    raw = {"kind": {"quick_answer": 0.9, "code_change": 0.1}}
    assert policy.summarize(raw, {"kind": 5.0})["kind"]["p"] < 0.9


def test_alternatives_rank_targets():
    answers = {
        "kind": {"probabilities": {"code_change": 0.6, "debugging": 0.4}},
        "difficulty": {"probabilities": {"moderate": 0.7, "hard": 0.3}},
        "tools": {"probabilities": {"workspace": 1.0, "none": 0.0}},
    }
    ranked = policy.alternatives(CFG, answers)
    assert ranked[0][0] == "codex-sol"
    assert sum(p for _, p in ranked) == pytest.approx(1.0)
    assert dict(ranked)["claude-opus"] == pytest.approx(0.4 * 0.3)


def test_service_plist(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/local/bin/ask")
    body = plistlib.loads(service.plist())
    assert body["ProgramArguments"] == ["/usr/local/bin/ask", "serve"]
    assert body["KeepAlive"] == {"SuccessfulExit": False}
    assert body["EnvironmentVariables"]["HF_HUB_OFFLINE"] == "1"


def test_route_cache_is_an_option(monkeypatch, tmp_path):
    from trivium import log

    monkeypatch.setattr(log, "LOG", tmp_path / "decisions.jsonl")
    engine = FakeEngine({"409": QUICK})
    cached = {**CFG, "router": {**CFG["router"], "cache": True}}
    first, _ = cli.route(cached, engine, "what does 409 mean", None, "semif")
    again, _ = cli.route(cached, engine, "what does 409 mean", None, "semif")
    assert len(engine.calls) == 1 and again.answers == first.answers and again.target == first.target
    cli.route(cached, engine, "what does 409 mean", "some-repo", "semif")  # other evidence: not reused
    cli.route(CFG, engine, "what does 409 mean", None, "semif")            # cache off: always asks
    cli.route(CFG, engine, "what does 409 mean", None, "semif")
    assert len(engine.calls) == 4


def test_service_windows_script(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda name: r"C:\bin\ask.exe")
    monkeypatch.setenv("TRIVIUM_CONFIG", r"C:\cfg\targets.yaml")
    lines = service.win_script().split("\r\n")
    assert 'set "HF_HUB_OFFLINE=1"' in lines and r'set "TRIVIUM_CONFIG=C:\cfg\targets.yaml"' in lines
    assert lines[-2].startswith(r'"C:\bin\ask.exe" serve >> "') and lines[-2].endswith('trivium.log" 2>&1')
    # no window: nothing to close or interrupt by accident
    assert service.win_task_command(pathlib.Path("serve.cmd")) == 'conhost.exe --headless cmd /c "serve.cmd"'


def test_resolve_runs_an_npm_shim_without_cmd_exe(tmp_path, monkeypatch):
    """A prompt must never pass through cmd.exe: resolve() starts the shim's node script itself."""
    shim = tmp_path / "codex.cmd"
    shim.write_text(r'"%_prog%"  "%dp0%\node_modules\@openai\codex\bin\codex.js" %*')
    where = {"codex": str(shim), "node": r"C:\node\node.exe", "claude": r"C:\bin\claude.EXE"}
    monkeypatch.setattr(launch, "WINDOWS", True)
    monkeypatch.setattr(launch.shutil, "which", where.get)
    nasty = 'x" & calc'
    assert REAL_RESOLVE(["codex", "-m", "m", nasty]) == [
        r"C:\node\node.exe", str(tmp_path / r"node_modules\@openai\codex\bin\codex.js"), "-m", "m", nasty]
    assert REAL_RESOLVE(["claude", "-p"]) == [r"C:\bin\claude.EXE", "-p"]
    assert REAL_RESOLVE(["missing"]) == ["missing"]
    shim.write_text("@echo something else")
    assert REAL_RESOLVE(["codex"]) == ["codex"]


def test_config_rejects_bad_calibration():
    with pytest.raises(ValueError, match="calibration"):
        config.validate({**CFG, "calibration": {"semif": {"kind": -1}}})
    with pytest.raises(ValueError, match="backend"):
        config.validate({**CFG, "router": {**CFG["router"], "backend": "gpt"}})


class Tty(io.StringIO):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer

    def readline(self):
        return self.answer


def test_pick_offers_likeliest_targets():
    answers = policy.summarize({"kind": {"code_change": 0.6, "debugging": 0.4},
                                "difficulty": {"moderate": 0.7, "hard": 0.3},
                                "tools": {"workspace": 1.0, "none": 0.0}})
    decision = policy.decide(CFG, answers)
    assert cli.pick(CFG, decision, Tty("2\n")) == policy.alternatives(CFG, answers)[1][0]
    assert cli.pick(CFG, decision, Tty("\n")) is None


# --- ask export --------------------------------------------------------------

from trivium import export  # noqa: E402


def answers_for(choices, p=0.8):
    out = {}
    for q, spec in CFG["questions"].items():
        options = list(spec["options"])
        rest = (1 - p) / (len(options) - 1)
        out[q] = {"choice": choices[q], "p": p,
                  "probabilities": {o: (p if o == choices[q] else rest) for o in options}}
    return out


def decision(id_, prompt, choices, target, reason="rule 3", ts=100.0, repo="demo"):
    return {"type": "decision", "id": id_, "ts": ts, "prompt": prompt, "repo": repo,
            "answers": answers_for(choices), "routed": target, "target": target, "reason": reason}


def test_labels_for_target_routes_to_feedback():
    answers = answers_for(CODE)
    labels = export.labels_for_target(CFG, answers, "claude-opus")
    assert policy.decide({**CFG, "min_confidence": {}},
                         {q: {"choice": o, "p": 1.0} for q, o in labels.items()}).target == "claude-opus"
    assert labels["difficulty"] == "hard"  # the cheapest change from the router's own answers


def test_rows_from_log_labels():
    records = [
        decision("a", "add retry", CODE, "codex-sol"),
        {"type": "feedback", "decision": "a", "verdict": "bad", "should": "claude-opus"},
        decision("b", "what is 409", QUICK, "local"),
        {"type": "feedback", "decision": "b", "verdict": "good", "should": None},
        decision("c", "unrated prompt", QUICK, "local"),
        decision("d", "picked one", CODE, "claude-sonnet", reason="picked with --ask"),
        {"type": "decision", "id": "e", "ts": 100.0, "prompt": "manual", "answers": {}, "target": "claude-opus"},
    ]
    rows, skipped = export.rows_from_log(records, CFG)
    by = {r["prompt"]: r for r in rows}
    assert by["add retry"]["label"] == "inferred-from-feedback" and by["add retry"]["expect"]["difficulty"] == "hard"
    assert by["what is 409"]["label"] == "confirmed-target" and not by["what is 409"]["needs_review"]
    assert by["unrated prompt"]["label"] == "router" and by["unrated prompt"]["needs_review"]
    assert skipped["no router answers"] == 1 and "manual" not in by
    rated, skipped = export.rows_from_log(records, CFG, only_rated=True)
    assert {r["prompt"] for r in rated} == {"add retry", "what is 409", "picked one"}
    assert skipped["unrated"] == 1


def test_rows_from_log_dedupes_and_filters_by_day():
    records = [decision("a", "same", QUICK, "local", ts=10.0), decision("b", "same", CODE, "codex-sol", ts=20.0)]
    rows, _ = export.rows_from_log(records, CFG)
    assert len(rows) == 1 and rows[0]["source"]["decision"] == "b"
    rows, skipped = export.rows_from_log(records, CFG, since=15.0)
    assert [r["source"]["decision"] for r in rows] == ["b"] and skipped["before --since"] == 1


def test_cmd_export_writes_eval_file(monkeypatch, tmp_path, capsys):
    log_file = tmp_path / "decisions.jsonl"
    log_file.write_text("\n".join(json.dumps(r) for r in [decision("a", "add retry", CODE, "codex-sol")]))
    monkeypatch.setattr(cli.log, "LOG", log_file)
    out = tmp_path / "mine.jsonl"
    assert cli.cmd_export(["--out", str(out)]) == 0
    row = json.loads(out.read_text())
    assert row["expect"] == CODE and row["needs_review"]
    assert "1 need review" in capsys.readouterr().err


# --- backend mismatch ---------------------------------------------------------

def test_backend_mismatch_loads_in_process(monkeypatch):
    httpd = server.make_server(FakeEngine(), 0, backend="laya")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        cfg = {**CFG, "router": {**CFG["router"], "port": httpd.server_address[1], "backend": "semif"}}
        monkeypatch.setattr(cli, "load_engine", lambda cfg, name: f"in-process {name}")
        assert cli.backend(cfg) == "in-process semif"
        matched = cli.backend({**cfg, "router": {**cfg["router"], "backend": "laya"}})
        assert isinstance(matched, server.Remote) and matched.backend == "laya"
    finally:
        httpd.shutdown()


# --- Laya reads the context first ---------------------------------------------

def test_laya_keeps_the_repo_sentence(monkeypatch):
    seen = {}

    class Agent:
        def predict(self, state, questions):
            seen["keys"] = list(state)
            seen["state"] = state
            return {"answers": {q: {"probabilities": {o: 1 / len(v["criteria"]) for o in v["criteria"]}}
                                for q, v in questions.items()}}

    monkeypatch.setitem(sys.modules, "laya", types.SimpleNamespace(load=lambda *a, **k: Agent()))
    from trivium.laya_engine import LayaEngine

    LayaEngine({}).route({"request": "x" * 5000, "context": "inside repo"}, CFG["questions"])
    assert seen["keys"] == ["request", "context"]  # order kept: context-first cost 9 of 36 tools answers
    assert len(seen["state"]["request"]) < 400 and seen["state"]["context"] == "inside repo"


# --- --json, calibrate --write, eval --sweep -----------------------------------

def test_json_decision(fake_cli, capsys):
    assert cli.run(["--json", "add retry to the client"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["target"] == "codex-sol" and body["model"] == "gpt-6-sol"
    assert body["command"][:3] == ["codex", "-m", "gpt-6-sol"]
    assert body["alternatives"][0][0] == "codex-sol"


def test_calibrate_write_and_load(fake_cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRIVIUM_CALIBRATION", str(tmp_path / "calibration.yaml"))
    rows = [{"prompt": "what does 409 mean", "repo": None, "expect": QUICK}] * 3
    f = tmp_path / "eval.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows))
    assert cli.cmd_calibrate([str(f), "--write"]) == 0
    assert "Saved to" in capsys.readouterr().out
    loaded = config.load(config.config_path())
    assert set(config.temperatures(loaded, "semif")) == set(CFG["questions"])


def test_sweep_trades_fallback_for_precision():
    uncertain = {q: {"choice": c, "p": 0.5, "probabilities": {c: 0.5}} for q, c in CODE.items()}
    confident = {q: {"choice": c, "p": 0.95, "probabilities": {c: 0.95}} for q, c in QUICK.items()}
    scored = [(None, uncertain, "codex-sol", 0.0), (None, confident, "local", 0.0)]
    rows = {floor: (right, fell, precise) for floor, right, fell, precise in cli.sweep(CFG, scored)}
    assert rows[0.0] == (1.0, 0.0, 1.0)
    # From 0.55 the uncertain prompt falls back to claude-sonnet, which is not its label;
    # the confident one (0.95) still routes, and routes right.
    assert rows[0.6] == (0.5, 0.5, 1.0)
    assert rows[0.9] == (0.5, 0.5, 1.0)


# --- runtimes -------------------------------------------------------------------

def test_runtime_config():
    from trivium import engine

    with pytest.raises(ValueError, match="runtime"):
        config.validate({**CFG, "router": {**CFG["router"], "runtime": "tpu"}})
    assert config.answers_locally(CFG)
    assert not config.answers_locally({**CFG, "router": {**CFG["router"], "runtime": "llamacpp"}})
    assert not config.answers_locally({**CFG, "router": {**CFG["router"], "backend": "laya"}})
    assert not config.answers_locally({**CFG, "router": {**CFG["router"], "backend": "systemone"}})
    assert engine.gguf_path({"gguf": "/models/q.gguf"}) == "/models/q.gguf"
    with pytest.raises(ValueError, match="gguf"):
        engine.gguf_path({})


def test_llamacpp_runtime_routes_local_to_claude(fake_cli, monkeypatch, capsys):
    monkeypatch.setattr(cli.config, "answers_locally", lambda cfg: False)
    assert cli.run(["--dry", "what does 409 mean"]) == 0
    assert "claude-haiku" in capsys.readouterr().err


def test_serve_refuses_a_taken_port(monkeypatch, capsys):
    httpd = server.make_server(FakeEngine(source="old"), 0, backend="semif")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    loaded = []
    monkeypatch.setattr(cli.config, "load", lambda: {**CFG, "router": {**CFG["router"], "port": port}})
    monkeypatch.setattr(cli, "load_engine", lambda cfg, name: loaded.append(name))
    try:
        assert cli.cmd_serve([]) == 1
        err = capsys.readouterr().err
        assert "already running" in err and "backend semif" in err and not loaded
        assert not server.port_free(port)
    finally:
        httpd.shutdown()


# --- status page ------------------------------------------------------------------

def test_status_page_escapes_and_counts(running_server, tmp_path, monkeypatch):
    import urllib.request

    from trivium import log

    engine, remote = running_server
    log_file = tmp_path / "decisions.jsonl"
    records = [decision("a", "<script>alert(1)</script> add retry", CODE, "codex-sol"),
               {"type": "feedback", "decision": "a", "verdict": "bad", "should": "claude-opus"}]
    log_file.write_text("\n".join(json.dumps(r) for r in records))
    monkeypatch.setattr(log, "LOG", log_file)
    remote.route({"request": "what is 409", "context": "x"}, CFG["questions"])
    page = urllib.request.urlopen(remote.base + "/status").read().decode()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "1 routed" in page and "codex-sol" in page and "claude-opus" in page
    assert urllib.request.urlopen(remote.base + "/favicon.ico").status == 204


def test_recent_decisions_reads_tail(tmp_path):
    from trivium import status

    f = tmp_path / "log.jsonl"
    f.write_text("\n".join(json.dumps(decision(str(i), f"p{i}", QUICK, "local", ts=i)) for i in range(40)) + "\nnot json")
    recent = status.recent_decisions(f, limit=5)
    assert [d["prompt"] for d in recent] == ["p39", "p38", "p37", "p36", "p35"]
    assert status.recent_decisions(tmp_path / "missing.jsonl") == []


def test_eval_split_filters_rows(fake_cli, tmp_path, capsys):
    rows = [{"prompt": "what does 409 mean", "repo": None, "expect": QUICK, "split": "train"},
            {"prompt": "add retry", "repo": "demo", "expect": CODE, "split": "test"}]
    f = tmp_path / "eval.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows))
    assert cli.cmd_eval([str(f), "--split", "test"]) == 0
    assert capsys.readouterr().out.startswith("1 prompts (test)")
    with pytest.raises(SystemExit):
        cli.cmd_eval([str(f), "--split", "holdout"])


# --- correction model -------------------------------------------------------------

def _scores(difficulty_p):
    """Router scores that always lean to "trivial", with the given score for "moderate"."""
    return {"kind": {o: 1 / 6 for o in CFG["questions"]["kind"]["options"]},
            "difficulty": {"trivial": 0.9 - difficulty_p, "moderate": difficulty_p, "hard": 0.1},
            "tools": {"none": 0.2, "workspace": 0.8}}


def test_correction_learns_what_the_router_gets_wrong():
    from trivium import correct

    # The router says "trivial" every time; the labels say "moderate" whenever moderate scores 0.3 or more.
    samples = [(_scores(p), {"kind": "code_change", "difficulty": "moderate" if p >= 0.3 else "trivial",
                             "tools": "workspace"}) for p in (0.05, 0.1, 0.15, 0.2, 0.3, 0.35, 0.4, 0.44) * 3]
    model = correct.fit(samples, CFG["questions"])
    fixed = correct.apply(model, _scores(0.4))
    assert max(_scores(0.4)["difficulty"], key=_scores(0.4)["difficulty"].get) == "trivial"
    assert max(fixed["difficulty"], key=fixed["difficulty"].get) == "moderate"
    low = correct.apply(model, _scores(0.05))
    assert max(low["difficulty"], key=low["difficulty"].get) == "trivial"
    assert abs(sum(fixed["kind"].values()) - 1) < 1e-9
    assert fixed["difficulty"]["hard"] == 0.0  # never labelled, so never chosen


def test_correct_writes_a_model_and_route_uses_it(fake_cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TRIVIUM_CORRECTION", str(tmp_path / "correction.json"))
    rows = [{"prompt": f"p{i}", "split": "test" if i % 4 == 0 else None, "probs": _scores(p),
             "expect": {"kind": "code_change", "difficulty": "moderate" if p >= 0.3 else "trivial",
                        "tools": "workspace"}}
            for i, p in enumerate((0.05, 0.1, 0.15, 0.2, 0.3, 0.35, 0.4, 0.44) * 3)]
    f = tmp_path / "scores.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows))
    engine, _ = fake_cli
    assert cli.cmd_correct([str(f), "--write"]) == 0
    out = capsys.readouterr().out
    assert "fitted on 18 prompts" in out and "on the 6 prompts" in out and "Saved to" in out
    assert engine.calls == []  # rows that carry scores are not routed again

    off = config.load(config.config_path())
    assert config.correction(off, "semif") is None  # ships off
    on = {**off, "router": {**off["router"], "correction": True}}
    assert cli.answers_for(on, "semif", _scores(0.4))["difficulty"]["choice"] == "moderate"
    assert cli.answers_for(off, "semif", _scores(0.4))["difficulty"]["choice"] == "trivial"
    decision, _ = cli.route(on, engine, "what does 409 mean", None, "semif")
    assert set(decision.scores) == set(CFG["questions"])  # the raw scores stay available for the log
    with pytest.raises(ValueError, match="no model for the laya router"):
        config.correction(on, "laya")
    other = {**on, "questions": {**on["questions"], "tools": {"question": "?", "options": {"a": "a", "b": "b"}}}}
    with pytest.raises(ValueError, match="other questions"):
        config.correction(other, "semif")


def test_export_keeps_the_raw_scores():
    record = {**decision("a", "add retry", CODE, "codex-sol"), "scores": {"kind": {"code_change": 1.0}}}
    rows, _ = export.rows_from_log([record], CFG)
    assert rows[0]["probs"] == {"kind": {"code_change": 1.0}}


# --- System One backend -------------------------------------------------------------

def test_systemone_engine_asks_the_server_and_maps_the_answers():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from trivium.systemone_engine import SystemOneEngine

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            answers = {q: {"probabilities": {o: (0.7 if i == 1 else 0.3 / (len(spec["criteria"]) - 1))
                                             for i, o in enumerate(spec["criteria"])}}
                       for q, spec in seen["body"]["questions"].items()}
            payload = json.dumps({"answers": answers} if self.path == "/v1/systemone" else {"answers": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        engine = cli.load_engine({"router": {"systemone_url": base + "/v1/systemone"}}, "systemone")
        probs, timing = engine.route({"request": "add retry"}, CFG["questions"])
        assert seen["body"]["state"] == {"request": "add retry"}
        assert seen["body"]["questions"]["tools"] == {
            "type": "choice", "instructions": CFG["questions"]["tools"]["question"],
            "criteria": CFG["questions"]["tools"]["options"]}
        assert max(probs["kind"], key=probs["kind"].get) == "code_change" and timing["total_seconds"] >= 0
        with pytest.raises(RuntimeError, match="left out an answer"):
            SystemOneEngine({"systemone_url": base + "/other"}).route({"request": "x"}, CFG["questions"])
    finally:
        httpd.shutdown()
        httpd.server_close()
    with pytest.raises(RuntimeError, match="did not answer"):
        engine.route({"request": "x"}, CFG["questions"])  # the server is gone
    # A router that is down does not block the prompt: it goes to the fallback, with the reason.
    decision, _ = cli.route(CFG, engine, "add retry", None, "systemone")
    assert decision.target == CFG["fallback"] and decision.reason.startswith("router failed")
    with pytest.raises(ValueError, match="systemone_url"):
        SystemOneEngine({"systemone_url": "file:///etc/passwd"})
    with pytest.raises(RuntimeError, match="only decides"):
        engine.generate("hi")
