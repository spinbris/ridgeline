@echo off
REM Publish one period to the dashboard.
REM
REM Usage:
REM   PUBLISH_PERIOD.bat <path-to-period_YYYYMMDD.json> [--project KEY] [--deploy]
REM
REM Validates the period against the contract this build publishes, files it under
REM data\<project>\, and rebuilds the static export. Without --deploy it stops after the
REM build and prints the four steps --deploy runs to a preview (clear, vercel build, the
REM build-output guard, vercel deploy --prebuilt), then the production four. The deploy step
REM is opt-in because it is the one step that cannot be checked before it runs.
REM
REM Producing a period is a separate job: RUN_PERIOD.bat.

if "%~1"=="" (
    echo Usage: PUBLISH_PERIOD.bat ^<path-to-period_YYYYMMDD.json^> [--project KEY] [--deploy]
    echo.
    echo   Publishes an existing period JSON. To PRODUCE one, use RUN_PERIOD.bat.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe not found.
    echo Create the environment first - this script does not guess an interpreter.
    exit /b 1
)

.venv\Scripts\python.exe -m src.am.publish_period %*
exit /b %ERRORLEVEL%
