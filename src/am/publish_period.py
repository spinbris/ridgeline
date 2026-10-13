"""Stage 7 part D (B-1): publish a period to the dashboard, in one command.

**What this replaces.** Until now, getting a period in front of a client was four manual steps in
the right order: produce the JSON, drop it beside the codebase, `npm run build`, then
`vercel build` and `vercel deploy --prebuilt`. It worked because the operator *was*
the specialist who built it. D-8 ruled that operating a client's instance is **product**, and
§5.1 ruled the shape: keep the static export, add a path a project manager can drive.

**What it deliberately does not do.** §5.1's scope ruling is that the client *publishes and views*
while a specialist still *produces* - producing a period needs the Python engine and the status
workbook, and no receive path changes that. So this takes a period JSON that already exists and
carries it the rest of the way. It is not a wrapper around `run_period`.

**Every precondition is checked and named, never defaulted.** The 3c deliverable runner learned
this the hard way: a runner that supplies a plausible default for something the operator did not
set will publish the wrong thing quietly. Each check below says what is wrong and what to do.

**The deploy step is opt-in, and that is a statement about evidence rather than caution.**
Everything up to and including the build is verifiable on this machine and is verified. The
`vercel` calls are not - there is no Vercel project reachable from here - so `--deploy` is
required to run them, and without it the command prints the exact sequence it would have run -
the clear, `vercel build`, the build-output guard, `vercel deploy --prebuilt` (``deploy_steps``).
A tool that claims to have deployed when nobody has watched it deploy is worse than one that
hands you four lines to run.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPO_ROOT / "dashboard"
DATA_ROOT = REPO_ROOT / "data"

#: The contract this app build understands. Read from the engine rather than retyped, so a
#: publish cannot silently accept a version the app will refuse at load.
from src.am.json_writer import SCHEMA_VERSION  # noqa: E402

#: Top-level blocks every period JSON carries. A file missing one of these is not a period.
REQUIRED_BLOCKS = (
    "schema_version", "meta", "headline", "trend", "risks",
    "mitigations", "activities", "distribution", "delta", "audit",
)


class PublishError(Exception):
    """A precondition failed. The message says what to do about it."""


@dataclass(frozen=True)
class PublishPlan:
    """What a publish would do, resolved before anything is written."""

    source: Path
    project: str
    destination: Path
    period_end: str
    replaces_existing: bool
    already_in_place: bool


def _fail(message: str) -> "PublishError":
    return PublishError(message)


def validate_period_json(source: Path) -> dict:
    """Read and check the period JSON, before anything is copied anywhere.

    Validated HERE rather than left to the app, because the app validates after deployment - by
    which point a bad period is already in front of the client. The same reasoning as the
    register contract's Validate button: catch it on the operator's machine.
    """
    if not source.is_file():
        raise _fail(f"no such file: {source}")

    try:
        doc = json.loads(source.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(f"{source.name} is not readable JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise _fail(f"{source.name} is not a JSON object, so it is not a period document")

    missing = [b for b in REQUIRED_BLOCKS if b not in doc]
    if missing:
        raise _fail(
            f"{source.name} is missing top-level block(s) {', '.join(missing)}. This does not "
            f"look like a period JSON produced by the engine.")

    declared = doc["schema_version"]
    if declared != SCHEMA_VERSION:
        raise _fail(
            f"{source.name} declares period-JSON contract {declared!r}, but this build publishes "
            f"{SCHEMA_VERSION!r}. The engine and the app must be deployed in step: re-run the "
            f"period on an engine at {SCHEMA_VERSION!r}, or check out the app that matches "
            f"{declared!r}. Publishing it would deploy a dashboard that refuses its own data.")

    period_end = doc.get("meta", {}).get("period_end_date")
    if not period_end:
        raise _fail(f"{source.name} carries no meta.period_end_date, so it cannot be filed")

    return doc


def refuse_unpublishable(project: str) -> None:
    """DASHGATE-01 P3 (RELEASE-01 D-5 as amended): nothing is filed for a project that may not
    be published. Asked of the binding, through the one answer ``is_publishable`` - never of a
    project's name. Raised before anything is written, so `data/` is untouched."""
    from src.sra.cpm.bindings import get_binding, is_publishable

    try:
        binding = get_binding(project)
    except KeyError:
        raise _fail(
            f"project {project!r} has no project binding, so it cannot be named for publication. "
            f"Nothing was filed.") from None
    if is_publishable(binding):
        return
    why = ("it is confidential" if binding.confidential
           else "it is not named for publication (its binding does not set publish=True)")
    raise _fail(f"project {project!r} may not be published: {why}. Nothing was filed.")


def resolve_plan(source: Path, project: str | None, data_root: Path = DATA_ROOT) -> PublishPlan:
    """Decide where the period goes, refusing rather than guessing when the two sources disagree."""
    doc = validate_period_json(source)
    declared_key = doc.get("meta", {}).get("project_key")

    # Director ruling D-I (30/09/2026, DASHGATE-01): a period that does not say whose it is is
    # not published. `--project` can no longer supply the key; it may only agree with it.
    if declared_key is None:
        raise _fail(
            "the period declares no meta.project_key, so it does not say whose it is and cannot "
            "be published. Publish a period produced by an engine at contract 1.4 or later. "
            "Nothing was filed.")

    if not isinstance(declared_key, str) or not declared_key:
        raise _fail(
            f"the period's meta.project_key is {declared_key!r}, not a project key. Nothing was "
            f"filed.")

    if project is not None and project != declared_key:
        raise _fail(
            f"--project {project!r} does not match the period's own meta.project_key "
            f"{declared_key!r}. Refusing rather than guessing: filing a period under the wrong "
            f"project is how one project's numbers end up under another project's name.")

    resolved = declared_key
    if "/" in resolved or "\\" in resolved or resolved in (".", ".."):
        raise _fail(f"project {resolved!r} is not usable as a directory name")
    refuse_unpublishable(resolved)

    period_end = doc["meta"]["period_end_date"]
    filename = f"period_{period_end.replace('-', '')}.json"
    destination = data_root / resolved / filename
    already = destination.is_file() and source.resolve() == destination.resolve()
    return PublishPlan(
        source=source,
        project=resolved,
        destination=destination,
        period_end=period_end,
        replaces_existing=destination.is_file() and not already,
        already_in_place=already,
    )


def describe_outcome(plan: PublishPlan) -> tuple[str, str]:
    """What to tell the operator: a verb, and a note where the verb alone would mislead.

    The verb turns on whether anything was **overwritten**, which is the thing a reader worries
    about, and not on whether a copy happened. Pointing the command at the file the engine just
    wrote is the normal first publish; it used to print "Re-published", which reads as though an
    earlier period had been replaced (F5B-16, from the 5b run on a fresh clone).
    """
    if plan.replaces_existing:
        return "Replaced", "an existing period of the same date was overwritten"
    if plan.already_in_place:
        return "Published", "the file was already where it belongs; nothing was copied"
    return "Published", ""


def place(plan: PublishPlan) -> None:
    """Copy the period into the project's directory.

    Publishing a file that is ALREADY where it belongs is a no-op, not an error. It is a normal
    thing to do - re-publishing after an app change, or pointing the command at the file the
    engine just wrote - and `shutil.copyfile` raises `SameFileError` on it. Found by running the
    command against a real period on the first try.
    """
    plan.destination.parent.mkdir(parents=True, exist_ok=True)
    if plan.already_in_place:
        logger.info("already filed at %s; nothing to copy", plan.destination)
        return
    shutil.copyfile(plan.source, plan.destination)


def _run(command: list[str], *, cwd: Path, what: str) -> None:
    logger.info("%s: %s", what, " ".join(command))
    exe = shutil.which(command[0])
    if exe is None:
        raise _fail(
            f"{command[0]!r} is not on PATH, so {what} cannot run. Install it and re-run; this "
            f"command does not skip a step it cannot complete.")
    result = subprocess.run([exe, *command[1:]], cwd=cwd)
    if result.returncode != 0:
        raise _fail(f"{what} failed (exit {result.returncode}). Nothing was deployed.")


def build(dashboard: Path = DASHBOARD) -> None:
    """Rebuild the static export. `prebuild` copies the data in, so this picks up the new period."""
    _run(["npm", "run", "build"], cwd=dashboard, what="dashboard build")


def deploy_commands(*, production: bool, scope: str | None = None) -> list[list[str]]:
    """The two `vercel` commands for one deploy. ``deploy_steps`` places them between the clear and
    the guard, and that sequence is the ONE list both run and printed (FW-26).

    Two steps because `data/` is gitignored and therefore absent on Vercel's build box: the
    artefact has to be built HERE, where the data is, and uploaded ready-made. `build` and
    `deploy` carry the same target, so the build is for the environment it is deployed to.

    Leg 1 found the executed pair and the printed pair differing by `--prod` - preview or a
    client's production - and both passing `vercel build` a `--prebuilt` it does not have.
    `scope` is the Vercel team; unset, Vercel uses the linked project's.
    """
    target = ["--prod"] if production else []
    team = ["--scope", scope] if scope else []
    return [
        ["vercel", "build", *target, *team],
        ["vercel", "deploy", "--prebuilt", *target, *team, "--yes"],
    ]


_BACKSLASH = chr(92)
#: Written by ``clear_build_output`` just before ``vercel build``; consumed by the guard.
BUILD_MARKER = ".guard-build-start"
#: The printed form of the clear and the guard: run from the repository root (N6).
GUARD_SCRIPT = [".venv\\Scripts\\python.exe", "scripts/release/build_guard.py"]


def _shape_offences(config: object) -> list[str]:
    """What makes ``config`` a shape the guard does not know (PM R-1: fail closed, never skip).

    A Build Output API version 3 document: ``version`` 3; ``routes`` a list of objects whose
    ``dest``, where present, is a string; ``overrides``, where present, an object of objects whose
    ``path``, where present, is a string. Anything else is refused rather than read around.
    """
    if not isinstance(config, dict) or config.get("version") != 3:
        return ["not a Build Output API version 3 document"]
    bad = []
    routes = config.get("routes")
    if not isinstance(routes, list):
        bad.append(f"routes is {type(routes).__name__}, not a list")
    else:
        for i, route in enumerate(routes):
            if not isinstance(route, dict):
                bad.append(f"routes[{i}] is {type(route).__name__}, not an object")
            else:
                # Round 2, NOTE-3: `src` is the one field the separator walk skips, so it must at
                # least be the string it is skipped for.
                for field in ("src", "dest"):
                    if field in route and not isinstance(route[field], str):
                        bad.append(f"routes[{i}].{field} is {type(route[field]).__name__}, "
                                   f"not a string")
    if "overrides" in config:
        overrides = config["overrides"]
        if not isinstance(overrides, dict):
            bad.append(f"overrides is {type(overrides).__name__}, not an object")
        else:
            for key, value in overrides.items():
                if not isinstance(value, dict):
                    bad.append(f"overrides[{key!r}] is {type(value).__name__}, not an object")
                elif "path" in value and not isinstance(value["path"], str):
                    bad.append(f"overrides[{key!r}].path is {type(value['path']).__name__}, "
                               f"not a string")
    return bad


def _separator_offences(config: dict) -> list[str]:
    """Every string in ``config.json`` - every key and every value, at any depth - that carries a
    Windows path separator, **except the value of ``routes[].src``**, which is a regex whose
    backslashes are escapes (``^/(.*)\\.html/?$``). A backslash anywhere else 404s a route, a
    redirect or a cron on Vercel's Linux runtime (RELEASE_PROCEDURE step 3). No field list, so a
    field Vercel adds later is covered too (gate 3 round 1, W5)."""
    bad = []

    def walk(node: object, where: str, is_route: bool) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{where}.{key}" if where else str(key)
                if isinstance(key, str) and _BACKSLASH in key:
                    bad.append(f"{where or 'config'} key {key!r}")
                if is_route and key == "src":
                    continue
                walk(value, here, False)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{where}[{i}]", where == "routes")
        elif isinstance(node, str) and _BACKSLASH in node:
            bad.append(f"{where} {node!r}")

    walk(config, "", False)
    return bad


def clear_build_output(dashboard: Path = DASHBOARD) -> None:
    """Remove ``.vercel/output`` and stamp the start of this build (gate 3 round 1, W1).

    Run immediately before ``vercel build``. The project link (``.vercel/project.json``) stays.
    The guard then refuses any output that is missing, unstamped or older than the stamp, so a
    previous run's output can never pass for this build's.
    """
    vercel = Path(dashboard) / ".vercel"
    shutil.rmtree(vercel / "output", ignore_errors=True)
    if (vercel / "output").exists():
        raise _fail(f"could not clear {vercel / 'output'}; a previous build's output would remain. "
                    f"Nothing was deployed.")
    vercel.mkdir(parents=True, exist_ok=True)
    (vercel / BUILD_MARKER).write_text("started", encoding="utf-8")


def _named_listing(listing: Path) -> list[str]:
    """``projects.json``'s list, or a refusal naming it (N1: never a traceback)."""
    try:
        doc = json.loads(listing.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(f"{listing} is unreadable ({exc}). Nothing was deployed.") from None
    listed = doc.get("projects") if isinstance(doc, dict) else None
    if not isinstance(listed, list) or not all(isinstance(p, str) for p in listed):
        raise _fail(f"{listing} does not hold a list of project names under \"projects\". "
                    f"Nothing was deployed.")
    return listed


def guard_build_output(dashboard: Path = DASHBOARD) -> None:
    """DASHGATE-01 P4: refuse to deploy what `vercel build` produced, unless it is safe to serve.

    Run between `vercel build` and `vercel deploy --prebuilt`, in `deploy()` and in the printed
    sequence alike (`deploy_steps`). Each refusal ends "Nothing was deployed":
    1. the output was not produced by this build: missing (`vercel build` reported success and wrote
       nothing), or not stamped by ``clear_build_output``, or older than the stamp (W1). The stamp
       is consumed here, so the guard passes a given build at most once;
    2. `config.json` is not a shape the guard knows (R-1: fail closed);
    3. any string in `config.json` other than a route's `src` regex carries a Windows path
       separator (step 3; the archived `check_build_output_config.py`, ported and widened - W5);
    4. the built data lists, or carries, anything the bindings do not name for publication: only
       `projects.json` and one folder per publishable project may sit in `static/data/`. The names
       come from the bindings (`publishable_projects()`), not from `dashboard/publish.json`.
    """
    from src.sra.cpm.bindings.registry import publishable_projects

    vercel = Path(dashboard) / ".vercel"
    marker = vercel / BUILD_MARKER
    out = vercel / "output"
    config_path = out / "config.json"
    stamped = marker.stat().st_mtime if marker.is_file() else None
    marker.unlink(missing_ok=True)
    if not config_path.is_file():
        raise _fail(f"`vercel build` left no build output at {config_path}. Nothing was deployed.")
    if stamped is None or config_path.stat().st_mtime < stamped:
        raise _fail(f"the build output at {out} was not produced by this build (no clear step "
                    f"preceded it, or it is older than the clear). Run the clear, then "
                    f"`vercel build`, then the guard. Nothing was deployed.")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(f"the build output config {config_path} is unreadable ({exc}). "
                    f"Nothing was deployed.") from None
    unknown = _shape_offences(config)
    if unknown:
        raise _fail(f"{config_path.name} is not a shape the guard knows: " + "; ".join(unknown)
                    + ". Refusing rather than skipping. Nothing was deployed.")
    bad = _separator_offences(config)
    if bad:
        raise _fail(f"{len(bad)} Windows path separator(s) in {config_path.name}: "
                    + "; ".join(bad) + ". These 404 on Vercel's Linux runtime. "
                    "Nothing was deployed.")

    named = set(publishable_projects())
    data = out / "static" / "data"
    listing = data / "projects.json"
    if not listing.is_file():
        raise _fail(f"the build output carries no {listing}. Nothing was deployed.")
    listed = _named_listing(listing)
    stray = sorted(set(listed) - named)
    stray += sorted(e.name for e in data.iterdir()
                    if e.name != "projects.json" and not (e.is_dir() and e.name in named)
                    and e.name not in stray)
    if stray:
        raise _fail(f"the build output would serve what is not named for publication: "
                    f"{stray} (named: {sorted(named)}). Nothing was deployed.")


@dataclass(frozen=True)
class DeployStep:
    """One step of a deploy: printed as ``argv`` from ``where``, executed as ``action``."""

    action: str  # "clear", "vercel" or "guard"
    argv: tuple[str, ...]
    where: str   # "repository root" or "dashboard"


def deploy_steps(*, production: bool, scope: str | None = None) -> list[DeployStep]:
    """The whole deploy sequence - the ONE list both `deploy()` runs and `main` prints (FW-26,
    widened by gate 3 round 1 W3 to include the clear and the guard)."""
    build, upload = deploy_commands(production=production, scope=scope)
    return [
        DeployStep("clear", (*GUARD_SCRIPT, "clear"), "repository root"),
        DeployStep("vercel", tuple(build), "dashboard"),
        DeployStep("guard", (*GUARD_SCRIPT, "check"), "repository root"),
        DeployStep("vercel", tuple(upload), "dashboard"),
    ]


def format_step(step: DeployStep) -> str:
    return f"(from the {step.where}) " + " ".join(step.argv)


def run_deploy_steps(dashboard: Path = DASHBOARD, *, production: bool,
                     scope: str | None = None) -> None:
    for step in deploy_steps(production=production, scope=scope):
        if step.action == "clear":
            clear_build_output(dashboard)
        elif step.action == "guard":
            guard_build_output(dashboard)
        else:
            _run(list(step.argv), cwd=dashboard, what=" ".join(step.argv[:2]))


def deploy(dashboard: Path = DASHBOARD, *, scope: str | None = None) -> None:
    """Upload the prebuilt export to a PREVIEW (R-5, Director 22/09/2026).

    Production is never this command's: the dashboard's release procedure deploys to preview first and to
    production only once the preview has passed, so production is a separate, explicit step.

    DASHGATE-01: the steps are clear, `vercel build`, the guard, `vercel deploy --prebuilt`
    (``deploy_steps``). A refusal at any step means `vercel deploy` never runs.
    """
    run_deploy_steps(dashboard, production=False, scope=scope)


def publish(
    source: Path,
    *,
    project: str | None = None,
    do_deploy: bool = False,
    replace: bool = False,
    data_root: Path = DATA_ROOT,
    dashboard: Path = DASHBOARD,
    scope: str | None = None,
) -> PublishPlan:
    """Validate, file, build, and optionally deploy. Returns the plan that was carried out."""
    plan = resolve_plan(source, project, data_root=data_root)
    if plan.replaces_existing and not replace:
        raise _fail(
            f"a DIFFERENT period already exists for {plan.period_end} under {plan.project!r}: "
            f"{plan.destination}. "
            f"Replacing it would move a published figure with no trace of what it was. Pass "
            f"--replace if that is intended - re-issuing a corrected period is a real thing, but "
            f"it should be said out loud rather than happening because two files share a date.")
    place(plan)
    build(dashboard)
    if do_deploy:
        deploy(dashboard, scope=scope)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="publish_period",
        description="Publish one period JSON to the dashboard (stage 7 B-1).",
    )
    parser.add_argument("period_json", type=Path, help="the period JSON to publish")
    parser.add_argument(
        "--project",
        help="the project key, as a check: it must match the period's own meta.project_key, "
             "which is required (a period that does not say whose it is is refused).")
    parser.add_argument(
        "--replace", action="store_true",
        help="allow replacing an existing period for the same period end. Refused without it: a "
             "published figure should not move because two files share a date.")
    parser.add_argument(
        "--deploy", action="store_true",
        help="also deploy the built export to a Vercel PREVIEW. Without this the command stops "
             "after the build and prints the commands --deploy would run. Production is always a "
             "separate step, once the preview has passed.")
    parser.add_argument(
        "--scope", default=os.environ.get("VERCEL_SCOPE") or None,
        help="the Vercel team to deploy under (default: env VERCEL_SCOPE; unset, the linked "
             "project's)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        plan = publish(args.period_json, project=args.project,
                       do_deploy=args.deploy, replace=args.replace, scope=args.scope)
    except PublishError as exc:
        print(f"\nPUBLISH REFUSED: {exc}\n", file=sys.stderr)
        return 1

    headline, note = describe_outcome(plan)
    print(f"\n{headline} period {plan.period_end} under project {plan.project!r}")
    print(f"  -> {plan.destination}")
    if note:
        print(f"  {note}")
    if args.deploy:
        print("\nDeployed to a PREVIEW.")
    else:
        print("\nBuilt, NOT deployed. To deploy a PREVIEW - exactly what --deploy runs, in order:")
        for step in deploy_steps(production=False, scope=args.scope):
            print("    " + format_step(step))
    print("Production is a separate step, only once the preview has passed - in order:")
    for step in deploy_steps(production=True, scope=args.scope):
        print("    " + format_step(step))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
