@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM  The deliverable. One entry point, one report path.
REM
REM  This file sets NOTHING it was not given. There is no default project and no
REM  input path in here: every one comes from the environment, and an unset one
REM  is refused rather than guessed.
REM
REM  Set before running:
REM    QRA_PROJECT     the binding to run, e.g. synthetic_wind
REM    REGISTER_FILE   the register .xlsx
REM    P6_FILE         the P6-derived schedule file
REM    STRAWMAN_FILE   the strawman .xlsx (the register itself where the
REM                    strawman is dissolved into it)
REM
REM  Optional:
REM    FINAL_REPORT_HEADLINE_METRIC   P80 (default) ^| Mean ^| both
REM    SR9_ITERATIONS                 override the register's iteration count
REM    SR9_SEED                       a whole number for a repeatable run; unset, blank or 0
REM                                   draws a random seed, recorded in provenance.json
REM
REM  Usage:
REM    RUN_FINAL.bat                     P80, prod
REM    RUN_FINAL.bat --headline both     P80 and Mean
REM    RUN_FINAL.bat --show-code         keep code cells in the HTML
REM
REM  This path runs the production basis, and only that. An earlier development
REM  mode put one project's hardcoded indicative scenario into the headline
REM  slot; it has been retired. Setting FINAL_REPORT_MODE to anything but
REM  'prod' is refused, not ignored.
REM
REM  Outputs (and no others - there is no PDF):
REM    outputs\<project>_deliverable_<date>.html   the report
REM    outputs\*executive_summary*.docx            Word, one per headline metric
REM    outputs\sra_stage3_standalone_*.docx/.html  the Stage 3 standalone pair
REM    outputs\runs\<date>_<project>\              state cache + provenance.json
REM
REM  Exit codes:
REM    0  cross-validation passed
REM    1  cross-validation FAILED - every artefact was still written and carries
REM       the FAIL banner (write, then fail). DO NOT DISTRIBUTE.
REM    2  the run did not complete: a precondition was not met, or it crashed
REM       before writing its manifest. Never confused with 0 - see QRA_RUN_TOKEN
REM       below.
REM ============================================================================

cd /d "%~dp0"

REM ---- Refuse on anything unset, before doing any work -----------------------
set MISSING=
if "%QRA_PROJECT%"=="" set MISSING=!MISSING! QRA_PROJECT
if "%REGISTER_FILE%"=="" set MISSING=!MISSING! REGISTER_FILE
if "%P6_FILE%"=="" set MISSING=!MISSING! P6_FILE
if "%STRAWMAN_FILE%"=="" set MISSING=!MISSING! STRAWMAN_FILE
if not "!MISSING!"=="" (
    echo ERROR: not set:!MISSING!
    echo.
    echo This runner has no default project and no built-in paths. Set the four
    echo variables above and re-run. The notebook's pre-flight will then report
    echo every missing register setting in one message, rather than one per run.
    exit /b 2
)

REM ---- The interpreter is part of what the numbers are --------
REM A bare `python` runs whatever is first on PATH; the goldens and every committed
REM number were produced on the lock's interpreter in .venv.
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe not found. Create the environment from the
    echo lock first - this runner does not guess an interpreter.
    exit /b 2
)

REM ---- Arguments -------------------------------------------------------------
set NO_INPUT_FLAG=--no-input
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--headline" (
    set FINAL_REPORT_HEADLINE_METRIC=%~2
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--show-code" (
    set NO_INPUT_FLAG=
    shift
    goto parse_args
)
echo Unknown argument: %~1
echo Usage: RUN_FINAL.bat [--headline P80^|Mean^|both] [--show-code]
exit /b 2
:args_done

for /f %%a in ('powershell -nologo -command "(get-date).ToString('yyyy-MM-dd')"') do set TODAY=%%a
set REPORT_HTML=outputs\%QRA_PROJECT%_deliverable_%TODAY%.html

REM One token per invocation, stamped into the manifest by the run and checked by
REM the gate below. Without it the gate reads a manifest keyed only by date and
REM project - so a run that crashed today, after a run that passed today, would
REM find the earlier manifest and report ITS pass. A gate that can pass against
REM the wrong artefact is worse than no gate.
REM ---- run token (begin) - the test suite runs this block on its own, so keep it self-contained
REM A token inherited from the calling shell is cleared first: reused, it lets this run's gate
REM find an earlier run's manifest and report that run's verdict. And a token that is still empty
REM after generation - PowerShell blocked or failed - stops the run rather than proceeding unmarked.
set QRA_RUN_TOKEN=
for /f %%t in ('powershell -nologo -command "[guid]::NewGuid().ToString()"') do set QRA_RUN_TOKEN=%%t
if "%QRA_RUN_TOKEN%"=="" (
    echo ERROR: this run's token could not be generated - PowerShell returned nothing.
    echo Without it the gate cannot tell this run's manifest from an earlier one. Stopping.
    exit /b 2
)
REM ---- run token (end)

echo Project:  %QRA_PROJECT%
echo Output:   %REPORT_HTML%
echo.

REM Every input, resolved, before the long run. An existence check alone
REM passes a file from the wrong tree silently; this names each resolved path and flags any
REM outside this working tree. The run's own pre-flight still checks the register settings.
.venv\Scripts\python.exe -m src.final.deliverable_preflight --paths
if errorlevel 1 exit /b 2
echo.

REM ---- Execute ----------------------------------------------------------------
REM --allow-errors is load-bearing and deliberate, not laxity. The notebook's last
REM cell raises when cross-validation failed; without this flag nbconvert aborts
REM and writes no HTML at all, so the one artefact a reader opens would be the
REM one that does not exist - exactly the contradiction the write-then-fail rule exists to avoid.
REM With it the bannered HTML is always written and nbconvert always exits 0, so
REM the run's verdict is read below from the manifest the run itself wrote.
REM The first cell describes this notebook to a developer. It is tagged dev-note and removed
REM here, so the client artefact opens on the project title rather than on the product's own
REM description.
REM report_html.j2 drops MathJax, which typeset "$5.02M at $48,000" as maths.
.venv\Scripts\python.exe -m nbconvert --to html --execute --allow-errors %NO_INPUT_FLAG% ^
    --TagRemovePreprocessor.enabled=True ^
    --TagRemovePreprocessor.remove_cell_tags=dev-note ^
    --template-file report_html.j2 ^
    final_runner.ipynb --output "%REPORT_HTML%"
if errorlevel 1 (
    echo ERROR: the notebook could not be converted at all. See the output above.
    exit /b 2
)


REM ---- The verdict, from what the run wrote ------------------------------------
.venv\Scripts\python.exe -m src.final.deliverable --gate
exit /b %ERRORLEVEL%
