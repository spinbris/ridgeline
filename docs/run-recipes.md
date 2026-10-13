# Run recipes

Operational run commands, kept lean. PowerShell on Windows; the
same commands run on the Mac with its own paths.

**Before running anything below: use `.venv`, not a bare `python`.** On Windows a bare `python`
resolves to whatever global interpreter is first on PATH, not this project's environment, and
the symptoms are serial-only lanes and a few pinned-value tests off in the last digits.

## The workspace property

**Every input and output path is resolved from the project binding or from an explicit
environment variable, never from a literal in an entry point, and a run refuses to start with
a path unset.** No recipe below carries a machine root or an engagement's file name: you set
the three path variables to your project's files, once per session, and select the project
by its binding key. A guard test (`tests/test_3c_b_workspace_property.py`) holds this for every
tracked file.

```powershell
$env:QRA_PROJECT   = "<binding key, e.g. synthetic_wind>"   # no default; absent selection raises
$env:REGISTER_FILE = "<path to the project's register .xlsx>"
$env:P6_FILE       = "<path to the project's P6 export>"
$env:STRAWMAN_FILE = "<path to the project's strawman .xlsx, or the register for a consolidated register>"
```

The register carries every methodology value the run needs (RS-D: the day rate, the Mode
multiplier grid, the four calibration tolerances, the default injection method); a register
missing one refuses by name. The template (`templates/register_template.xlsx`) carries starting
values for all of them.

## The showcase (the product's own worked example)

```powershell
$env:QRA_PROJECT = "synthetic_wind"
python scripts\run_wind_showcase.py
```

Inputs are the committed fixtures under `tests/fixtures/synthetic_wind/`; outputs land under
`outputs/`. `tests/test_showcase_smoke.py` runs exactly this end to end, and the wind golden
(`python -m pytest -m golden`) holds its headline numbers.

## Cost-only headless run (Tier 2)

There is no command for this. `main.py`, which wrapped it, is retired:
it defaulted to the reference project and could not start without Excel. The headless cost run
itself is `src.tier1_headless.run_headless_from_workbook`, which takes the workbook and the
risk-ID prefix as arguments; call it from Python.

## The client deliverable (notebook surface)

`RUN_FINAL.bat` and `final_runner.ipynb` implement the property
above: one entry point, project-generic, every artefact FAIL-bannered on a
cross-validation failure and a non-zero exit, no PDF.

Smoke run at reduced iterations, when the deliverable is in place:

```powershell
$env:SR5_ITERATIONS = "1000"; $env:SR8_ITERATIONS = "1000"; $env:SR9_ITERATIONS = "1000"
.\RUN_FINAL.bat
Remove-Item Env:\SR5_ITERATIONS, Env:\SR8_ITERATIONS, Env:\SR9_ITERATIONS
```

HTML output hides code cells by default (`--no-input`); `--show-code` keeps them. Word output
is unaffected.

## Diagnostic from cached state

```powershell
python scripts\run_diagnostic.py --project <project-key> --run-date YYYY-MM-DD
```

## Alternate strawman runs

Point `STRAWMAN_FILE` at the variant workbook and re-run; nothing else changes. Editing an
alternate strawman's Modes: `Risk_Scope.Mode_Aggregated` is a formula, not a literal - edit the
Mapping sheet's Mode column and let the lookup refresh.

## A register bigger than 40 risks (the xlsx surface)

The shipped `templates/register_template.xlsx` carries 40 blank risk rows. That is a
**default, not a limit**: the scaffolder takes the count as an argument and builds every
range, formula and protected extent from it.

```bash
python -c "from pathlib import Path; from tools.register_scaffold import build_template; build_template(Path('outputs/register_200.xlsx'), n_blank_input_rows=200)"
```

Regenerate for the project, then fill it - this is a specialist step, done once, before the
register is handed over. Do NOT re-scaffold over a register that already holds data: the
scaffolder emits an empty workbook by design, and it would overwrite the risks.

The shipped default stays at 40 so no register grows without someone choosing the number
(a deliberate choice). Sorting, filtering and inserting a risk row in place are
permitted on the Risk Register under protection, so a register that fits in 40 needs none of
this.

## Retired (do not look for these)

The legacy `.xlsm` VBA path (`run_from_excel.py`, `run_single_only.py`,
`run_assumptions_from_excel.py`, `setup_vba.py`, `vba_module.bas`, `check_dist.py`; no `.xlsm`
was ever tracked) and two diagnostics with no test or recipe (`run_toc_sensitivity.py`,
`diagnose_reader_diff.py`). The cost-only report path is retired too. The xlsx surface
runs through the Tier 1 xlwings shell
(`tier1_xlwings_shell.py`; activation is the specialist's task).
