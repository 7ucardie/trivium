"""Run `ask serve` at login with launchd, so the router is always warm."""

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
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if PLIST.exists():
        PLIST.unlink()
    print(f"trivium: removed {PLIST}", file=sys.stderr)
    return 0


def status() -> int:
    result = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    if result.returncode != 0:
        print("trivium: service not installed (ask service install)", file=sys.stderr)
        return 1
    state = next((line.strip() for line in result.stdout.splitlines() if line.strip().startswith("state =")), "")
    print(f"trivium: {LABEL} {state}\n  plist: {PLIST}\n  log:   {LOG}", file=sys.stderr)
    return 0
