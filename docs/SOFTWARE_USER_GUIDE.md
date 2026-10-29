# Cost and Schedule Risk Analysis Software - User Guide

**Version:** 2.2
**Date:** 14 September 2026
**Status:** Current.
**Audience:** Analysts and reviewers running this software on a project. Finance-professional
level; no programming knowledge assumed.

---

## How to read this guide

The software has **three surfaces**, and this guide covers all three: the Excel register workbook,
the deliverable run, and the monthly period cycle with its web app. Each part says what the surface
is, who runs it, what goes in, what comes out, and what it refuses.

| If you are | Read |
|---|---|
| Filling in a project for the first time | §1, §2, then Part A (§3-§5) |
| Producing a client deliverable | Part B (§6-§8) |
| Running the monthly cycle | Part C (§9-§11) |
| Reviewing someone else's numbers | §8, §12, §13, and `METHODOLOGY.md` |
| Looking for the exact commands | `docs/PLAYBOOK.md` - the step-by-step procedure |
| Looking for the mathematics | `METHODOLOGY.md` - distributions, correlation, joint sampling |

**This guide explains; the playbook instructs.** Every command sequence lives in
`docs/PLAYBOOK.md`, which is checked against the repository by a test on every stage gate. This
guide names commands where it must, but does not restate the procedure.

**Methodology is not duplicated here.** `METHODOLOGY.md` is the single home for the mathematics of
the four analytical components. Where this guide needs a formula to make an instruction
intelligible, it gives one line and a pointer. Anything stated twice eventually disagrees with
itself, which is exactly what happened to v1.1 of this guide.

### Changelog

**v2.2 (14 September 2026)** - §8.8 describes the run diagnostic as it now is. The four wrong lines
v2.1 warned about are fixed, and so is a fifth: a run that failed only because its
Stage 3 pair was not written used to get a diagnostic reading PASS.

**v2.1 (13 September 2026)** - the report content added on 12 September 2026 reaches the guide.
v2.0 said a run wrote no diagnostic text file; it has written one on every run since that change,
and an engine log since shortly after.

- §7 lists every file a run writes, one row each, and nothing a run does not write - held by a
  test that runs the deliverable and compares the files on disk with this table.
- §7.2 adds `stage3_standalone_error`, the field behind a FAIL whose four checks all passed.
- §8.5 to §8.8 are new: model validation, what correlation contributes, the basis of estimate
  column, and the run diagnostic - including the four lines of it that were wrong at the time.
- Paths named here are held by `tests/test_doc_paths.py`, which also walks the playbook.

**v2.0 (12 September 2026)** - rebuilt from v1.1, after an
audit measured v1.1 against the code. v1.1 was dated 13 May 2026, described one of the three
surfaces, and had been overtaken in some sixty specific claims - among them which methodology
produces the headline number. What changed:

- Covers all three surfaces. Tier 1 in Excel, the period cycle and the web app were absent.
- States the current headline correctly: the **Stage 3** CPM-replay distribution, with Stage 2.5
  retained as a labelled comparator (11 September 2026).
- Describes the **scaffolded register** that the product ships.
- Methodology sections replaced by pointers to `METHODOLOGY.md`.
- Corrected throughout: the input set, the artefact set, the executive summary's structure, the
  cross-validation checks, the convergence chart, and the run-time figures.
- Held true by `tests/test_guide_tripwire.py`, which fails when a path, module, entry point, sheet,
  named range, environment variable or document pointer named here stops resolving.

v1.1 and its history remain in git.

---

## 1. What this software does

It produces a **quantitative cost and schedule risk analysis** for an infrastructure project: how
much contingency the project needs, how late it is likely to finish, and which risks drive both.

It combines four analytical components - a deterministic cost QRA, a cost Monte Carlo, a schedule
Monte Carlo over the CPM network, and an integrated joint simulation of the two - into one client
deliverable, and then tracks the same project month by month. The mathematics of each component is
in `METHODOLOGY.md`; the framework is anchored in AACE 132R-23 and the Australian Department of
Infrastructure Cost Estimation Guidance Notes.

**The headline number** the deliverable reports is the **Stage 3** integrated cost-plus-schedule
contingency: one distribution from a full CPM replay, quoted at P80. The older Stage 2.5
Mode-multiplier approach is retained in the deliverable as a **labelled comparator** and is never
the headline. §12 gives the current state and its caveats.

**It is project-agnostic.** A project is a register workbook, a P6 schedule export, and a binding
module that names the project. Nothing in the engines is specific to any one project.

### What it is not

- It is not an estimating tool. The base estimate is an input.
- It does not price liquidated damages, escalation, or interest during construction. Escalation has
  a separate module that is deliberately unwired.
- It does not identify risks. It quantifies a register that a workshop has already produced.

---

## 2. The three surfaces

| Surface | Who runs it | Entry point | Inputs | Outputs |
|---|---|---|---|---|
| **Tier 1, in Excel** | Analyst, after a specialist activates it once | xlwings Lite task pane, inside the register | The register's own `Risk Register`, `Settings`, `Methodology` and `Layer1_*` sheets | The register's `Simulation` sheet: P-table, S-curve, convergence |
| **The deliverable** | Analyst | `RUN_FINAL.bat` | Register, P6 `.xer`, the four environment variables | HTML report, executive summary `.docx`, Stage 3 standalone pair, run cache with `provenance.json` |
| **The period cycle and app** | Analyst monthly; whoever publishes approves publishing | `RUN_PERIOD.bat`, then `PUBLISH_PERIOD.bat` | Status workbook, register, `.xer` | Period JSON, and the web dashboard built from it |

The three agree by construction, and two of the agreements are tested:

- Tier 1 and the deliverable's cost arm produce **identical** numbers - exact on `float.hex()`,
  no tolerance (`tests/test_3c_d_cross_surface_agreement.py`).
- The deliverable and the period engine run the same CPM kernel. Their Stage 3 P80 delays are
  compared on every deliverable run, and the run fails if they disagree beyond the register's
  tolerance (§8.3, check 2).

### 2.1 Before you start

- **Python 3.12 and the lock file.** The three `.bat` entry points run the repository's own `.venv`
  and refuse without it. See `README.md` for setup and `docs/PLAYBOOK.md` Part 0 for the sequence.
- **Node 22** or higher, for the web app only.
- **Excel 365** with the xlwings Lite add-in, for Tier 1 only.
- **Windows** for the three `.bat` entry points. The Python install works on macOS; the runners do
  not.

---

# Part A - the register workbook

The register is the project's input document and, for the deliverable, its configuration file. One
workbook holds the risks, the run parameters, the schedule bindings and the methodology settings.

## 3. Creating and filling the register

### 3.1 Creating it

A new project's register is **scaffolded** from `templates/register_template.xlsx` by
`tools/register_scaffold.py`. Do not open and save the template itself - it is a tracked artefact
and a test fails when it changes.

The command is in `docs/PLAYBOOK.md` Part A step 1. It writes a workbook of **18 sheets**, opening
on `TOC & Instructions`, whose tab list is in the order you fill them. The scaffolded workbook
carries 40 blank risk rows by default; the row count is set at scaffold time, and rows cannot be
inserted afterwards because the sheets are protected.

### 3.2 The sheets

| Sheet | You fill it? | What it is |
|---|---|---|
| `TOC & Instructions` | No | Front sheet: the fill order, the cell-type legend, units and basis, and how to run |
| `MC_Params` | **Yes** | Engine run parameters for the deliverable (§3.3) |
| `Lists` | **Yes** | The dropdown vocabularies: packages, RBS levels, distributions, correlation groups, factors |
| `Risk Register` | **Yes** | One row per risk, from row 5 (§3.4) |
| `Mapping` | **Yes** | Which schedule activities each delaying risk binds to (§3.5) |
| `Risk_Activity_Patterns`, `Risk_Pattern_Assignments`, `Treatments` | **Yes, if you have them** | Workshop inputs. Headers only reads as "none" |
| `Methodology` | **Yes** | Correlation coefficients, Mode multipliers, calibration tolerances (§3.6) |
| `Settings` | **Yes** | Run settings for Tier 1 in Excel, and the risk-ID prefix (§3.3) |
| `Layer1_Base`, `Layer1_Factors`, `Layer1_Allocation`, `Layer1_Correlation` | Optional | The deterministic factor model; ships off (§3.7) |
| `Summary`, `EMV & Mode Analysis` | No - calculated | Live Excel formulas over your inputs: the checks you read while filling |
| `Simulation` | No - model writes | Tier 1 writes its results here |
| `Reference (xlwings)` | No | Activation instructions for Tier 1 (§5) |

### 3.3 Run parameters: two sheets, and why

**`MC_Params` holds the run settings the deliverable reads. `Settings` is read by Tier 1 in Excel.** Both must be
filled, and they overlap. This is a known wart.

On `MC_Params`, the labels are in column B and **your values go in column C**. Nothing on the sheet
says so; only the named range `MC_day_rate`, which points at `MC_Params!$C$11`, reveals it.

| Cell | Parameter | Notes |
|---|---|---|
| C2 | Iterations | 100,000 is the canonical production count |
| C3 | Random seed | Not read by the deliverable, which takes its seed from `SR9_SEED`. 42 by convention |
| C4 | Stakeholder view | Optional |
| C5 | Reporting P-level | 80 |
| C6 | Base estimate, dollars | Labelled "TIC". It means the base estimate at its base date, before contingency and escalation |
| C7-C10 | Cascade parameters | Not read from a scaffolded register; leave blank |
| C11 | **Day rate**, dollars per working day | The named range `MC_day_rate`. Fill this first: every schedule figure converts to dollars through it, and the live checks read zero without it |
| C12 | Programme seasons | 1 unless the programme is seasonal |
| C13 | Critical-path float threshold, working days | 20 is the shipped default |
| C14 | Programme duration, weeks | |
| C15 | Count of Time Impact = Yes risks | Recorded for the reader. **Nothing asserts it today** - see §13 |

On `Settings`, labels are in column A and values in column B: iterations (25,000 interactive),
seed, view, **risk-ID prefix**, the 100,000 on-demand count, the contract version and the Pyodide
pin (both locked), and the Layer 1 switch. The **risk-ID prefix is load-bearing**: risk IDs that do
not match it are read as no rows at all.

**The day rate is typed, not derived.** Whatever reconciliation produced it - weekly preliminaries
over programme working days, or another basis - happens off-tool and belongs in the project file.
The deliverable needs it.

### 3.4 The `Risk Register` sheet

31 columns, A to AE. Section labels are in row 3, headers in row 4, and **your rows start at row
5**. Hover a header for its format note.

The columns that change what the engines do:

| Column | What it does |
|---|---|
| `Risk ID` | Must carry the prefix from `Settings` B4 |
| `MC Include` | **The inclusion switch.** `Yes` puts the risk in the cost simulation; anything else drops it |
| `Risk Status` | Recorded, and **not** used as a filter on this path. Use `MC Include` to include or exclude |
| `Package` | Printed as the risk owner in the deliverable. There is no separate Owner column |
| `Cost Impact` | `Yes` for a costed risk |
| `Probability` | A **fraction**: 0.45 means 45%. The risk's one probability: the cost and the schedule arm both fire on it, including the Stage 3 CPM replay that produces the headline. Fill it for **every** risk, including one that only delays - give that its dollar estimates as zero |
| `Optimistic / Most Likely / Pessimistic ($)` | The three-point cost inputs |
| `Distribution` | PERT, Triangular, Lognormal, Binary, or Binary/PERT |
| `Correlation Group` | CG01 to CG13, or blank for a singleton. Coefficients live on `Methodology` |
| `Time Impact` | `Yes` puts the risk in the schedule arm |
| `Probability (Time)` | **Not read as a probability**. Keep it equal to `Probability`: the workbook's own EMV columns still read it, and a run refuses a Time Impact = Yes risk where the two differ. It is being removed |
| `Optimistic / Most Likely / Pessimistic (days)` | The three-point schedule inputs, in working days |
| `Mode` | Series, Hybrid or Parallel - how the delay combines with others. Used by the Stage 2.5 comparator only |
| `EMV_cost`, `EMV_sched_days`, `EMV_sched_dollars` | Calculated. Do not type |

**Why there is one probability.** A risk is one event. Whether it happens is one question, and
its cost and its delay are both consequences of the answer, so both arms fire a risk on one draw
against `Probability` (since 17/09/2026). Per risk per iteration the two arms share that fire
decision and the severity draw: a risk carries its cost and its delay together or neither, and if
it fires large on cost it fires large on schedule. That is the integration mechanic, and
`METHODOLOGY.md` §6 is its home. If what you want to say is that a risk which happens may not
delay, put that in its delay estimate; if the delay is really a different event, give it its own
row.

Columns recorded but not read by the engines: `Impact_Basis`, `Recurrence Type`, `Basis of
Estimate`, `Causes`, `Consequences`, `Existing Controls`.

### 3.5 The `Mapping` sheet

One row per Time Impact = Yes risk, from row 6's headers. It binds each delaying risk to the
schedule:

- `Prefix_List` - one activity-code prefix, or a single activity ID. **A blank means the risk
  contributes no delay, silently.**
- `Activity_Count` - how many activities the planner expects that prefix to expand to.
- `Gating_Activity_ID` - the single activity the delay attaches to.
- `Pattern_ID` - blank when the project has no pattern catalogue.
- `Injection_Method` - blank takes the `Methodology` default.

### 3.6 The `Methodology` sheet

Correlation coefficients CG01 to CG13 (they ship at 0.5 and should be elicited per project), the
Mode multiplier grid, and the calibration tolerances the cross-validation gate uses (§8.3),
including the top-3 tie band. **These are register values.** The Mode multiplier grid and the
calibration tolerances, the tie band included, have no code default: a register without them is
refused - which is deliberate, so that a tolerance can never be relaxed in code to make a failing
run pass. A correlation group the coefficient block does not name runs at 0.5 (§8.6).

### 3.7 Layer 1, the optional factor model

Four sheets - base matrix, factors, allocation, correlation - plus `Set_Layer1_Enabled` on
`Settings`, which ships `FALSE`. Fill the sheets first and switch it on last. `Layer1_Base` carries
a declared total in **$M**, checked against the column sum. `Layer1_Correlation` takes the strict
lower triangle only.

Layer 1 is **off in the integrated engine by design**: the deliverable runs the event-risk layer
only. Layer 1 feeds Tier 1 in Excel.

### 3.8 While you fill: the live checks

Two sheets calculate as you type, and are how you catch a number typed as text:

- `EMV & Mode Analysis` - B5 total cost EMV, B6 total schedule EMV, B7 their sum, B8 the
  Series / Hybrid / Parallel counts.
- `Summary` - the two SRA calibration comparators, in days and dollars.

A `#VALUE!` or a zero where you expect a figure almost always means a number typed as text, or a
blank day rate.

## 4. What the register refuses

The deliverable's pre-flight reads the register before any engine starts and reports **every**
missing setting in one message, by the sheet's own label, rather than one per run. It checks the
three input paths, that no file is open in Excel (a `~$` lock file fails the run), the methodology
settings, the Mode multiplier grid and the tolerances.

It is **silent when it passes**. No news is good news.

## 5. Tier 1 - running the cost simulation inside Excel

Tier 1 is the cost engine, running in Excel, on the register you are filling. It is the fastest way
to see a cost distribution without leaving the workbook.

**It is cost only.** No schedule simulation, no CPM, no integrated result, no cross-validation and
no document. For those, run the deliverable (Part B).

### 5.1 Activation, once per machine and workbook

A specialist does this once. The register ships with no code in it.

1. Install the **xlwings Lite** add-in from the Office add-in store. It appears on the Home ribbon.
2. Generate the pasteable bundle with `tools/make_qra_xlwings.py`. It writes
   `dist/qra_xlwings_combined.py`, which embeds the engine modules. `dist/` is not tracked, so
   **regenerate it after every pull** - a stale bundle runs old engine code.
3. In the task pane, add `numpy` and `scipy` to the requirements tab, then **click Restart** when
   the pane says dependencies changed. Until you do, no script is selectable.
4. Paste the whole bundle into the editor's `main.py` tab. Three *cannot resolve imported module*
   entries appear in PROBLEMS; they are expected, because the file installs those modules at run
   time.

Read `Reference (xlwings)` rows 3 to 9 for the requirements and the Pyodide pin. **Rows 16 onward
are a human-readable copy of the shell source and cannot run in Excel** - do not paste them.

The exact click sequence, and the traps in it, are in `docs/PLAYBOOK.md` Part 0 step 0.6 and Part A
step 3.

### 5.2 Running it

Three entry points appear in the task pane's dropdown. **Select one and then click Run** - selecting
alone does nothing.

| Entry | What it does |
|---|---|
| `run_simulation` | Runs at the `Settings` interactive iteration count (25,000 as shipped) |
| `run_simulation_100k` | Runs at the on-demand count (100,000 as shipped) |
| `validate_contract` | Checks the workbook's contract - named ranges, contract version, the methodology grid - and writes PASS or FAIL to the `Simulation` sheet. It reports; it does not raise |

### 5.3 What it writes

All on the `Simulation` sheet, in amber cells the model owns: the P-table (P5 to P95), the S-curve,
a correlation flag, the convergence half-width in dollars and per cent, the correlation-sensitivity
triple, and the contract validation cell. **There is no completion message** - the sheet filling in
is the only evidence the run finished.

Tier 1 reads `Settings`, not `MC_Params`, and has no reporting P-level of its own.

---

# Part B - the client deliverable

## 6. Running it

### 6.1 What it needs

Four environment variables. **The runner has no default project and no built-in paths**, and
refuses rather than guessing, because a runner that guesses publishes the wrong project's numbers
quietly:

| Variable | What it is |
|---|---|
| `QRA_PROJECT` | The binding key: the filename, without `.py`, of a module under `src/sra/cpm/bindings/`. It supplies the report title and the project's schedule binding |
| `REGISTER_FILE` | The register workbook |
| `P6_FILE` | The P6 `.xer` export |
| `STRAWMAN_FILE` | Usually the register again - the strawman is dissolved into it |

Run `RUN_FINAL.bat` with none of them set and it names all four and exits 2. The command sequence
is `docs/PLAYBOOK.md` Part A steps 4 and 5.

Two optional variables: `SR9_ITERATIONS` sets the iteration count, and `SR9_SEED` sets the
seed. A positive whole number gives a repeatable run; unset, blank or 0 gives a random one, whose
seed is drawn once, used by every part of the run and recorded in its provenance, so setting it
back repeats the run. `FINAL_REPORT_MODE` is refused unless it is `prod`.

### 6.2 The command and its flags

`RUN_FINAL.bat` takes two flags:

- `--headline P80 | Mean | both` - **the default is P80 only.** Pass `both` for the second
  document.
- `--show-code` - keeps the executed code visible in the HTML.

The register must be **closed in Excel**, and no previous deliverable `.docx` open in Word. The
`~$` lock check covers the three input files; an open output document fails later, when the
document is saved.

### 6.3 Exit codes

| Code | Meaning |
|---|---|
| **0** | Cross-validation passed. The artefacts are the deliverable |
| **1** | A cross-validation check failed. **Every artefact was still written, and each carries a DO NOT DISTRIBUTE banner.** `cv_result` in the run's `metadata.json` says which check failed |
| **2** | The run refused before starting: a missing variable, a missing register setting, a locked file, or no `.venv` |

Writing the artefacts and then failing is deliberate: a failed run is diagnosable without being
distributable.

### 6.4 How long it takes

A production run at 100,000 iterations took **2 min 12 s** on a development machine on 11/09/2026,
and 6 to 7 minutes on other measured runs. Run time depends on register size, iteration count and machine load, so treat any single figure
as that machine on that day.

## 7. What a run produces

| Artefact | What it is |
|---|---|
| `outputs\<project>_deliverable_<date>.html` | The long-form report: charts, tables, methodology. Written by `RUN_FINAL.bat`'s notebook conversion, after every file below |
| `outputs\BETA_executive_summary_<date>.docx` | The client document, 11 sections, 6 to 8 pages. Under `--headline P80`, the default, or `both` |
| `outputs\BETA_executive_summary_MEAN_<date>.docx` | Only under `--headline Mean` or `both` |
| `outputs\sra_stage3_standalone_PROD_<variant>_<date>.docx` | The Stage 3 schedule analysis in full, including model validation (§8.5) and what correlation contributes (§8.6) |
| `outputs\sra_stage3_standalone_PROD_<variant>_<date>.html` | A one-page summary of the Stage 3 analysis; neither §8.5 nor §8.6 is in it |
| `outputs\runs\<date>_<binding key>\provenance.json` | What makes the run evidence (§7.2) |
| `outputs\runs\<date>_<binding key>\run_diagnostic_<date>.txt` | A one-page plain-text summary of the run - verdict, headline, top drivers, provenance, artefacts. Written on a pass and on a fail, bannered on a fail (§8.8) |
| `outputs\runs\<date>_<binding key>\engine_log.txt` | The engines' log lines, held out of the HTML and filed here instead. Written even when the run stops part-way, because that is the run whose log matters |
| `outputs\runs\<date>_<binding key>\metadata.json` | The run cache's structure, with each array replaced by a reference. The gate's full text is here |
| `outputs\runs\<date>_<binding key>\manifest.json` | The run cache's map from array name to where it sits in the structure |
| `outputs\runs\<date>_<binding key>\<array>.parquet` | One file per cached array. With the two files above, this is what `scripts\run_diagnostic.py` re-reads to re-render a diagnostic |
| `outputs\charts\<chart>.png` | The rendered chart images |

There is no PDF.

**The HTML and the executive summary are not two renderings of one report.** Each carries material
the other does not, so neither is on its own the complete analysis:

| Only in the executive summary `.docx` | Only in the deliverable HTML |
|---|---|
| Activity-level criticality in full - the explainer, the criticality Gantt, the near-critical table and the risk-to-critical-path prose | The cross-validation gate table, up front. The `.docx` carries one sentence of it, in the audit trail |
| The headline apparatus: the Stage 3 percentile table, the comparison against first-principles rules of thumb, and the component breakdown of cost, schedule and diversification | The reconciliation page comparing the headline against those same first-principles approaches, with the waterfall |
| The confidence-curve table, and the event-risk cost distribution charts | The full cost-driver table, where the `.docx` shows the top five |
| - | The list of artefacts the run wrote, with each input's digest and the method used |

Both open on a front page: the project's title, the product line (Ridgeline, a CBL Analytics
product) and, for Tropic Ridge, the statement that the project is synthetic. The HTML's front
page also carries the run's identity.

The Stage 3 standalone pair is asymmetric in the same way: its `.docx` is the full report plus a
six-part criticality appendix, while its `.html` is a one-page summary rather than a mirror.

If you are sending one document to a client, it is the executive summary `.docx`; keep the HTML as
the run's own record, and read both before you rely on either.

**Same-date runs overwrite.** Only the Stage 3 standalone pair carries a variant tag. The HTML, the
executive summary and the run cache are keyed by date and project, so a second run on the same day
replaces the first.

### 7.1 The HTML report is an executed notebook

The deliverable is produced by one notebook, `final_runner.ipynb`, and the HTML **is** that notebook
executed and rendered. `RUN_FINAL.bat` runs it through nbconvert; the notebook itself is thin, and
calls `src/final/deliverable.py` for everything. There is no second report path: the standalone
schedule run and the integrated run are cells of this one, and the three earlier runners are
retired.

What this means in practice:

- **Code cells are hidden by default.** The HTML reads as a report. Pass `--show-code` to keep the
  executed code visible, which is the form to use when someone wants to see what ran.
- **A failed run still produces the report.** nbconvert is run with `--allow-errors` deliberately:
  the notebook's last cell raises when cross-validation fails, and without the flag the conversion
  would abort and no HTML would exist at all. The banner, not the absence of a file, is how a
  failed run announces itself (§6.3).
- **The executed notebook is not saved as an artefact.** You get the HTML, the Word documents and
  the run cache - not an `.ipynb` carrying its outputs. If you want the notebook itself as a
  deliverable, that is a product change, not a setting.
- **There is no PDF**, by rule.

Reproducing a run means re-running it from the recorded inputs and commit (§7.2 and §14),
not re-opening a saved notebook.

### 7.2 `provenance.json` - what makes a run evidence

| Field | Why it matters |
|---|---|
| `engine_sha`, `engine_tree_dirty` | The commit, and whether the working tree was modified. **`engine_tree_dirty: true` means the run is not evidence** - the stamp is taken at the end, so even a file edited while the run was going counts |
| `input_sha256` | A digest each for the register, the `.xer` and the strawman |
| `params` | Iterations, seed, day rate, reporting P-level, programme days, the Mode multipliers, the CG coefficients and the four calibration tolerances |
| `cross_validation_all_pass` | The gate's verdict |
| `run_token`, `timestamp`, `run_date`, `project` | One token per invocation, so a gate cannot pass against an earlier run on the same day |
| `artefacts` | The files the deliverable wrote: the Word documents, the Stage 3 pair, the run-cache directory, the engine log and the diagnostic. Not `provenance.json` itself, and not the HTML, which the notebook conversion writes afterwards |
| `stage3_standalone_error` | Empty when the Stage 3 pair was written. Otherwise the reason it was not - and then the run **fails even if all four cross-validation checks passed**, because `cross_validation_all_pass` is the four checks *and* this being empty. A FAIL with four passing checks is this field |

The full gate text, including the tie line, is `cv_result.interpretation` in `metadata.json`. It is
not printed to the console and not in the HTML.

## 8. Reading the deliverable

### 8.1 The executive summary, section by section

Eleven level-1 sections, in this order. This list and
`src/final/presentation_contract.py` are the same list, checked by the same test
(`tests/test_presentation_contract.py`): if one moves without the other, both go red.
Contract version **1.4**.

1. **Executive summary** - the recommended contingency, one sentence, with the basis named.
2. **Headline contingency (P80, Stage 3)** - the percentile block, and the comparison against
   first-principles rules of thumb. A project whose binding declares a target-cost contract reads
   *Headline TOC contingency*; the wording follows the contract shape, not the project.
3. **Distribution shape** - led, where the register enables Layer 1, by the total-cost S-curve
   (base + event-risk cost + delay cost) and its contingency table; then the integrated
   contingency S-curve and build-up, the confidence curve, the confidence-band waterfall, and the
   cost and schedule distributions.
4. **Main report** - the body.
5. **Risk drivers - cost** - the cost tornado and the ranked contributors.
6. **Risk drivers - schedule** - the schedule drivers, the Mode sensitivity and the RBS breakdown.
7. **Activity-level criticality** - criticality indices, the near-critical activities, and how the
   top risks land on them.
8. **Action implications** - treatments and their effect, where the register carries them.
9. **Methodology and caveats** - including the convergence diagnostic.
10. **Appendix** - the criticality detail and the risk-to-activity bridge table.
11. **Audit trail** - inputs, hashes, parameters and the cross-validation result.

### 8.2 The headline, and the comparator

The headline is the **Stage 3** integrated cost-plus-schedule contingency at P80: one distribution,
from a CPM replay, with its basis stated on the page. P50 and P95 are reported around it.

The **Stage 2.5 Mode-scenario figures appear as a labelled comparator** and are never the headline.
Where you see two integrated P80 figures, that is the intent: one distribution, one comparator.

### 8.3 The cross-validation gate

Four checks run after the engines and before the report is composed. All four use the register's own
tolerances, and **all four must pass** or the run exits 1 with every artefact bannered.

| Check | What it compares |
|---|---|
| 1, cost calibration | The integrated cost mean against the standalone cost mean. Passes on dollars **or** per cent |
| 2, schedule cross-surface | The deliverable's Stage 3 P80 delay against the **period engine's** Stage 3 P80 delay, on the same inputs. Passes on days or per cent. This is the limb that keeps the deliverable and the app agreeing |
| 3, top-3 cost drivers | The same three risks, in the same order, cost-only against integrated |
| 4, top-3 schedule drivers | The same three, ranked by probability-weighted mean contribution on the register's Mode basis. A rank may **tie** within the register's tie band and still pass |

Check 4 ranks the Stage 3 cost arm's additive, Mode-scaled per-risk draws - **not** the CPM replay
itself. Per-activity attribution from the replay is not built yet, so the schedule driver ranking is
not gated against the headline engine.

### 8.4 The convergence diagnostic

The deliverable charts a 95% confidence band around the **integrated cost P80**, by block bootstrap
from 1,000 up to the run's iteration count. It answers "have I run enough iterations", which is
Monte Carlo error - not model uncertainty, and not a confidence interval on the project's outcome.

If the chart is absent, its failure was caught and logged rather than raised.

### 8.5 Model validation

In the **Stage 3 standalone `.docx`**, under *Methodology and caveats*. Not in the executive summary
or either HTML.

It asks whether the simulation did what the register asked. That is a different question from
cross-validation (§8.3), which asks whether two surfaces agree with each other: two surfaces can
agree and both mis-sample.

| Table | Compares |
|---|---|
| Realised firing | How often each risk fired, against its `Probability`. One table serves both arms, and the section checks on every run that the schedule simulation fired on exactly the cost simulation's decisions; if it did not, the page carries a WARNING |
| Sampled magnitude | The mean impact over the iterations where the risk fired, against the mean of the distribution the register declares for it |

Three things to know before reading a difference as a defect:

- **The two arms fire on one draw.** Realised firing is one table because it is one set of
  decisions. A WARNING under the table means a run broke that, and is a defect to raise.
- **Firing is measured after chain logic.** A risk that a chain resamples at an elevated
  probability should fire more often than its register cell. A difference on such a risk is the
  chain working.
- **The elicited mean follows the risk's `Distribution` column.** PERT, triangular, lognormal and
  binary have different means for the same three points, which is why the row names it. A risk
  that never fired says *Did not fire* rather than showing a zero.

A difference that persists on an unchained risk as iterations rise is worth raising. The
distributions and chains themselves are `METHODOLOGY.md` §3.2 and §3.4.

### 8.6 What correlation contributes

Also in the **Stage 3 standalone `.docx`**, under *Methodology and caveats*. Two tables, answering
two different questions; neither substitutes for the other.

**Does correlation matter here at all?** The bounding table re-runs the cost arm with every
correlation group's coefficient at zero, and again at one, and reports P50, P80 and P90 for zero,
the register's elicited values, and full correlation - with the gap from zero to full in dollars
and as a share of the elicited result. This is the sensitivity test the Commonwealth guidance
prescribes (GN3A §4.1), and the page states its decision rule: a negligible gap means correlation
can be ignored; otherwise the level of correlation should be examined, discussed and documented by
the project team. **What counts as negligible is the project team's judgement.** The report sets
no threshold.

**Which group drives the spread?** The variance-share table drops each correlation group's risks
together and reports the share of portfolio variance the project loses.

What the page may also say:

- **A scope note.** The bounding varies the correlation-group coefficients, which correlate
  *firing* within a group. That is narrower than the guidance's "each model input", and the page
  says so.
- **Groups the register does not name.** A risk carrying a group the coefficient block omits ran
  at the engine's default of 0.50. The bounds are still true bounds, but the elicited row rests on
  that default for those groups, and the page lists them. Fill the coefficient block.
- **Correlation bounding not reported.** The bounding is printed only when its elicited re-run
  reproduces the run's own cost arm exactly. If it does not, the section is withheld with that
  reason, rather than printing a gap that could not be attributed to correlation alone.

The arithmetic is `METHODOLOGY.md` §3.7.

### 8.7 Basis of estimate

A **Basis of estimate** column on the cost and schedule driver tables, in the executive summary,
the Stage 3 standalone `.docx`, and the HTML's driver pages. It is the register's own free text
saying where each three-point estimate came from, printed unmodified.

The register carries that header twice, and the two are different claims about different numbers:
the cost table reads the Contingent section's, and the schedule table reads the Time section's. A
blank cell prints **Not recorded** - never an empty cell, which a reader could take for "nothing to
note". No vocabulary is enforced.

### 8.8 The run diagnostic

`run_diagnostic_<date>.txt`, in the run's folder beside `provenance.json`. One page of plain text:
readable with no tooling, and comparable between two runs with any diff tool. It is written from
what the run already holds, so it cannot disagree with the provenance beside it. It is written on a
fail as well as a pass, and a failed run carries its FAIL banner at both the top and the bottom -
including a run whose four checks passed but whose Stage 3 pair was not written, because the
verdict is the run's, the one the exit code reports.

In order:

- the verdict, the project, date and run token;
- the **Stage 3 headline** with its percentiles and basis;
- the top three cost and schedule drivers, each beside the measure its table is ranked by - the
  P80 (or Mean) contribution in dollars for cost, probability times mean impact in days for
  schedule;
- **the gate**: the four checks of §8.3, each PASS or FAIL, with check 2 saying which basis it ran
  on. A Stage 3 pair that was not written is its own FAIL line, with the reason. A failure with no
  failing line says so, and points at `cv_result.interpretation` in `metadata.json`;
- the provenance - engine commit, whether the tree was clean, iterations, seed, and each input's
  digest with the method it was taken by;
- every artefact the run wrote.

To re-render an earlier run's diagnostic from its cache - after the file is deleted, or when the
formatter changes - use `scripts/run_diagnostic.py`; the command is in `docs/run-recipes.md`. It
does not re-run the engines, and a missing cache is an error rather than a fresh run.

---

# Part C - the period cycle and the app

Once a deliverable is issued, the project is tracked month by month: freeze the data, update the
status workbook, run the period, review the movement, publish, and discuss. The full cycle is
`docs/PLAYBOOK.md` Part B.

## 9. The status workbook

The monthly input. It is **generated from the register** by `scripts/build_status_workbook.py`, and
carries no formatting and no notes: it is a contract, and nothing else.

It selects every register risk that is Open **and** Time Impact = Yes, and refuses loudly on a
missing header, on zero tracked risks, on a blank `Probability`, or on overflow: at most
**16 tracked risks** and **26 milestones**, because the reader scans exactly those rows.

Four sheets:

| Sheet | What you edit each period |
|---|---|
| `Risk Register` | A helper sheet with the risk IDs and an `AM_Include` column |
| `AM_Period_Status` | The metadata block in B1 to B8 - period end, previous period, phase, analyst, reviewer, notes - and then one row per tracked risk from row 15: status this period, dates, and the probability and Mode overrides |
| `AM_Milestones` | Status and per cent complete, from row 5 |
| `AM_Mitigation_Log` | Proposed mitigations with cost, lead time and estimated days saved |

A risk newly entered in the register this period is added here as a row with its risk ID. The
register remains the source of truth for the risk itself.

## 10. Running and publishing a period

### 10.1 `RUN_PERIOD.bat`

Takes the status workbook, plus `--register`, `--xer` and `--strawman`, and needs `QRA_PROJECT` set.
It writes `data\<binding key>\period_<YYYYMMDD>.json`.

It **refuses to run on a dirty working tree**: a period is evidence, and must come from a clean
checkout. `--allow-dirty` exists for smoke runs and stamps the JSON as non-clean.

`--main-iter` sets the main run's iteration count, `--days-at-risk-iter` and
`--counterfactual-iter` set the two sweeps' counts, and `--seed` sets the seed.

### 10.2 The period JSON

Schema version **1.4**. Eleven top-level keys: `schema_version`, `meta`, `headline`, `trend`,
`risks`, `mitigations`, `activities`, `distribution`, `delta`, `audit`, and `integrated`.

`meta` carries the same provenance as the deliverable - engine SHA, tree-dirty flag, and a digest
each for the register, the `.xer` and the workbook - plus `previous_period_end_date`, which is what
populates the trend and delta blocks. A first period has none, and the app says so.

### 10.3 `PUBLISH_PERIOD.bat`

Validates the JSON **before** copying it: all blocks present, the schema version equal to the
engine's own constant, and the project key matching. It refuses:
- a period whose date already exists, unless you pass `--replace`;
- a `--project` that disagrees with the file;
- a period with no, or an invalid, `meta.project_key` (it does not say whose it is);
- a project that is not named for publication (or is confidential).

Each refusal prints `PUBLISH REFUSED`, and nothing is filed.

Then it copies the JSON into the app's data directory and builds the site. It prints **`Built, NOT
deployed`**, then the four steps a preview deploy runs, each with the directory it runs from:
- `build_guard.py clear` (repository root);
- `vercel build` (the dashboard);
- `build_guard.py check` (repository root);
- `vercel deploy --prebuilt` (the dashboard).

After them it prints the production sequence, the same four steps with `--prod`, which is a separate
step.

**`--deploy` is the only step that cannot be checked before it runs, and it is the publisher's call.**

## 11. The web app

A static Next.js export. It reads the period JSON and nothing else - no server, no API, no live
data.

| Route | What it shows |
|---|---|
| `/` | Where we are: the P80 forecast finish against the deterministic baseline, the percentile row, open, fired and closed counts, the integrated event-risk cost, near-critical milestones, and the P80 trend |
| `/risks/` | What is driving risk: the risk table with per-risk detail |
| `/mitigations/` | What we could do: baseline against mitigated, with mitigation cards |
| `/changes/` | What changed: P80 movement, and what got worse, better or new |
| `/analyst/` | S-curve, histogram, percentile table |
| `/analyst/drivers/` | Tornado and sensitivity charts, with metric definitions |
| `/analyst/activities/` | The stochastic Gantt by criticality, and critical-path statistics |
| `/analyst/audit/` | Engine configuration, the calibration gates, methodology notes |

Serve the built site locally with any static server, and open it with `?project=<binding key>`.
The command is in `docs/PLAYBOOK.md` step 7.

**Three refusals, by design**: the schema version must equal the version the app was built for, the
period's project key must match the directory serving it, and the filename must match the period
pattern. A mismatch is an error on the page, not a silent wrong number.

The footer carries the engine SHA and shows an "uncommitted changes" chip when the period came from
a dirty tree. A banner warns when the period is older than the seven-working-day service level.

**Access control is Vercel-side only.** The app has no login, no route guard and no permission
boundary; the PM and Analyst toggle is a view, not a permission. Whoever can reach the URL sees
everything the period JSON contains. Deployment protection is configured in Vercel by whoever owns the deployment.

---

# Part D - reference

## 12. Current state and its caveats

**Stage 3 is the production headline** (since 11 September 2026): one distribution from a
per-iteration CPM replay, with Mode multipliers off, because a multiplier on top of a replay would
double-count. Stage 2.5 - the Mode-multiplier approximation - is retained as a labelled comparator
for continuity with earlier reporting.

Two caveats travel with every Stage 3 figure today, and the deliverable states them on its own face:

1. **Risk-to-activity bindings are auto-mapped, not workshop-validated.** The auto-mapper expands
   each risk's prefix to the activities under it; a workshop has not yet confirmed those bindings.
   The executive summary carries this as a banner.
2. **One project-default calendar** is used for the whole network, rather than per-activity
   calendars from the `.xer`.

A third gap is in the method itself rather than printed as a caveat: the schedule's duration distribution does not feed the cost model; cost and schedule are joint-sampled, and the schedule is dollarised at the project's day rate
(`METHODOLOGY.md` §7.3).

The history of how Stage 2.5 and Stage 3 relate, and the mathematics of both, are in
`METHODOLOGY.md`.

## 13. Limitations and known gaps

- **`MC_Params` C15 is not asserted.** The count of Time Impact = Yes risks is read and recorded,
  but nothing compares it to the register today. Treat it as documentation, not a guard.
- **`Risk Status` does not filter.** Use `MC Include` for the cost arm and `Time Impact` for the
  schedule arm.
- **Recurrence is not parameterised** from a scaffolded register. The integrated engine treats every
  risk as single-occurrence.
- **The schedule driver ranking is not attributed to the CPM replay** (§8.3, check 4).
- **Layer 1 does not reach the deliverable.** It is Tier 1 only.
- **Out of scope entirely**: liquidated damages, probabilistic escalation, interest during
  construction, time-phased cash flow, and risk identification.

## 14. Reproducibility

Every production run records what it ran on: the engine commit and whether the tree was clean, a
digest per input file, every parameter, the scenarios run and the gate's verdict - in
`provenance.json`, beside a state cache that holds the composed result and the raw arrays.

Re-running the same commit, the same inputs and the same seed reproduces the numbers within Monte
Carlo noise. The engine additionally self-verifies against committed reference numbers on every
commit, so a headline that moves without an approved methodology change fails before it can ship.

## 15. Glossary

| Term | Meaning |
|---|---|
| **Base estimate** | The project cost before contingency and escalation. Labelled TIC on `MC_Params` |
| **Binding key** | The project's identifier: a module filename under `src/sra/cpm/bindings/` |
| **CG** | Correlation group: risks whose cost outcomes move together |
| **Criticality index** | The share of iterations in which an activity lands on the critical path |
| **Dual-coded risk** | A risk with both a cost and a schedule impact |
| **EMV** | Expected monetary value: probability times expected impact |
| **Integrated** | Cost and schedule simulated together, sharing one severity draw per risk |
| **Mode** | How a delay combines with others: Series, Hybrid or Parallel. Stage 2.5 only |
| **P80** | The value 80% of simulated outcomes fall below |
| **Period** | One month of the tracking cycle, and its JSON |
| **Stage 2.5 / Stage 3** | The Mode-multiplier approximation, and the full CPM replay |
| **Strawman** | Historically a separate schedule workbook; now dissolved into the register |
| **Tier 1** | The cost engine running in Excel through xlwings Lite |

---

## Appendix A - where everything else lives

| Document | What it is for |
|---|---|
| `docs/PLAYBOOK.md` | The procedure: every command, with its expected result and what to do when it differs |
| `METHODOLOGY.md` | The mathematics of the four components and the integrated engine |
| `ARCHITECTURE.md` | Module map, data flow and interface contracts, for developers |
| `README.md` | Install, setup and the run recipes |
