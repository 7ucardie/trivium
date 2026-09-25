"""Never let a test start a real claude, codex or open. One did once: a one-shot test ran
`codex exec` against this repo and it patched two files. Tests that need those commands fake them."""

import subprocess

import pytest

REAL = {"Popen": subprocess.Popen, "run": subprocess.run}
FORBIDDEN = {"claude", "codex", "open"}


def _guard(name):
    real = REAL[name]

    def guarded(cmd, *args, **kwargs):
        program = (cmd[0] if isinstance(cmd, (list, tuple)) else str(cmd).split()[0]).rsplit("/", 1)[-1]
        if program in FORBIDDEN:
            raise AssertionError(f"test tried to start a real `{program}`: fake it instead")
        return real(cmd, *args, **kwargs)

    return guarded


@pytest.fixture(autouse=True)
def no_real_agent_clis(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _guard("Popen"))
    monkeypatch.setattr(subprocess, "run", _guard("run"))
    import os

    real_exec = os.execvp

    def guarded_exec(file, argv):
        if file.rsplit("/", 1)[-1] in FORBIDDEN:
            raise AssertionError(f"test tried to exec a real `{file}`: fake it instead")
        return real_exec(file, argv)

    monkeypatch.setattr(os, "execvp", guarded_exec)


class FakeProc:
    """Stands in for subprocess.Popen: replays recorded stdout lines, then exits with `code`."""

    def __init__(self, lines, code=0):
        self.stdout, self._code = iter(lines), code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def wait(self):
        return self._code
