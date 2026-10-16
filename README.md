# Ridgeline

**Ridgeline: cost and schedule risk for capital projects, from bid to handover. A CBL Analytics
product.**

Ridgeline is quantitative risk analysis for capital projects: cost risk, schedule risk, the
integrated cost-plus-schedule result, and the management of that result month by month over the
life of a project. It computes the contingency. **Its deliverable presents the event-risk
contingency.** The base estimate is an input; the owner view's distribution of base plus
contingency is an output; escalation is a documented hand-off.

**What ships:** the engine, the report, the monthly dashboard app, and two synthetic projects to
run them on - *Tropic Ridge*, a wind farm and the showcase, and *Kestrel Highway*, a road upgrade.
Every number they produce comes from synthetic data. Your own project's register and schedule are
your data, and stay in folders that are never committed (see [Your data](#your-data)).

**To start**, install from the lock file and run the showcase:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-lock-20260901-py312.txt
$env:QRA_PROJECT = "synthetic_wind"
$env:REGISTER_FILE = "tests\fixtures\synthetic_wind\wind_register.xlsx"
$env:P6_FILE = "tests\fixtures\synthetic_wind\wind_schedule.xer"
$env:STRAWMAN_FILE = "tests\fixtures\synthetic_wind\wind_register.xlsx"
.\RUN_FINAL.bat --headline both
```

The full walkthrough - install, setting up a project from its workshop output, the report, and the
monthly period cycle with the app - is [`docs/PLAYBOOK.md`](./docs/PLAYBOOK.md). Every surface,
input and output is described in [`docs/SOFTWARE_USER_GUIDE.md`](./docs/SOFTWARE_USER_GUIDE.md).
The method in mathematical detail is [`METHODOLOGY.md`](./METHODOLOGY.md); the codebase layout and
data flow are [`ARCHITECTURE.md`](./ARCHITECTURE.md); persistence, memory and archive decisions are
[`SCALABILITY.md`](./SCALABILITY.md).

The repository is named `outturn`. The name is a label, not a claim about what the software
computes.

## The method in one paragraph

Ridgeline combines four analytical components - **deterministic QRA, Monte Carlo QRA,
deterministic SRA and Monte Carlo SRA** - into one integrated cost-plus-schedule deliverable. The
deterministic layers live in Excel workbooks (the project's risk register and its schedule
methodology workbook); the Monte Carlo layers and the integration are Python, run from a Jupyter
notebook. The method is anchored in **AACE International 132R-23 - *Schedule Risk Analysis Maturity
Model*** (May 2024) and the Australian Department of Infrastructure *Cost Estimation Guidance
Notes* v2.0 (November 2023), in particular Guidance Note 3A. The headline is **Stage 3**: a
per-iteration Monte Carlo simulation of the CPM schedule, whose single distribution carries the
deliverable's headline. An earlier, simpler schedule approximation (Stage 2.5) is kept beside it
as a labelled comparator, never the headline. Two caveats travel with every Stage 3 figure, and the
deliverable states both on its own face: risk-to-activity bindings are auto-mapped rather than
workshop-validated, and a single project-default calendar is used
([`docs/SOFTWARE_USER_GUIDE.md`](./docs/SOFTWARE_USER_GUIDE.md) §12). A third gap is in the method
itself: the schedule's duration distribution does not feed the cost model; cost and schedule are joint-sampled, and the schedule is dollarised at the project's day rate (`METHODOLOGY.md` §7.3).

Each project is a **binding** (`src/sra/cpm/bindings/`) declaring its own register, schedule and
strawman. There is no default project: an unset selection fails loud.

## The four components at a glance

| Component | Lives in | Produces |
|---|---|---|
| Deterministic QRA | The project's register workbook (Risk Register, EMV Summary, EMV Tornado, Risk Matrix, Top 20, Pareto Analysis, Risk Analysis sheets) | Per-risk Inherent EMV, Contingent EMV (simple and PERT), totals by RBS, Current and Residual P x C scoring |
| Monte Carlo QRA | `src/simulation.py` (cost engine) — exposed through `final_runner.ipynb` | Event-risk (Layer 2) cost distribution in the deliverable; base plus contingency (Layer 1 + Layer 2) on the Tier 1 owner view, where the register enables Layer 1; tornado decomposition, owner-view splits (BOP / counterparty / Whole-project), S-curve, contingency adequacy |
| Deterministic SRA | The project's strawman workbook (Risk_Scope, Run_Config_Preview - `MC_Params` in a consolidated register - P6_Processed, Mapping, Methodology sheets) | Per-risk Mode classification (Series/Hybrid/Parallel), EMV days (simple and PERT), finish-delay contribution in days and dollars, Comparator 1 and Comparator 2 calibration targets |
| Monte Carlo SRA | `src/sra/sra_simulation.py` (schedule engine) — exposed through `final_runner.ipynb` | Finish-delay-days distribution, P-level percentiles, criticality table, the Mode counterfactual sweep (five base scenarios plus one per Time=Yes risk), single-scenario transparency walkthrough |
| Integrated solution | `src/integrated/integrated_simulation.py` + `src/final/composer.py` — exposed through `final_runner.ipynb` (the client deliverable, and the only report path) | Joint cost+schedule distribution, marginal calibration gates, diversification benefit at P80, cross-validated client HTML and Word report (an eleven-section executive summary plus drilldowns and appendices) |

The cost engine, the schedule engine and the integrated engine all read the **same register** for the active project, so probabilities, distributions and PERT parameters cannot drift between layers. The integrated engine joint-samples the **dual-coded (Time=Yes) risks** — one fire decision and one severity uniform per iteration, shared across cost and schedule — while cost-only risks draw independent uniforms. How many risks fall each side is the project's own fact and comes from its register. See `METHODOLOGY.md` Section 6 for the joint-sampling math.

## Inputs

Three inputs per project, each declared in the project's binding. **For the deliverable, set four
environment variables:** `QRA_PROJECT` (the binding), `REGISTER_FILE`, `P6_FILE` and
`STRAWMAN_FILE`. It refuses to start if a path is missing.

| Input | What it carries | Role |
|---|---|---|
| Risk register (`.xlsx`) | The deterministic QRA scoring (Current and Residual P x C, EMV simple, EMV PERT), the MC bridge fields (Probability, Optimistic / Most Likely / Pessimistic cost, Opt/ML/Pess days, Distribution, Correlation Group, Recurrence Type, MC Include) and the methodology named ranges | Single source of truth for all risks |
| P6 schedule (`.xer`) | The full Primavera export: every activity, milestone and logic link | Stage 3's CPM replay; a longest-path `.xlsx` subset is retained as a sanity check |
| SRA strawman (`.xlsx`) | Mode classifications, day rate, programme dates, calibration targets (Comparator 1 / 2), `Risk_Scope` (the dual-coded risks with Probability, Opt/ML/Pess days, Mode_Aggregated) and the run settings (iterations, day rate, P-level reporting) - in the register's `MC_Params` sheet when the strawman is part of the register, as in both shipped projects, or a separate strawman's `Run_Config_Preview` | The SRA methodology workbook |

The period run takes its inputs as flags instead: `--register`, `--xer` and `--strawman` ([`docs/PLAYBOOK.md`](./docs/PLAYBOOK.md) step 7).

## Setup

The project supports two environments depending on whether you need the legacy xlwings-driven Excel workflow or just the notebook stack.

```powershell
# Notebook-only (recommended; no Excel required for the MC layers)
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements_client.txt

# Full stack including xlwings (only needed for the legacy MC_Dashboard + VBA RunMC button)
pip install -r requirements.txt
```

**Python 3.12 or newer is required**, and `pyproject.toml` enforces it (`requires-python =
">=3.12"`). 3.12 is what the lock pins, what the test suite runs on, and what every committed
number was produced on. The Monte Carlo engines run in memory; no Excel installation is needed for
the deliverable notebook.

**To reproduce the committed reference numbers, install from the lock file instead.** The
requirements files above carry `>=` floors, so a fresh resolution today can pull versions the
reference numbers were never produced on, and the test suite checks those numbers for exact
equality:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-lock-20260901-py312.txt
pytest -m golden          # expect 3 passed
```

`requirements-lock-20260901-py312.txt` is the closure this repository was built and tested on
(Python 3.12.4, numpy 1.26.4, scipy 1.16.3, pandas 2.3.3), wheels-only.

> **The lock is a Windows cut; off Windows it installs but is not a full closure.** Its one
> Windows-only pin, `pywin32`, carries a `sys_platform == "win32"` marker, so the install above
> works on macOS and Linux too. There, POSIX-only dependencies it does not pin resolve at install:
> `pexpect` and `ptyprocess` on both, `appnope` and `appscript` on macOS. Run `pytest -m golden` to
> confirm it reproduces the reference numbers before you trust a non-Windows install. On arm64
> (Apple silicon) the reference numbers hold, but two tests that pin exact samples move by 1-2
> units in the last place.

## Running the deliverable

**One notebook, and it is the only report path.** `final_runner.ipynb` lives at the repository
root. Earlier per-component notebooks are retired; the standalone schedule and integrated runs are
cells of this one.

It is thin by design: it calls `src/final/deliverable`, which runs the engines in memory, then
cross-validation, then composes the report, the Word summary and the Stage 3 standalone pair, and
writes the state cache and the provenance; the notebook renders the result.

### Running it

`RUN_FINAL.bat` sets nothing it was not given. There is no default project and no input path in
it: every one comes from the environment, and an unset one is refused rather than guessed.

```bat
set QRA_PROJECT=synthetic_wind
set REGISTER_FILE=tests\fixtures\synthetic_wind\wind_register.xlsx
set P6_FILE=tests\fixtures\synthetic_wind\wind_schedule.xer
set STRAWMAN_FILE=tests\fixtures\synthetic_wind\wind_register.xlsx
RUN_FINAL.bat --headline both
```

It refuses to start if a path is missing.

### What it produces

`outputs\<project>_deliverable_<date>.html`, a Word executive summary per headline metric, the
Stage 3 standalone docx+html pair, and `outputs\runs\<date>_<project>\` holding the state
cache and `provenance.json`. There is no PDF: if one is needed, print the Word file.

Every file, and what it is for: [`docs/SOFTWARE_USER_GUIDE.md`](./docs/SOFTWARE_USER_GUIDE.md) §7.
To re-render a run's one-page diagnostic from its state cache:

```powershell
python scripts\run_diagnostic.py --project <project-key> --run-date YYYY-MM-DD
```

### Exit codes, and why they matter

| | |
|---|---|
| `0` | cross-validation passed |
| `1` | cross-validation **FAILED**. Every artefact was still written and carries the FAIL banner: the run writes, then fails. Do not use those artefacts as results |
| `2` | the run did not complete — a precondition was unmet, or it stopped before writing its manifest |

`1` and `2` are deliberately different: `1` means there are bannered artefacts on disk to
investigate, `2` means there are not.

### Options

`--headline P80|Mean|both` and `--show-code` (keeps code cells in the HTML). The deliverable runs
in production mode only; `FINAL_REPORT_MODE=dev` is refused rather than silently honoured. For a
quicker smoke run, set `SR9_ITERATIONS` to a small number (for example 1000) to run end to end in
seconds rather than minutes.

### Headless cost-only entry point

The cost engine can be driven directly for ad-hoc cost-only runs, no notebook needed:
`src.tier1_headless.run_headless_from_workbook(workbook_path, risk_id_prefix=...)`. It takes the
workbook and the project's risk-ID prefix as arguments.

## Tests

```powershell
# Fast lane (default; skips slow notebook smoke tests)
python -m pytest tests/ -v -m "not slow"

# Full suite (includes ~5k-iter end-to-end notebook tests; needs strawman + register inputs)
python -m pytest tests/ -v
```

The full suite must remain green. A handful of tests are slow because they exercise full
simulation runs at reduced iteration counts; the `slow` marker partitions them out for fast
feedback.

### Golden-number regression harness

The engine has a self-verification loop that locks the headline numbers (P50/P80/P90/mean) against
silent drift. A moved headline is a bug unless it is an approved methodology change.

```powershell
# Run the golden gate (fast; seeded, n=10,000)
python -m pytest -m golden

# See current vs blessed numbers without changing anything (diff mode)
python scripts/bless_goldens.py
```

- **Two tiers, chosen by data, not code.** `tests/golden/projects.toml` is the registry: each
  project row carries a `confidential` flag. A public project, such as the synthetic *Tropic Ridge*
  showcase, blesses to the committed `tests/golden/manifests/` tier and always runs, including on a
  fresh clone or in CI. A confidential project blesses to a tier that is never committed, and runs
  only on a machine where `QRA_GOLDEN_LOCAL=1` is set. Both shipped projects are public. Where the
  tier is armed, a missing or moved manifest **or input** is a hard failure, never a silent pass.
- **A red golden means a headline number moved.** Stop and read the old-vs-new diff. Do not adjust
  the manifest or add a tolerance. Numbers move only through `python scripts/bless_goldens.py
  --approve --reason "..."`, which is a methodology decision, made deliberately.
- **Adding a project** is a registry row and a bless, with no code change, for a project that
  reuses an existing engine entry.
- **Before a commit:** `pytest -m golden` takes seconds, and a secret scan (gitleaks) catches a
  credential before it is committed.

## Repository layout

```text
outturn/
├── README.md                      # this file
├── METHODOLOGY.md                 # the four components in mathematical detail
├── ARCHITECTURE.md                # module layout and data flow
├── SCALABILITY.md                 # persistence, memory and archive decisions
├── requirements.txt               # full stack (incl. xlwings)
├── requirements_client.txt        # notebook-only stack
├── requirements-lock-20260901-py312.txt  # the exact closure the reference numbers were made on
├── RUN_FINAL.bat                  # the one deliverable entry point
├── final_runner.ipynb             # the deliverable notebook
├── dashboard/                     # the monthly dashboard app (Next.js static export)
├── outputs/
│   ├── charts/                    # PNGs emitted by composer.py
│   ├── runs/<date>_<project>/     # state cache + provenance.json, one per run
│   └── *.html, *.docx             # report deliverables
├── src/                           # see ARCHITECTURE.md for full module map
├── scripts/                       # diagnostics, workbook builders, release checks
├── tests/                         # pytest suite and the two synthetic projects' fixtures
└── docs/
    ├── PLAYBOOK.md                # the walkthrough
    └── SOFTWARE_USER_GUIDE.md     # every surface, input and output
```

## Standards and methodology references

The method is anchored in two aligned industry references:

**AACE International** (international):

- AACE PGD-02 — *Guide to Quantitative Risk Analysis*
- AACE 122R-22 — *Quantitative Risk Analysis Maturity Model*
- AACE 132R-23 — *Schedule Risk Analysis Maturity Model* (May 2024) — defines maturity Levels 0-5
- AACE 57R-09 — *Integrated Cost and Schedule Risk Analysis Using Risk Drivers and Monte Carlo Simulation of a CPM Model* — the canonical Level 3 reference
- AACE 117R-21 / 118R-21 / 123R-22 / 113R-20 — supporting RPs on integrated and ranging-based methods

**Australian Department of Infrastructure** (v2.0, November 2023):

- *Guidance Note — Overview*
- *Guidance Note 1 — Project Scope*
- *Guidance Note 2 — Base Cost Estimation*
- *Guidance Note 3A — Probabilistic Contingency Estimation* (and its Supplementary Guidance) — Risk Factor Models 1-4 progression aligns with AACE 132R-23 maturity levels
- *Guidance Note 3B — Deterministic Contingency Estimation*
- *Guidance Note 4 — Escalation*

Supporting references:

- ISO 31000:2018 — *Risk management — guidelines*
- Engineers Australia Risk Engineering Society (RES) *Contingency Guideline* v2 (Feb 2019) — referenced by both AACE and GN3A for First Principles Risk Analysis

## Your data

Everything that ships is synthetic: the two projects, their registers and schedules, and every
committed reference number. Nothing in this repository is a real project's data.

A project of your own is your data. Keep its register, schedule and outputs in folders the
repository never commits: `outputs/` and `data/` are gitignored, and a confidential project's
reference numbers bless to a tier that is never committed. The test suite and the pre-commit hook
fail loudly if a confidential project's manifest is ever staged.

## Licence

Ridgeline is source-available under the [Business Source License 1.1](./LICENSE). You may read,
copy, modify and run it for any non-production purpose, such as evaluating, testing or learning
from it. Any production use, including running it on a real project, on a paid engagement or as a
service, and including use by government bodies, needs a separate licence from the copyright
holder, Stephen Parton, through CBL Analytics. Each version converts to the Apache License 2.0
four years after it is published.
