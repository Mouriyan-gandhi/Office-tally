@echo off
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
 echo Python was not found. Install Python 3.11 or newer from python.org first.
 pause
 exit /b 1
)
py -m connector.launcher
pause
