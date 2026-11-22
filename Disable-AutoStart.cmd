@echo off
setlocal
set "STARTUP_FILE=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Upkar-Tally-AutoStart.cmd"

echo ========================================================================
echo   Upkar Agency - Disable Auto-Start on Windows
echo ========================================================================
echo.

if exist "%STARTUP_FILE%" (
    del "%STARTUP_FILE%"
    echo [SUCCESS] Auto-start has been disabled.
    echo Tally and the connector will no longer start automatically at login.
) else (
    echo Auto-start is not currently enabled.
)

echo.
echo ========================================================================
pause
