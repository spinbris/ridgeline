"""The deploy sequence's two in-process steps, as commands.

`publish_period.py --deploy` runs these itself, as steps 1 and 3 of the four it prints; this is the
same code for a sequence run by hand - the production sequence always is
(docs/RELEASE_PROCEDURE_dashboard.md steps 3 and 7). From the repository root:

    python scripts/release/build_guard.py clear    # before `vercel build`
    python scripts/release/build_guard.py check    # after it, before `vercel deploy --prebuilt`

`clear` removes `dashboard/.vercel/output` and stamps the start of the build; `check` is
`guard_build_output`, which refuses output this build did not produce. Exit 0 = done / passed;
1 = refused (the reason is printed); nothing is deployed by either.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.am import publish_period  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["clear", "check"])
    args = parser.parse_args(argv)
    try:
        if args.step == "clear":
            publish_period.clear_build_output(publish_period.DASHBOARD)
            print("cleared the previous build output; run `vercel build` in dashboard/ next.")
        else:
            publish_period.guard_build_output(publish_period.DASHBOARD)
            print("PASS: the build output is this build's, and safe to deploy.")
    except publish_period.PublishError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
