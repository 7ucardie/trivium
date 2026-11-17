"""Run `ask serve` at login, so the router is always warm: launchd on macOS, a scheduled task on Windows."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.github.7ucardie.trivium"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "trivium.log"


def program() -> list[str]:
    ask = shutil.which("ask") or str(Path(sys.argv[0]).resolve())
    return [ask, "serve"]


def plist(env: dict | None = None) -> bytes:
    body = {
        "Label": LABEL,
        "ProgramArguments": program(),
        "RunAtLoad": True,
        # Restart after a crash, not after a clean `launchctl bootout`.
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
        "EnvironmentVariables": {
            # The model is cached after the first run; skip the network check at every login.
            "HF_HUB_OFFLINE": "1",
            "USE_TF": "0",
            **({"TRIVIUM_CONFIG": os.environ["TRIVIUM_CONFIG"]} if "TRIVIUM_CONFIG" in os.environ else {}),
            **(env or {}),
        },
    }
    return plistlib.dumps(body)


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install() -> int:
    if os.name == "nt":
        return _win_install()
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LABEL}")  # replace an older install, ignore "not loaded"
    PLIST.write_bytes(plist())
    result = _launchctl("bootstrap", domain, str(PLIST))
    if result.returncode != 0:
        print(f"trivium: launchctl bootstrap failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"trivium: installed {PLIST}\n  runs: {' '.join(program())}\n  log:  {LOG}", file=sys.stderr)
    return 0


def uninstall() -> int:
    if os.name == "nt":
        return _win_uninstall()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if PLIST.exists():
        PLIST.unlink()
    print(f"trivium: removed {PLIST}", file=sys.stderr)
    return 0


def status() -> int:
    if os.name == "nt":
        return _win_status()
    result = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    if result.returncode != 0:
        print("trivium: service not installed (ask service install)", file=sys.stderr)
        return 1
    state = next((line.strip() for line in result.stdout.splitlines() if line.strip().startswith("state =")), "")
    print(f"trivium: {LABEL} {state}\n  plist: {PLIST}\n  log:   {LOG}", file=sys.stderr)
    return 0


# --- Windows: a task that starts at logon -------------------------------------------------------

TASK = "Trivium"
WIN_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "trivium"


def win_script() -> str:
    """serve.cmd: the environment, the command and the log, in one file the task can start."""
    env = {"HF_HUB_OFFLINE": "1", "USE_TF": "0", "PYTHONUTF8": "1",
           **({"TRIVIUM_CONFIG": os.environ["TRIVIUM_CONFIG"]} if "TRIVIUM_CONFIG" in os.environ else {})}
    ask, *args = program()
    return "\r\n".join(["@echo off", *(f'set "{k}={v}"' for k, v in env.items()),
                        f'"{ask}" {" ".join(args)} >> "{WIN_DIR / "trivium.log"}" 2>&1', ""])


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True)


def _win_stop() -> None:
    """End the running server, found by its port, and only if it answers as Trivium."""
    from . import config
    from .server import Remote

    port = config.load()["router"]["port"]
    if not Remote(port).alive():
        return
    pid = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen).OwningProcess | Select-Object -First 1"],
        capture_output=True, text=True).stdout.strip()
    if pid.isdigit():
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        import time

        from .server import port_free

        for _ in range(50):  # `ask serve` refuses to start while the port is still closing
            if port_free(port):
                break
            time.sleep(0.1)


def _win_install() -> int:
    WIN_DIR.mkdir(parents=True, exist_ok=True)
    script = WIN_DIR / "serve.cmd"
    script.write_text(win_script(), newline="")
    _win_stop()
    # A minimised window: a task that runs without one needs the account's password.
    result = _schtasks("/Create", "/F", "/TN", TASK, "/SC", "ONLOGON",
                       "/TR", f'cmd /c start "trivium" /min cmd /c "{script}"')
    if result.returncode != 0:
        print(f"trivium: schtasks failed: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
        return 1
    _schtasks("/Run", "/TN", TASK)
    print(f"trivium: installed the task {TASK}\n  runs: {script}\n  log:  {WIN_DIR / 'trivium.log'}",
          file=sys.stderr)
    return 0


def _win_uninstall() -> int:
    _schtasks("/Delete", "/F", "/TN", TASK)
    _win_stop()
    print(f"trivium: removed the task {TASK}", file=sys.stderr)
    return 0


def _win_status() -> int:
    if _schtasks("/Query", "/TN", TASK).returncode != 0:
        print("trivium: service not installed (ask service install)", file=sys.stderr)
        return 1
    from . import config
    from .server import Remote

    port = config.load()["router"]["port"]
    state = f"running on port {port}" if Remote(port).alive() else "not running"
    print(f"trivium: task {TASK}, {state}\n  script: {WIN_DIR / 'serve.cmd'}\n  log:    {WIN_DIR / 'trivium.log'}",
          file=sys.stderr)
    return 0
