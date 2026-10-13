"""DIGESTFALLBACK-01: input identity never falls back silently, and git never answers about
another repository.

P1 - every outcome of identifying an input, on BOTH copies (the engine's
     ``src.am.run_period._input_digest`` and the golden harness's ``input_digest``).
P2 - the lane-hook environment (GIT_DIR at another repository, an absolute GIT_INDEX_FILE, no
     GIT_WORK_TREE) no longer reaches a repository git call.
P3 - a repository git call added without ``env=git_env()`` reds this file, naming file:line.

Shells out to git by design: the property is what git answers under a given environment and
folder layout, so a stub would test something else. Exemption and timing in ``conftest.py``.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import src.am._provenance as prov
import src.am.run_period as rp
import tests.golden.golden_harness as gh
from src.git_identity import GitIdentityError, git_env

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACKED = REPO_ROOT / "tests" / "fixtures" / "synthetic_wind" / "wind_schedule.xer"

COPIES = {"engine": rp._input_digest, "harness": gh.input_digest}


@pytest.fixture(params=sorted(COPIES))
def digest(request):
    return COPIES[request.param]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=git_env()).stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    (root / "tracked.txt").write_bytes(b"tracked\n")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "c")
    return root


def _no_dot_git_above(folder: Path) -> bool:
    return not any((d / ".git").exists() for d in (folder, *folder.parents))


# ---------------------------------------------------------------------------
# P1 positive controls: what was recorded before is still recorded
# ---------------------------------------------------------------------------


def test_a_tracked_input_is_still_a_blob_oid(digest) -> None:
    entry = digest(TRACKED)
    assert entry == {"method": "git_blob_oid",
                     "value": _git(REPO_ROOT, "hash-object", "--", str(TRACKED))}


def test_an_untracked_input_inside_a_repository_is_still_a_plain_byte_hash(digest, tmp_path) -> None:
    repo = _repo(tmp_path / "repo")
    path = repo / "untracked.txt"
    path.write_bytes(b"untracked\n")
    assert digest(path) == {"method": "sha256_bytes", "value": gh.sha256_file(path)}


def test_an_input_outside_any_repository_is_still_a_plain_byte_hash(digest, tmp_path) -> None:
    path = tmp_path / "loose" / "register.xlsx"
    path.parent.mkdir()
    path.write_bytes(b"not in any repository\n")
    assert _no_dot_git_above(path.parent), "premise: nothing above tmp_path is a repository"
    assert digest(path) == {"method": "sha256_bytes", "value": gh.sha256_file(path)}


# ---------------------------------------------------------------------------
# P1 the failures that used to be recorded as "untracked"
# ---------------------------------------------------------------------------


def test_a_dot_git_that_git_refuses_raises_naming_the_failure(digest, tmp_path) -> None:
    """A corrupt repository: a ``.git`` git will not accept. ls-files exits 128 exactly as it
    does outside any repository; the ``.git`` above the input is what tells them apart."""
    folder = tmp_path / "corrupt"
    (folder / ".git").mkdir(parents=True)
    path = folder / "register.xlsx"
    path.write_bytes(b"x\n")
    with pytest.raises(GitIdentityError, match=r"ls-files .* exited 128 .*register\.xlsx"):
        digest(path)


def test_a_repository_variable_that_survives_raises(digest, monkeypatch) -> None:
    """Defence in depth behind P2: if a GIT_DIR ever reaches the call anyway, git reports 128
    inside a repository, and that raises rather than recording a tracked input as untracked."""
    real_run = subprocess.run

    def survive(args, *a, **k):
        if args and args[0] == "git":
            k["env"] = dict(k.get("env") or os.environ, GIT_DIR=str(REPO_ROOT / "no-such-gitdir"))
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", survive)
    with pytest.raises(GitIdentityError, match=r"exited 128 .*wind_schedule\.xer"):
        digest(TRACKED)


def test_a_git_call_that_hangs_raises_rather_than_hanging(digest, monkeypatch) -> None:
    real_run = subprocess.run

    def hang(args, *a, **k):
        if args and args[0] == "git" and "--local-env-vars" not in args:
            if k.get("timeout") is None:
                pytest.fail(f"{args[:4]} carries no timeout: a hung git hangs the run")
            raise subprocess.TimeoutExpired(args, k["timeout"])
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(GitIdentityError, match=r"ls-files .* timed out .*wind_schedule\.xer"):
        digest(TRACKED)


def test_git_not_installed_is_a_byte_hash_marked_git_unavailable(digest, monkeypatch, tmp_path) -> None:
    """Measured: a child env without PATH still finds git on Windows (CreateProcess searches
    the PARENT's PATH), so the parent's own PATH is emptied."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(OSError):
        subprocess.run(["git", "--version"], capture_output=True, env=git_env())
    assert digest(TRACKED) == {"method": "sha256_bytes", "value": gh.sha256_file(TRACKED),
                               "git": "unavailable"}


# ---------------------------------------------------------------------------
# P2 the lane-hook environment reaches no repository git call
# ---------------------------------------------------------------------------


@pytest.fixture
def lane_hook_env(tmp_path, monkeypatch) -> str:
    """GIT_DIR at another repository, an absolute GIT_INDEX_FILE, no GIT_WORK_TREE: what git
    exports to a hook in a linked worktree. Returns the other repository's HEAD."""
    other = _repo(tmp_path / "other")
    other_head = _git(other, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    return other_head


def test_engine_sha_is_this_repositorys_under_a_hook_environment(lane_hook_env) -> None:
    ours = _git(REPO_ROOT, "rev-parse", "HEAD")
    assert ours != lane_hook_env, "premise: the two repositories differ"
    assert prov.resolve_engine_sha() == ours


def test_tree_status_reads_this_tree_under_a_hook_environment(lane_hook_env) -> None:
    """Compared as the porcelain text, not the bool: a dirty tree would make the bool agree
    whichever index git read."""
    ours = _git(REPO_ROOT, "status", "--porcelain", "--untracked-files=normal")
    assert prov._git("status", "--porcelain", "--untracked-files=normal") == ours
    assert prov.resolve_tree_dirty() == bool(ours)


def test_a_tracked_input_is_a_blob_oid_under_a_hook_environment(digest, lane_hook_env) -> None:
    assert digest(TRACKED)["method"] == "git_blob_oid"


def test_the_showcase_stamps_this_repository_under_a_hook_environment(lane_hook_env) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_wind_showcase as ws
    assert ws._resolve_engine_sha() == _git(REPO_ROOT, "rev-parse", "HEAD")
    assert ws._resolve_tree_dirty() == bool(_git(REPO_ROOT, "status", "--porcelain"))


def test_the_client_gate_lists_this_tree_under_a_hook_environment(lane_hook_env) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import client_gate
    expected = _git(REPO_ROOT, "ls-files", "-z", "--cached", "--others",
                    "--exclude-per-directory=.gitignore")
    assert client_gate._git_visible(REPO_ROOT) == [REPO_ROOT / p for p in expected.split("\0") if p]


# ---------------------------------------------------------------------------
# P3 the class stays closed
# ---------------------------------------------------------------------------

_SHELLOUT = frozenset({"run", "Popen", "call", "check_call", "check_output"})
_SCANNED = ("src", "scripts", "tools", "tests")


def _callee(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _uses_git_env(expr: ast.expr) -> bool:
    return any(isinstance(n, ast.Call) and (_callee(n.func) or "").endswith("git_env")
               for n in ast.walk(expr))


def unclean_git_calls(root: Path) -> list[str]:
    """Every ``subprocess.<run|Popen|call|check_call|check_output>(["git", ...])`` under
    src/, scripts/, tools/ and tests/ whose ``env=`` does not call a ``*git_env`` function.

    Blind spots, by construction of an AST scan:

    - an argv not written as a literal list or tuple starting ``"git"`` (built in a variable,
      a shell string, ``os.system``, a git library) is not seen;
    - the env is trusted by the NAME of the function it calls: anything ending ``git_env``
      passes, whatever it returns;
    - a wrapper taking ``env`` from its caller is flagged even when every caller is clean.
      That is the loud direction;
    - folders outside the four, the agent hooks among them, are not scanned.
    """
    found = []
    for top in _SCANNED:
        for f in sorted((root / top).rglob("*.py")):
            nodes = [n for n in ast.walk(ast.parse(f.read_bytes(), filename=str(f)))
                     if isinstance(n, ast.Call)]
            for node in sorted(nodes, key=lambda n: n.lineno):
                if not (isinstance(node, ast.Call) and _callee(node.func) in _SHELLOUT
                        and node.args):
                    continue
                argv = node.args[0]
                if not (isinstance(argv, (ast.List, ast.Tuple)) and argv.elts
                        and isinstance(argv.elts[0], ast.Constant) and argv.elts[0].value == "git"):
                    continue
                env = next((k.value for k in node.keywords if k.arg == "env"), None)
                if env is None or not _uses_git_env(env):
                    found.append(f"{f.relative_to(root).as_posix()}:{node.lineno}")
    return found


def test_every_repository_git_call_runs_in_the_clean_environment() -> None:
    found = unclean_git_calls(REPO_ROOT)
    assert not found, ("git calls without env=git_env(), which inherit GIT_DIR and can answer "
                       "about another repository:\n  " + "\n  ".join(found))


def test_the_guard_reds_on_a_planted_call_in_src_and_in_scripts(tmp_path) -> None:
    for top, body in (("src", 'subprocess.run(["git", "rev-parse", "HEAD"])\n'),
                      ("scripts", 'sp.check_output(("git", "status"), cwd=".")\n'),
                      ("tests", 'subprocess.run(["git", "status"], env=git_env())\n'),
                      ("tools", 'subprocess.run(["git", "status"], env=dict(_git_env(), X="1"))\n')):
        (tmp_path / top).mkdir()
        (tmp_path / top / "planted.py").write_text(body, encoding="utf-8")
    assert unclean_git_calls(tmp_path) == ["src/planted.py:1", "scripts/planted.py:1"]
