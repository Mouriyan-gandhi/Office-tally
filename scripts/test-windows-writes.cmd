@echo off
setlocal

REM Resolve project root folder (where connector\launcher.py exists)
set "ROOT_DIR=%~dp0"
if exist "%ROOT_DIR%connector\launcher.py" goto found_root
for %%I in ("%~dp0..") do if exist "%%~fI\connector\launcher.py" set "ROOT_DIR=%%~fI"& goto found_root
for %%I in ("%~dp0..\..") do if exist "%%~fI\connector\launcher.py" set "ROOT_DIR=%%~fI"& goto found_root

:found_root
cd /d "%ROOT_DIR%"
set "PYTHONPATH=%ROOT_DIR%;%PYTHONPATH%"

where py >nul 2>nul
if not errorlevel 1 (
    py -m connector.test_office
    goto done
)

where python >nul 2>nul
if not errorlevel 1 (
    python -m connector.test_office
    goto done
)

echo Python was not found. Install Python 3.11 or newer from python.org first.
:done
pause
