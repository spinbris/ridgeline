"""Extract the polish-layer source embedded in the register workbook."""
from openpyxl import load_workbook
from pathlib import Path
import sys

SHEET = "Reference (polish)"
# Longest markers first: "FILE 2 ADDENDUM 2" also startswith "FILE 2 ADDENDUM",
# so a shortest-first scan collapses both addenda onto one path.
TARGETS = [
    ("FILE 1 of 3",       "config/polish_spec.yaml"),
    ("FILE 2 of 3",       "tools/register_polish.py"),
    ("FILE 3 of 3",       "tools/polish_charts.py"),
    ("FILE 2 ADDENDUM 2", "tools/_polish_meta_addendum.py"),
    ("FILE 2 ADDENDUM",   "tools/_polish_inbox_addendum.py"),
]


def extract(xlsx):
    ws = load_workbook(xlsx)[SHEET]
    lines = [(c.row, str(c.value) if c.value is not None else "")
             for c in ws["A"]]
    starts = {}
    for row, text in lines:
        for marker, path in TARGETS:
            if text.startswith(marker):
                starts[row] = path
                break
    bounds = sorted(starts)
    for i, start in enumerate(bounds):
        end = bounds[i + 1] - 2 if i + 1 < len(bounds) else len(lines)
        body = [t for r, t in lines if start + 2 <= r < end]
        while body and not body[0].strip():
            body.pop(0)
        # The last section runs to the end of the column, so its closing banner and any
        # trailing editorial note fall inside the slice. Neither is code.
        while body and (not body[-1].strip()
                        or body[-1].startswith("(continues")
                        or body[-1].startswith("====")
                        or body[-1].startswith("END - ")):
            body.pop()
        out = Path(starts[start])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(body) + "\n", encoding="utf-8")
        print(f"wrote {out}  ({len(body)} lines)")


if __name__ == "__main__":
    extract(sys.argv[1] if len(sys.argv) > 1 else "dist/wind_register.xlsx")
