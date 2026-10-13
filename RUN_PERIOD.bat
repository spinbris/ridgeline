@echo off
REM Active Management - monthly cycle runner (this repository)
REM Usage:
REM   RUN_PERIOD.bat <path-to-status-workbook.xlsx>
REM Smoke mode (faster, lower precision):
REM   RUN_PERIOD.bat <workbook> --main-iter 5000 --days-at-risk-iter 500 --counterfactual-iter 500

if "%~1"=="" (
    echo Usage: RUN_PERIOD.bat ^<path-to-status-workbook.xlsx^> [extra flags]
    echo.
    echo Smoke run example:
    echo   RUN_PERIOD.bat status_periods\test_period.xlsx --main-iter 5000
    exit /b 1
)

set WORKBOOK=%~1
shift

set EXTRA_FLAGS=
:gather
if "%~1"=="" goto run
set EXTRA_FLAGS=%EXTRA_FLAGS% %1
shift
goto gather

:run
if "%QRA_PROJECT%"=="" (
  echo ERROR: QRA_PROJECT is not set. This runner selects the project by that env var ^(synthetic_wind or synthetic_road^); there is no default.
  exit /b 1
)
REM Use the repository's own interpreter, never whatever python is first on PATH.
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv\Scripts\python.exe not found. Run from the repository root, with the
  echo environment created from the lock - this script does not guess an interpreter.
  exit /b 1
)
.venv\Scripts\python.exe -m src.am.run_period --workbook "%WORKBOOK%" %EXTRA_FLAGS%
exit /b %ERRORLEVEL%
