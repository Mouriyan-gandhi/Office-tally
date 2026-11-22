@echo off
setlocal
cd /d "%~dp0"

echo ========================================================================
echo   Upkar Agency - Enable Auto-Start on Windows
echo ========================================================================
echo.

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_CMD=%~dp0scripts\launch-tally-and-connector.cmd"

if not exist "%TARGET_CMD%" (
    echo [ERROR] Cannot find scripts\launch-tally-and-connector.cmd
    echo Please ensure you extracted the Office-tally zip file before running this.
    echo.
    pause
    exit /b 1
)

set "STARTUP_FILE=%STARTUP_FOLDER%\Upkar-Tally-AutoStart.cmd"

(
    echo @echo off
    echo REM Auto-starts TallyPrime and Office Connector on Windows Sign-In
    echo cd /d "%~dp0"
    echo start "" /min "%TARGET_CMD%"
) > "%STARTUP_FILE%"

if exist "%STARTUP_FILE%" (
    echo [SUCCESS] Auto-start is now enabled!
    echo.
    echo Every time you turn on or log into your Windows laptop:
    echo   1. TallyPrime will open automatically.
    echo   2. The Office Connector script will launch in the background.
    echo.
    echo To disable auto-start at any time, run: Disable-AutoStart.cmd
    echo.
) else (
    echo [ERROR] Failed to write to the Windows Startup folder.
    echo Path: %STARTUP_FILE%
)

echo ========================================================================
pause
