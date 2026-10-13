"""RIDGELINE-01 round 5, item 1: RUN_FINAL.bat's run token is this run's, or the run stops.

**What this measures.** The block between ``REM ---- run token (begin)`` and ``(end)`` in
``RUN_FINAL.bat``, copied verbatim into a scratch batch file and run by ``cmd.exe`` - with a stub
``powershell.bat`` in the scratch folder, put first on ``PATH`` so ``cmd`` finds it before the real
PowerShell. The stub prints a given line, or nothing, standing in for
PowerShell succeeding or being blocked (Bitdefender blocks PowerShell spawns on the build machine).
It does NOT run the rest of the batch or the real PowerShell.

Why it matters (gate 3 round 4, breaker WARN): the gate finds this run's manifest by the token. A
token inherited from the calling shell, or no token at all, let a run be judged on an earlier run's
manifest - a day-B crash or FAIL reported as day A's PASS, exit 0.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(sys.platform != "win32", reason="RUN_FINAL.bat is a Windows batch file"),
]

REPO = Path(__file__).resolve().parents[1]
BEGIN, END = "REM ---- run token (begin)", "REM ---- run token (end)"
GUID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def token_block() -> str:
    text = (REPO / "RUN_FINAL.bat").read_text(encoding="utf-8")
    i = text.index(BEGIN)
    return text[i:text.index(END, i) + len(END)]


def run_block(block: str, tmp_path: Path, *, stub_prints: str | None,
              inherited: str | None) -> tuple[int, str]:
    """Run ``block`` under cmd with PowerShell stubbed; return (exit code, token it left)."""
    (tmp_path / "powershell.bat").write_text(
        "@echo off\n" + (f"echo {stub_prints}\n" if stub_prints else ""), encoding="utf-8")
    probe = tmp_path / "probe.bat"
    probe.write_text("@echo off\nsetlocal enabledelayedexpansion\n" + block
                     + "\necho TOKEN=[%QRA_RUN_TOKEN%]\nexit /b 0\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("QRA_RUN_TOKEN", "NODEFAULTCURRENTDIRECTORYINEXEPATH")}
    # The stub's folder first on PATH too: the `for /f` runs its command in a child cmd, which
    # does not always search the current directory first.
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"
    if inherited is not None:
        env["QRA_RUN_TOKEN"] = inherited
    r = subprocess.run(["cmd", "/c", str(probe)], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=60)
    token = r.stdout.split("TOKEN=[", 1)[1].split("]", 1)[0] if "TOKEN=[" in r.stdout else None
    return r.returncode, token


def test_a_generated_token_is_used_and_an_inherited_one_is_not(tmp_path):
    rc, token = run_block(token_block(), tmp_path, stub_prints=GUID, inherited="stale-token")
    assert (rc, token) == (0, GUID)


def test_no_token_stops_the_run(tmp_path):
    rc, token = run_block(token_block(), tmp_path, stub_prints=None, inherited=None)
    assert rc == 2 and token is None, (rc, token)


def test_an_inherited_token_does_not_survive_a_failed_generation(tmp_path):
    rc, token = run_block(token_block(), tmp_path, stub_prints=None, inherited="stale-token")
    assert rc == 2 and token is None, f"the run went on with {token!r}"
