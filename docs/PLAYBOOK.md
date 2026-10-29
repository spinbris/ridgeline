# PLAYBOOK - running Ridgeline on a project, as commands with asserted results

**What this is.** The walkthrough for running Ridgeline: installing it, setting up a project from
its risk workshop, producing the report, and then the monthly period cycle with the dashboard app.
Every step has four parts: the **precondition** you check before typing, the **command** you paste,
what to **expect**, and what it means **if not**. For what each sheet is and what each surface
produces, see `docs/SOFTWARE_USER_GUIDE.md` (Part A the register and Tier 1, Part B the deliverable,
Part C the period cycle and the app); for the mathematics, `METHODOLOGY.md`.

**The two shipped projects.** *Tropic Ridge* (binding `synthetic_wind`) is the showcase: a synthetic
wind farm whose inputs ship in `tests\fixtures\synthetic_wind\`, and the one project named for
publication to the app. *Kestrel Highway* (binding `synthetic_road`) is a synthetic road upgrade
that is **not** named for publication, so publishing it is refused: that refusal is the publish gate
working, and step 7 shows it. Use them to check your install end to end before your own project.

**Who it is for.** Part 0 and step 3's activation are for the risk specialist who sets the tools up.
Steps 1, 2 and 4 to 7 are the analyst's. Part B is the monthly cycle, and is the analyst's.

**How it is kept true.** `tests/test_stage5_playbook_tripwire.py` walks every command block in this
file against the repository: paths exist, modules import, flags are accepted, environment variables
are read. A command that stops resolving fails the test suite.

**Conventions.** Commands are PowerShell, run from the repository root with the virtual
environment active (`.venv\Scripts\activate` puts `(.venv)` at the prompt); the three batch files
run the repository's `.venv` themselves and refuse without it. `<...>` is a value you supply.
Windows paths: the batch files are Windows-only, so macOS is not covered here, although the lock
does install there (README §Setup).

---

## Part 0 - install and activation (once per machine, once per workbook)

### Step 0.1 - Prerequisites

**Precondition.** A Windows machine with Git, Python 3.12, Node 22 and Excel 365 with the
xlwings Lite add-in installable from the Office add-in store. No checkout of this repository yet.

**Command.**

```powershell
py -3.12 --version
node --version
git --version
```

**Expect.** `Python 3.12.x`; `v22.x.x` or higher; any git.

**If not.** Python 3.12 is what the lock pins and every committed number was produced on
(README §Setup). Node 22 is the floor `dashboard/package.json` declares; the app's publish step
refuses below it. Install the missing one and re-run.

### Step 0.2 - Clone at the release tag

**Precondition.** The release tag you mean to run, and only that tag: this walkthrough names no
example tag, because any tag written here goes stale at the next release and would still satisfy
this step's own check. You are **not** inside an existing checkout of this repository - the clone
lands beside one, never in it.

**Command.**

```powershell
git rev-parse --is-inside-work-tree
git clone https://github.com/<owner>/outturn.git outturn-run
cd outturn-run
git checkout <tag>
git rev-parse --show-toplevel
git describe --tags
```

**Expect.** The **first line fails** with `fatal: not a git repository` - expected, and required: it
proves you are not inside a checkout. The checkout prints git's detached-HEAD advisory, ending
*"Or undo this operation with: git switch -"*: **expected and correct at a tag - do not run
`git switch -`**, which takes you off it. The `--show-toplevel` line prints a path ending
`outturn-run`, and the last line prints the tag you asked for.

**If not.** `true` from the first line: you are inside a checkout - `cd ..` out of it and start
again. Cloning there nests a second repository inside the first, and every command below then acts
on the wrong tree while this step's own check still passes. `destination path 'outturn-run' already
exists`: an earlier clone is in the way - use another name, or remove it once you have checked it
holds no work. A different tag on the last line means you are not running the release you meant to:
stop and check.

### Step 0.3 - The Python environment, from the lock

**Precondition.** Step 0.2. No `.venv` directory exists yet.

**Command.**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-lock-20260901-py312.txt
pip install -e .
```

**Expect.** The last two commands each print `Successfully installed ...`; the second one names
`ridgeline-0.1.0`. Two `[notice] A new release of pip is available` lines follow each install and are
the last thing on screen: expected, and **do not upgrade pip** - the lock was cut on the bundled one.

**If not.** A resolver error on the lock means the interpreter is not 3.12 (the lock is wheels-only,
cut on 3.12; it installs off Windows too). A failure on `pip install -e .` is a packaging defect:
report it.

### Step 0.4 - Prove the install reproduces the reference numbers

**Precondition.** Step 0.3, `(.venv)` at the prompt.

**Command.**

```powershell
pytest -m golden
outturn-gate
```

**Expect.**

```text
3 passed, 1 skipped, ... deselected
FAIL: QRA_PROJECT is unset; there is no default project.
```

**If not.** A red golden means this machine does not reproduce the numbers the repository asserts;
do not go on, because the deliverable would not be comparable to anything. The gate's refusal is
the expected result: it proves the console script installed and that the runner has no default
project. Any other message from it is a defect: report it.

### Step 0.5 - The app's toolchain

**Precondition.** Step 0.1's Node.

**Command.**

```powershell
cd dashboard
npm ci
cd ..
```

**Expect.** `added N packages` with no `ERR!` lines. A deprecation warning, a funding line, and an
audit summary reporting vulnerabilities follow it: expected, and **do not run `npm audit fix`** -
it rewrites `dashboard/package-lock.json`, which is tracked.

**If not.** An engine-version refusal means Node is below 22 (step 0.1). Anything else is a
defect in `dashboard/package-lock.json`: report it.

### Step 0.6 - The xlwings Lite add-in (specialist)

**Precondition.** Excel 365 signed in; step 0.3 done, so the pasteable file can be generated.

**Command.** In Excel: Home > Add-ins > More Add-ins > search *xlwings Lite* > Add. Then, on this
machine:

```powershell
python tools\make_qra_xlwings.py
```

**Expect.** The add-in appears on the ribbon as **xlwings Lite** and the command prints the path
`dist/qra_xlwings_combined.py`. Note the add-in's version now (Help > About in its task pane): the
step 3 description below was written against `1.0.0.104`.

**If not.** No ribbon entry: the add-in store is blocked by your organisation's Office settings,
which is outside this product. No `dist/` file: the command's own error names the module it could
not embed.

---

## Part A - setting up a project, once per project

### Step 1 - Create the project's register from the template

**Precondition.** Part 0 done. You have decided where the project's files live; this walkthrough
uses `outputs\<project>\` and calls the register `register_v1.xlsx`. `outputs\` is never committed,
so your project's data stays on your machine. Do **not** open and save
`templates\register_template.xlsx` itself: it is a tracked artefact and a test fails on it.

**`<project>` is a short folder name of your choosing** - a slug for the project, lower case with
underscores. It is not the binding key of step 4, and nothing reads it: it names a directory.

**Command.**

```powershell
$project = "<project>"
python -c "from pathlib import Path; from tools.register_scaffold import build_template; print(build_template(Path('outputs/$project/register_v1.xlsx')).resolve())"
```

**Expect.** The command prints the **absolute path of the register it wrote** - check that it names
your project's folder. `build_template` creates whatever folder it is given and prints nothing else,
so a typo in `$project` writes the register somewhere you did not intend, and this printed path is
the only place you would see it. Set `$project` once here; later steps reuse the same name. The file
opens in Excel on the `TOC & Instructions` sheet, whose tab list is in fill order. Seconds.

**If not.** `ModuleNotFoundError: tools` means you are not at the repository root or the
environment is not active. Anything else is a defect: report it.

### Step 2 - Fill the register from your workshop output

**What you bring: your risk workshop's output.** This is **not a spreadsheet.** It is the record of
what the workshop agreed - usually a Word or Markdown document, in the workshop's own words, with no
workbook column names. A complete one carries:

- **the project:** a one-paragraph description, the base estimate at its base date, and the risk-ID
  prefix;
- **run parameters:** the cost of delay per working day, the number of seasons, the programme length
  in weeks, and the float threshold (in working days) the planner treats as near-critical;
- **correlation groups:** each group's name and its within-group correlation coefficient;
- **the cost build-up:** dollars by element (rows) and resource (columns), if the project uses the
  factor model;
- **the event risks:** per risk, its ID, title, owner, category, shape (PERT, Triangular or
  Lognormal), group, probability, low / most likely / high cost, and - if it delays the programme -
  low / most likely / high working days, how the delay combines (Series, Hybrid or Parallel) and the
  activity it holds up;
- **cost-driver factors:** each factor's low / most likely / high proportional change, and which
  resource columns and elements it applies to;
- **treatments and activity patterns,** if the workshop produced any.

**Why it does not look like the workbook.** A workshop records what people agreed, in their terms;
the register records what the engine reads, in its terms. The gap between the two is the analyst's
job, and this step bridges it: the workbook's own instructions say where each fact goes, and the
table below says the rest. If your output is missing one of the items above, the register cannot be
completed: go back to the workshop for it rather than inventing a value.

**Precondition.** Step 1's workbook open; your workshop output beside it. Follow the front sheet's
tab list, the note block above each sheet's headers, and the header-cell notes. Claude-in-Excel can
do the typing; a person still decides every value.

**Command.** No shell command. Type, in this order: front sheet and run parameters (the day rate
before anything else, so the live EMV totals read), then risks on `Risk Register` from row 5, then
`Mapping` for every Time = Yes risk, then the four `Layer1_*` tabs with `Set_Layer1_Enabled` = TRUE
only once they are filled. **Where each workshop fact goes, where the workbook does not yet say:**

| Where | Type | Why |
|---|---|---|
| `Settings` | iterations 25000, seed 42, owner view - **these three ship as the defaults, so check rather than type** | Tier 1 (step 3, in Excel) reads `Settings`; 25,000 runs in minutes in the add-in. **`Settings` has no P-level row**: the reporting P-level lives on `MC_Params` C5 only, and Tier 1 has none |
| `MC_Params` C2, C5 | iterations 100000, reporting P-level 80 | The deliverable (step 5) reads these from `MC_Params`, not `Settings`; 100,000 is the canonical count |
| `MC_Params` C3 | seed 42 | Recorded on the sheet. The deliverable does not read it: `SR9_SEED` sets its seed |
| `MC_Params` C11 | the workshop's cost of delay, $ per working day | Only the named range `MC_day_rate` says the value column is C |
| `Risk Register` cost three-points (low / most likely / high $) | the risk's direct cost only, without preliminaries or site overheads | Risk cost impacts exclude project time-related costs (preliminaries and site overheads). The model prices those once, through the day rate, on the finish delay that survives float in each iteration. Event-specific standby (idle plant or crew, demobilise / remobilise) is a direct cost and stays in the risk's cost impact. The day rate itself covers preliminaries and site overheads only, with no standby, so the same cost cannot enter through both the day rate and a risk's cost impact. |
| `MC_Params` C12, C13, C14 | seasons (1 unless seasonal), the float threshold in days, programme duration in weeks | Position-only rows |
| `MC_Params` C15 | the count of Time = Yes risks you will enter | Recorded for the reader; nothing checks it, so count carefully |
| `MC_Params` C4, C7 to C10 | leave blank | Stakeholder view and the cascade parameters are not read from a scaffolded register |
| Front sheet identity block | leave blank unless the project supplies them | Project number, client, prepared-by and issue date are recorded, not read |
| `MC_Params` C6 | the base estimate, $, at the estimate's base date | Labelled "TIC" in the workbook |
| `Settings` B4 | the risk-ID prefix your IDs use | IDs with another prefix are read as no rows |
| `Risk Register` Risk Status | `Open` | Recorded, and **not** a filter on this path: `MC Include` is the switch |
| `Risk Register` MC Include | `Yes` for every risk to simulate | The cost arm's inclusion switch: anything else drops the row |
| `Risk Register` Cost Impact | `Yes` for a costed risk | Read by the parser as the cost switch |
| `Risk Register` Probability and Probability (Time) | `Probability` for every risk, as a fraction; `Probability (Time)` the same value **on every Time Impact = Yes row** - a row that does not delay may leave it blank | One risk, one probability: both arms, including the Stage 3 schedule replay behind the headline, fire on `Probability`. A risk that only delays still needs it, with zero dollar estimates. A Time Impact = Yes row whose `Probability (Time)` differs is refused |
| `Risk Register` Impact_Basis, Recurrence Type, Layer1_Factors Column_Scope | leave blank / type the workshop's word | Not read by the engine from this workbook |
| `Risk Register` Package | the risk owner's package, or the owner | This column is what the deliverable prints as the owner |
| `Mapping` Pattern_ID | blank when the project has no pattern catalogue | An empty catalogue is read as none |
| `Mapping` Prefix_List, Activity_Count, Gating_Activity_ID | one row per Time = Yes risk; the prefix or activity the workshop said the risk holds up, the count expected, and the gating activity | A blank `Prefix_List` means the risk contributes no delay, **silently**. A group-bound row (a prefix, not one activity) still takes a gating activity; `Risk Register` AE takes the same activity |
| `Mapping` Injection_Method | blank | Takes the `Methodology` default |
| `Lists` | **replace** the shipped vocabularies with the project's own - packages, RBS levels, factors | They ship as generic seeds no real workshop matches. Extending them leaves dropdowns offering words the project does not use |
| Correlation-group base $ and per-risk chain links | leave them out | The register captures neither; keep them in the workshop record |
| `Layer1_Base` B15 | the declared total, one figure, in $M | Checked against the column sum |
| `Layer1_Correlation` | the strict lower triangle only; the diagonal is locked | The parser refuses upper-triangle values |
| `Methodology` row `Schedule_Top3_Tie_Tolerance_Pct` | leave 0.02 | The cross-validation tie band |
| `Treatments`, `Risk_Activity_Patterns`, `Risk_Pattern_Assignments` | leave headers only if the project has none | An empty sheet reads as none |
| Unused template slots - `Layer1_Base` rows and `Layer1_Allocation` columns beyond your element count, `Methodology` coefficients for groups you removed from `Lists` | leave them | Placeholders and orphans are not read: a register with fewer elements or groups than the template ships is complete |

**Expect.** Save. The live checks are **not on the front sheet**: they are on `EMV & Mode Analysis` -
B5 total cost EMV, B6 total schedule EMV, B8 the Series/Hybrid/Parallel counts - and on `Summary`,
with the per-risk schedule dollars in `Risk Register` column AD. A delaying risk's AD reading a
dollar figure proves the day rate is read. Thirty risks take about ten minutes of typing with
Claude-in-Excel.

**If not.** A live check reading `#VALUE!` or zero means a number was typed as text or the day
rate is blank. Every place you had to guess is worth writing down, with the cell.

### Step 3 - Cost QRA in the workbook (Tier 1; activation is the specialist's)

**Precondition.** Step 2 saved. The add-in installed (step 0.6). Read the `Reference (xlwings)`
tab **rows 3 to 9 only**: row 9 is the instruction. Rows 16 onward print the shell's source as a
convenience copy and **cannot run in Excel**: do not paste them.

**Command.** In Excel, open the xlwings Lite task pane. In add-in **1.0.0.104 there are no panes
called Environment or Editor**: there are three file tabs, `main.py`, `sample.nb.py` and
`requirements.txt`, and two buttons, Update all and Update xlwings.

1. On **`requirements.txt`**, add `numpy` and `scipy`, each on its own line, keeping the lines
   already there. Press neither button: Update would move pinned versions.
2. A banner appears: `Dependencies changed. Restart to apply them.` **Click Restart.** Until you do,
   the run control reads `(no script)` and nothing is selectable. The OUTPUT tab reports what it
   pinned.
3. On **`main.py`**, select all, delete, and paste the whole of `dist/qra_xlwings_combined.py`
   (step 0.6). The PROBLEMS tab will show three *cannot resolve imported module* entries: they are
   not errors, the file installs those modules at runtime.
4. In the dropdown beside the run button, **select** `run_simulation` **and click the button**
   (selecting does not run). The other entries are `run_simulation_100k`, which uses the on-demand
   count, and `validate_contract`, which checks the workbook and writes PASS or FAIL.

**Expect.** The `Simulation` sheet fills, and **nothing announces that it finished** - the filled
sheet is the only evidence. About a minute at 25,000 iterations. **Then save the workbook**: until
you do, the result exists only in the open session. The amber *Contract validation* box beside it
stays empty after `run_simulation` - it is filled by `validate_contract`, not by this run.

**If not.** A `ModuleNotFoundError` at run time means `requirements.txt` is missing `numpy` or
`scipy`, or the Restart in item 2 above was not clicked.

### Step 4 - Declare the project binding

**Precondition.** The register closed in Excel (the pre-flight refuses a locked file). **A project
runs through a binding:** a module under `src\sra\cpm\bindings\` that declares its inputs, labels and
parameters, and whose filename without `.py` is the project's **binding key**. The two shipped
projects have theirs, `synthetic_wind` and `synthetic_road`; a project of your own needs one,
written in the same shape as `src\sra\cpm\bindings\synthetic_road.py`. **Commit your binding, on a
branch of your own, before you run anything.** An uncommitted file - even a new, untracked one -
makes the working tree dirty: the period run (step 7) refuses a dirty tree, and the report is
stamped `engine_tree_dirty: true`, which means the run is not evidence (step 6). The schedule is a P6 `.xer` export from the planner.
**Give it relative to this clone.** An absolute path to a copy elsewhere - another checkout, say -
passes the pre-flight, which checks that a file exists and not where it came from, and silently
becomes the run's input.

**Command.** First with nothing set, to see the refusal; then the four variables.

```powershell
Get-ChildItem src\sra\cpm\bindings\*.py
.\RUN_FINAL.bat
$env:QRA_PROJECT = "<binding key>"
$env:REGISTER_FILE = "outputs\<project>\register_v1.xlsx"
$env:P6_FILE = "<the .xer, relative to this clone>"
$env:STRAWMAN_FILE = "outputs\<project>\register_v1.xlsx"
```

**Expect.** The bare run prints, and exits 2:

```text
ERROR: not set: QRA_PROJECT REGISTER_FILE P6_FILE STRAWMAN_FILE
```

`STRAWMAN_FILE` is the register itself: the schedule methodology workbook is part of the register.
Under a minute. **For the showcase**, set the four to `synthetic_wind`,
`tests\fixtures\synthetic_wind\wind_register.xlsx`, `tests\fixtures\synthetic_wind\wind_schedule.xer`
and the register again.

**If not.** A run with a wrong key stops in the pre-flight with `No project binding registered
under '<key>'. Registered: [...]. A binding must live in src/sra/cpm/bindings/<key>.py` - the
message names the file, so the key is the filename.

### Step 5 - Run the schedule arm and the integrated result (Tier 2)

**Precondition.** Step 4's four variables set in this shell; register closed; no deliverable
`.docx` from a previous run open in Word. Steps 5 and 6 are one command: the standalone schedule
run and the integrated result are cells of the one notebook that produces the deliverable.

**Command.**

```powershell
.\RUN_FINAL.bat
echo "exit $LASTEXITCODE"
```

**Expect.** First an `Inputs:` block: each of the four inputs, `[OK  ]`, with its **resolved** path.
**Read it.** Every path should sit inside the clone from step 0.2; a `NOTE: outside this working
tree` line means the run is about to read a file from somewhere else, which no later check will
catch. Then nbconvert's own lines and the expected warnings below while the three engines run, then the
gate's line and exit code **0**:

```text
PASS: cross-validation passed; artefacts listed in outputs\runs\<date>_<binding key>\provenance.json.
exit 0
```

**Expected on the console, and harmless:** the batch file's own `Project:` and `Output:` lines; a
`zmq` `RuntimeWarning` about the Windows event loop; *"Kernel is running over TCP without encryption
... susceptible to eavesdropping"*, which is a local kernel talking to itself on this machine, not a
network exposure; and an alt-text warning on the report's images. None of them is a failure.

The report's *Cross-validation* table (step 6) shows the four checks; the full gate text, tie line
included, is `cv_result.interpretation` in `outputs\runs\<date>_<binding key>\metadata.json`.

**How long it takes depends on the machine:** a few minutes on a current laptop. Treat a run far
outside that as worth looking into rather than as a failure.

**If not.** Exit **2** with a pre-flight refusal: it lists every check, `[MISSING]` against each
register setting that is absent, by the sheet's own label, and `[OK  ]` against the rest - fix
the cell, save, close, re-run (`MC_Params` iterations and P-level are the usual ones). Exit
**2** at once with `ERROR: .venv\Scripts\python.exe not found`: step 0.3 was not done here, or you
are not at the repository root. Exit **2** after the engines had started: `engine_log.txt` in
`outputs\runs\<date>_<binding key>\` holds their log up to where the run stopped. Exit **1**: every
artefact was written and carries a `DO NOT DISTRIBUTE` banner; `cv_result` in `metadata.json` says
which of the four checks failed - and if all four passed, `stage3_standalone_error` in
`provenance.json` names why the Stage 3 pair was not written, which fails the run on its own.
A `ValueError` naming `headless_config[...]` is a binding reaching for a legacy value: it is a
product defect, so report it rather than editing the source.

### Step 6 - Read the deliverable

**Precondition.** Step 5 exited 0.

**Command.**

```powershell
Get-ChildItem outputs\*<date>*
Get-ChildItem outputs\runs\<date>_<binding key>\ -Exclude *.parquet
Get-Content outputs\runs\<date>_<binding key>\run_diagnostic_<date>.txt -TotalCount 20
Get-Content outputs\runs\<date>_<binding key>\provenance.json | Select-Object -First 30
```

**Expect.** The deliverable HTML, one executive-summary `.docx` per headline metric, the Stage 3
standalone `.docx` and `.html` pair, and `outputs\runs\<date>_<binding key>\` holding
`provenance.json` (engine SHA, `engine_tree_dirty`, input hashes, `params` with iterations, seed,
day rate and programme days, and `cross_validation_all_pass: true`) beside the state cache
(`manifest.json`, `metadata.json` and the arrays), `engine_log.txt`, and
`run_diagnostic_<date>.txt`. **The diagnostic is the one-page answer**: its first line after the
title is `Cross-validation: PASS`, its headline block is the Stage 3 P80 the executive summary
opens with, its `GATE` block reads `PASS` on each of the four checks, and `Engine tree:` reads
`clean`. The full list of what a run writes, and what each file is for, is
`docs/SOFTWARE_USER_GUIDE.md` §7; model validation, what correlation contributes and the basis of
estimate column are its §8.5 to §8.7, and the diagnostic itself is §8.8. The headline is the
**Stage 3** distribution - one schedule-replay run, P50 / P80 / P95 with its basis stated; the
Stage 2.5 Mode-scenario figure appears only as a labelled comparator. The executive summary opens
`Recommended project contingency: $<value> M (P80, integrated cost plus schedule).`

**If not.** `engine_tree_dirty: true` in the provenance, or `(working tree dirty)` beside the
engine SHA in the report's header, means the checkout was modified - including a tracked file
edited while the run was going, since the stamp is taken at the end; the run is not evidence.
A headline equal to the Stage 2.5 comparator's figure, or a Stage 3 standalone page naming another
project or printing `<...>` tokens, is a defect: report it.

### Step 7 - Produce a period and serve it in the app

**Precondition.** Step 5's register; the same `.xer`; `QRA_PROJECT` still set in this shell
(`RUN_PERIOD.bat` refuses without it). The status workbook is generated from the register; it has
no formatting and no notes - it is the contract and nothing else. **`--strawman` names the
register** - the same file as `--register`. With `--register` given, `RUN_PERIOD` uses the register
as the strawman even when `--strawman` is left out.

**`<phase>` is free text** and nothing validates it: it is printed on the period's metadata block
for a reader. Use the phase the project is actually in, for example `Construction`. The flag may be
omitted entirely.

**Command.**

```powershell
$project = "<project>"; $binding = "<binding key>"; $periodEnd = "<YYYY-MM-DD>"; $xer = "<relative\path\to\schedule.xer>"
$register = "outputs\$project\register_v1.xlsx"
python scripts\build_status_workbook.py --register $register --period-end $periodEnd --out outputs\$project\period_01.xlsx --phase "<phase>"
.\RUN_PERIOD.bat outputs\$project\period_01.xlsx --register $register --xer $xer --strawman $register
.\PUBLISH_PERIOD.bat <json-path-printed-above> --project $binding
```

**Expect.** The status workbook, then the period, then the publish:

```text
wrote outputs\<project>\period_01.xlsx  (<n> tracked risks, period end <YYYY-MM-DD>)
Wrote data\<binding key>\period_<YYYYMMDD>.json (... bytes)
```

**Nothing is published unless it is named.** A project reaches the app only when its binding sets
`publish=True` (and is not confidential) and `dashboard\publish.json` is regenerated from the
bindings - a decision per project, not a step in this walkthrough. Until then `PUBLISH_PERIOD`
refuses it and files nothing. Run the commands above on Kestrel - `$env:QRA_PROJECT` and `$binding`
both `synthetic_road`, `$register` its register `tests\fixtures\synthetic_road\road_register.xlsx`,
and `$xer` its schedule `tests\fixtures\synthetic_road\road_schedule.xer` - and the publish prints:

```text
PUBLISH REFUSED: project 'synthetic_road' may not be published: it is not named for publication (its binding does not set publish=True). Nothing was filed.
```

That refusal is the gate working.

**To see the dashboard,** publish the named showcase, Tropic Ridge (`synthetic_wind`), from its own
status workbook, then serve the build:

```powershell
python -m src.am.run_period --workbook status_periods\wind_period_01.xlsx --project synthetic_wind --output-dir data --project-start 2024-01-01
.\PUBLISH_PERIOD.bat <json-path-printed-above> --project synthetic_wind
python -m http.server 4173 -d dashboard\out
```

Give `PUBLISH_PERIOD.bat` the path `run_period` printed on its `Wrote` line, exactly as printed -
never build it by hand from the date. The showcase ships four monthly status workbooks,
`status_periods\wind_period_01.xlsx` to `status_periods\wind_period_04.xlsx`: run and publish the
other three the same way, in order, and the app's trend and change views fill in. **Expect** `Built, NOT deployed`, then the four steps a preview
deploy would run (step B.5). Then open `http://localhost:4173/?project=<binding key>`, with
`synthetic_wind` as the key: the page's title is the project's display name, *Tropic Ridge Wind
Farm*, and the headline strip shows the P80 forecast finish and the integrated P80.

**If not.** `RUN_PERIOD.bat` refuses with `ERROR: .venv\Scripts\python.exe not found` when it is
not run from the repository root or step 0.3 was not done. `PUBLISH_PERIOD.bat` refuses a period
whose date already exists without `--replace`, and never deploys without `--deploy`; this
walkthrough stops at the local build. From there to a served instance - guard, preview, smoke
check, production - is `docs/RELEASE_PROCEDURE_dashboard.md`. **The app's integrated P80 against
step 6's headline:** both are the Stage 3 distribution on the same inputs, and both fire every risk
on the same draw, so on the same inputs, seed and iterations they agree exactly. A difference is a
defect; do not reconcile them by hand.

---

## Part B - the period cycle, monthly

The cycle is: data freeze, workbook update, engine run, review against the previous period,
publish, discuss. The aim is about seven working days from period end to a refreshed dashboard.
Record how long each step takes you: that is the measure of whether the cycle fits.

### Step B.1 - Data freeze

**Precondition.** Period end reached. The planner's `.xer` for the period received; the register
current (a risk closed or re-probabilised this period is changed in the register, which is the
source of truth).

**Command.** No shell command. File the `.xer` and the register under `outputs\<project>\` with the
period date in the filename; record the two filenames and the date.

**Expect.** Two files, dated. Nothing is run.

**If not.** No `.xer` for the period: the cycle waits; a period run on last period's schedule is
not this period's.

### Step B.2 - Update the status workbook

**Precondition.** Last period's workbook, or step 7's for the first period.

**Command.** Copy last period's workbook to `period_<NN>.xlsx` and edit in Excel: on
`AM_Period_Status` set `am_period_end` (B1) to this period's end and `am_previous_period` (B2) to
last period's; per risk set `Status_this_period` (Open / Fired / Closed), the dates, and any
`Probability_override` or `Mode_override`; on `AM_Milestones` update `Status` and
`Percent_complete`; on `AM_Mitigation_Log` add proposals with `Cost_AUD`, `Lead_time_weeks` and
`Estimated_days_saved`. A new risk entered in the register this period is added as a row with its
`Risk_ID`. Close the file.

**Expect.** The workbook opens without a lock file beside it (`~$period_<NN>.xlsx` means Excel
still has it).

**If not.** The reader refuses a missing header by name (`AM_Period_Status row 14 is missing
expected column headers`): a column was deleted or renamed; restore it from
`templates\status_workbook_template.xlsx`.

### Step B.3 - Run the period

**Precondition.** Step B.2 closed; `QRA_PROJECT` set; the environment active.

**Command.**

```powershell
.\RUN_PERIOD.bat outputs\<project>\period_<NN>.xlsx --register outputs\<project>\register_<date>.xlsx --xer outputs\<project>\<schedule_date>.xer --strawman outputs\<project>\register_<date>.xlsx
```

**Expect.** `Wrote data\<binding key>\period_<YYYYMMDD>.json`; `meta.previous_period_end_date` in
the JSON is last period's date, so the trend and the delta blocks are populated. About half a
minute at the default iteration counts.

**If not.** `engine_tree_dirty` refused: the checkout has uncommitted changes; a period is
evidence and must come from a clean tree (`--allow-dirty` exists and stamps the JSON as
non-clean, for smoke runs only). A reader error names the sheet and row.

### Step B.4 - Review against the previous period

**Precondition.** Step B.3's JSON.

**Command.**

```powershell
python -m http.server 4173 -d dashboard\out
```

Open `http://localhost:4173/?project=<binding key>` after step B.5's build, or read the JSON's
`delta` and `trend` blocks directly.

**Expect.** The trend strip carries one more point; the delta block names the risks that fired,
closed or moved; the P80 finish moved for a reason you can name from the workbook edits.

**If not.** A P80 move you cannot trace to an edit is an anomaly, and resolving it is the risk
specialist's job before anything is published. Do not publish.

### Step B.5 - Publish

**Precondition.** Step B.4 reviewed; a decision taken on whether this period is deployed.

**Command.**

```powershell
.\PUBLISH_PERIOD.bat data\<binding key>\period_<YYYYMMDD>.json --project <binding key>
```

Add `--deploy` only once a deploy has been decided, and follow
`docs/RELEASE_PROCEDURE_dashboard.md`. `--deploy` runs the build-output guard between the build and
the upload, so it cannot upload a build nothing has checked.

**Expect.** For a project named for publication: `Built, NOT deployed`, then the four steps a
preview deploy runs, in order - the clear, `vercel build`, the guard, `vercel deploy --prebuilt` -
each with the directory it runs from, and the same four for production, which is always a separate
step, taken only once the preview has passed. For a project not named for publication, the
refusal, and nothing filed:

```text
PUBLISH REFUSED: project 'synthetic_road' may not be published: it is not named for publication (its binding does not set publish=True). Nothing was filed.
```

**If not.** A contract refusal names the schema version: the JSON was produced by a different
engine build than the app expects; re-run step B.3 on the release the app was built from.

### Step B.6 - Discuss

**Precondition.** Step B.5 served.

**Command.** No shell command. The project team reads the page; actions are assigned against the
mitigation proposals; decisions go back into next period's register and workbook (step B.2).

**Expect.** Every mitigation row on `AM_Mitigation_Log` has an owner and a status by the end.

**If not.** A period with no decisions recorded is a period the cycle did not close; note it in
`am_period_notes` (B8) so the next period's reviewer sees it.
