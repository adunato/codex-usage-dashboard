@echo off
setlocal
set "CODEX_DASHBOARD_NO_BROWSER=1"
cd /d "%~dp0"
if defined CODEX_DASHBOARD_PYTHON goto run_pinned
set "PYTHON="
python --version >nul 2>&1
if not errorlevel 1 set "PYTHON=python"
if not defined PYTHON (
  py -3 --version >nul 2>&1
  if not errorlevel 1 set "PYTHON=py -3"
)
if not defined PYTHON (
  echo Python could not be found. Install Python 3, then double-click this file again.
  pause
  exit /b 1
)
%PYTHON% "%~dp0skills\codex-usage-dashboard\scripts\open_dashboard.py"
goto check_result
:run_pinned
"%CODEX_DASHBOARD_PYTHON%" "%~dp0skills\codex-usage-dashboard\scripts\open_dashboard.py"
:check_result
if errorlevel 1 (
  echo.
  echo The dashboard could not be opened. Please try again or ask for help.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8765/"
timeout /t 3 /nobreak >nul 2>&1
exit /b 0
