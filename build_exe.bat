@echo off
rem One-click build: output is dist\LawyerSelector.exe
rem All required files are inside this folder; venv is auto-created if missing.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe

if exist ".venv\Scripts\python.exe" goto HAVE_VENV
echo [1/4] Creating venv and installing dependencies (needs network)...
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 (
    echo FAIL: venv creation failed. Install Python 3.11+ and rerun.
    exit /b 1
)

:HAVE_VENV
echo [2/4] Checking dependencies...
set N=0
:DEPS
set /a N+=1
"%PY%" -m pip install --retries 5 --timeout 60 -r requirements.txt --quiet
if errorlevel 1 (
    if !N! lss 3 (
        echo Retry dependencies... !N!
        goto DEPS
    )
    echo FAIL: dependency install failed. Check network.
    exit /b 1
)

echo [3/4] Checking PyInstaller...
set N=0
:PYI
set /a N+=1
"%PY%" -m pip install --retries 5 --timeout 60 pyinstaller --quiet
if errorlevel 1 (
    if !N! lss 3 (
        echo Retry PyInstaller... !N!
        goto PYI
    )
    echo FAIL: PyInstaller install failed. Check network.
    exit /b 1
)

echo [4/4] Building...
"%PY%" build_exe.py
if errorlevel 1 (
    echo FAIL: build failed. See output above.
    exit /b 1
)
echo DONE: exe is in the dist folder.
