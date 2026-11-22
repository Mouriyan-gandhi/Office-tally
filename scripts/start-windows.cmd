@echo off
setlocal
cd /d "%~dp0.."

if not exist "connector\launcher.py" (
    echo ========================================================================
    echo  ERROR: "connector" folder not found!
    echo.
    echo  You appear to be running this directly inside a ZIP file.
    echo  Windows requires extracting the zip file first:
    echo.
    echo    1. Go to your Downloads folder.
    echo    2. Right-click the Office-tally zip file and choose "Extract All...".
    echo    3. Click "Extract".
    echo    4. Open the extracted "Office-tally" folder and double-click:
    echo       Run-Connector.cmd  (or start-windows.cmd)
    echo ========================================================================
    pause
    exit /b 1
)

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

echo Python was not found. Install Python 3.11 or newer from python.org first.
:done
pause
