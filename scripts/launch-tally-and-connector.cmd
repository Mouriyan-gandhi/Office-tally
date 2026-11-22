@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

echo ========================================================================
echo   Upkar Agency - Auto-Launcher (TallyPrime + Office Connector)
echo ========================================================================
echo.

REM 1. Check if Tally is already running
tasklist /FI "IMAGENAME eq tally.exe" 2>NUL | find /I /N "tally.exe" >NUL
if not errorlevel 1 (
    echo [OK] TallyPrime is already running.
    goto check_connector
)

REM 2. Look for Tally executable in standard installation directories
set "TALLY_PATH="
if exist "C:\Program Files\TallyPrime\tally.exe" set "TALLY_PATH=C:\Program Files\TallyPrime\tally.exe"
if not defined TALLY_PATH if exist "C:\Program Files (x86)\TallyPrime\tally.exe" set "TALLY_PATH=C:\Program Files (x86)\TallyPrime\tally.exe"
if not defined TALLY_PATH if exist "C:\TallyPrime\tally.exe" set "TALLY_PATH=C:\TallyPrime\tally.exe"
if not defined TALLY_PATH if exist "C:\TallyPrime 4.0\tally.exe" set "TALLY_PATH=C:\TallyPrime 4.0\tally.exe"
if not defined TALLY_PATH if exist "C:\TallyPrime 3.0\tally.exe" set "TALLY_PATH=C:\TallyPrime 3.0\tally.exe"
if not defined TALLY_PATH if exist "C:\Tally.ERP9\tally.exe" set "TALLY_PATH=C:\Tally.ERP9\tally.exe"
if not defined TALLY_PATH if exist "%USERPROFILE%\Desktop\TallyPrime.lnk" set "TALLY_PATH=%USERPROFILE%\Desktop\TallyPrime.lnk"
if not defined TALLY_PATH if exist "%PUBLIC%\Desktop\TallyPrime.lnk" set "TALLY_PATH=%PUBLIC%\Desktop\TallyPrime.lnk"

if defined TALLY_PATH (
    echo [*] Starting TallyPrime: "!TALLY_PATH!"
    start "" "!TALLY_PATH!"
    echo [*] Waiting 10 seconds for TallyPrime to initialize...
    timeout /t 10 /nobreak >nul
) else (
    echo [!] TallyPrime path not found in default locations.
    echo     Please make sure TallyPrime is open with Upkar Agency loaded.
)

:check_connector
echo.
echo [*] Starting Office Connector...
set "PYTHONPATH=%CD%;%PYTHONPATH%"

where py >nul 2>nul
if not errorlevel 1 (
    py -m connector.launcher
    goto done
)

where python >nul 2>nul
if not errorlevel 1 (
    python -m connector.launcher
    goto done
)

echo [!] Python 3.11+ was not found. Please install Python from python.org first.
pause

:done
