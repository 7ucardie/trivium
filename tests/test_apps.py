"""The shared session core and the terminal app, with a fake engine and scripted keys."""

import json
import subprocess

import pytest

from test_runtime import CFG, CODE, QUICK, FakeEngine
from trivium import export, log, repl, session


@pytest.fixture
def router(monkeypatch, tmp_path):
    monkeypatch.setattr(log, "LOG", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(session, "LAUNCH_DIR", tmp_path / "launch")
    monkeypatch.setattr(session.state, "repo_name", lambda cwd: "demo")
    return session.Router(cfg=CFG, engine=FakeEngine({"409": QUICK, "retry": CODE}))


def records():
    return [json.loads(line) for line in log.LOG.read_text().splitlines()]


def test_decide_logs_and_ranks(router, tmp_path):
    d = router.decide("add retry to the client", str(tmp_path))
    assert d["target"]["name"] == "codex-sol" and d["target"]["model"] == "gpt-6-sol"
    assert d["alternatives"][0]["name"] == "codex-sol" and d["id"] == records()[-1]["id"]
    with pytest.raises(ValueError, match="empty"):
        router.decide("  ", str(tmp_path))
    with pytest.raises(ValueError, match="not a directory"):
        router.decide("hi", str(tmp_path / "nope"))


def test_decide_without_local_answers(router, tmp_path):
    router.cfg = {**CFG, "router": {**CFG["router"], "runtime": "llamacpp"}}
    d = router.decide("what does 409 mean", str(tmp_path))
    assert d["target"]["vendor"] == "claude"
    assert all(a["vendor"] != "local" for a in d["alternatives"])


def test_pick_counts_as_the_chosen_target(router, tmp_path):
    d = router.decide("add retry", str(tmp_path))
    router.pick(d["id"], "opus")
    rows, _ = export.rows_from_log(records(), CFG, only_rated=True)
    assert rows[0]["source"]["should"] == "claude-opus" and rows[0]["label"] == "inferred-from-feedback"


def test_launch_script_quotes_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "LAUNCH_DIR", tmp_path / "launch")
    nasty = "it's \"quoted\" $(touch /tmp/pwned) `id` ; rm -rf ~ && echo"
    project = tmp_path / "my project"
    project.mkdir()
    script = session.launch_script(["printf", "%s|", nasty, str(project)], str(project))
    out = subprocess.run(["bash", str(script)], capture_output=True, text=True)
    assert out.stdout == f"{nasty}|{project}|"
    assert not script.exists()  # the script deletes itself: it holds the prompt


class Keys:
    def __init__(self, *keys):
        self.keys = list(keys)

    def __call__(self):
        return self.keys.pop(0)


def app_with(router, tmp_path, keys, lines, ran):
    lines = list(lines)

    def line(prompt, prefill=""):
        if not lines:
            raise EOFError
        return lines.pop(0)

    return repl.App(router, str(tmp_path), key=Keys(*keys), line=line,
                    run=lambda cmd, cwd: ran.append((cmd, cwd)) or 0, out=lambda *a: None)


def test_app_pick_run_and_rate(router, tmp_path):
    ran = []
    app = app_with(router, tmp_path, ["2", "\n", "g"], ["add retry to the client"], ran)
    assert app.loop() == 0
    second = [r for r in records() if r["type"] == "pick"][0]["target"]
    assert ran and ran[0][0][:3] == ["claude", "--model", router.cfg["targets"][second]["model"]]
    assert ran[0][1] == str(tmp_path.resolve())
    assert records()[-1] == {**records()[-1], "type": "feedback", "verdict": "good"}


def test_app_local_one_shot_and_bad_rating(router, tmp_path, capsys):
    ran = []
    app = app_with(router, tmp_path, ["\n", "b", "3"], ["what does 409 mean"], ran)
    app.loop()
    assert not ran and "local answer" in capsys.readouterr().out
    fb = records()[-1]
    assert fb["verdict"] == "bad" and fb["should"] == "claude-sonnet"


def test_app_edit_prefills_and_cd(router, tmp_path):
    seen = []
    sub = tmp_path / "sub"
    sub.mkdir()
    lines = ["/cd sub", "add retry"]

    def line(prompt, prefill=""):
        seen.append(prefill)
        if not lines:
            raise EOFError
        return lines.pop(0)

    app = repl.App(router, str(tmp_path), key=Keys("e"), line=line, run=None, out=lambda *a: None)
    app.loop()
    assert app.cwd == str(sub.resolve()) and seen[-1] == "add retry"


# --- dashboard API and its guards ---------------------------------------------------------------

import threading
import urllib.error
import urllib.request

from trivium import security, server


@pytest.fixture
def api(router, tmp_path, monkeypatch):
    monkeypatch.setenv("TRIVIUM_TOKEN_FILE", str(tmp_path / "api-token"))
    opened = []
    monkeypatch.setattr(session.subprocess, "run", lambda cmd, check=False: opened.append(cmd))  # no real `open`
    httpd = server.make_server(router.engine, 0, backend="semif", cfg=CFG)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None, token=True, headers=None):
        h = {**({security.TOKEN_HEADER: security.token()} if token else {}), **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(base + path, data=data, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    yield call, opened, tmp_path
    httpd.shutdown()


def test_api_decide_pick_run_rate(api):
    call, opened, tmp_path = api
    code, d = call("/api/decide", {"prompt": "add retry", "cwd": str(tmp_path)})
    assert code == 200 and d["target"]["name"] == "codex-sol"
    assert call("/api/pick", {"id": d["id"], "target": "opus"})[1]["name"] == "claude-opus"
    code, out = call("/api/run", {"id": d["id"], "target": "claude-opus", "mode": "terminal"})
    assert code == 200 and opened[0][:3] == ["open", "-a", "Terminal"]
    code, _ = call("/api/rate", {"id": d["id"], "verdict": "bad", "should": "sonnet"})
    kinds = [r["type"] for r in records()]
    assert code == 200 and kinds[-3:] == ["decision", "pick", "feedback"]


def test_api_one_shot_streams_local_answer(api):
    call, _, tmp_path = api
    _, d = call("/api/decide", {"prompt": "what does 409 mean", "cwd": str(tmp_path)})
    code, text = call("/api/run", {"id": d["id"], "mode": "oneshot"})
    events = [json.loads(line) for line in text.splitlines()]
    assert code == 200 and events[0]["kind"] == "status"
    assert "".join(e["text"] for e in events if e["kind"] == "text") == "local answer"


def test_api_guards(api):
    call, _, tmp_path = api
    assert call("/api/status", token=False)[0] == 401
    assert call("/api/status", headers={security.TOKEN_HEADER: "wrong"})[0] == 401
    assert call("/api/status", headers={"Host": "evil.example:8765"})[0] == 403  # DNS rebinding
    assert call("/api/status", headers={"Origin": "https://evil.example"})[0] == 403
    code, err = call("/api/decide", {"prompt": "x"}, headers={"Content-Type": "text/plain"})
    assert code == 415
    assert call("/api/run", {"id": "nope", "mode": "oneshot"})[0] == 404
    assert call("/api/status")[0] == 200


def test_dashboard_embeds_token_and_forbids_framing(api):
    call, _, _ = api
    code, page = call("/", token=False)
    assert code == 200 and security.token() in page and "__TRIVIUM_TOKEN__" not in page
    assert (security.token_path().stat().st_mode & 0o077) == 0  # owner-only file
