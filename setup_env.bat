@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_PATH=%SCRIPT_DIR%.venv"
set "PYTHON_EXE=%VENV_PATH%\Scripts\python.exe"
set "PIP_EXE=%VENV_PATH%\Scripts\pip.exe"
set "BASE_PYTHON_EXE="
set "BASE_PYTHON_ARGS="

echo [IMS Control] Setting up Python environment...
echo.

REM Detect a base Python installation (prefer python, then py launcher)
python --version >nul 2>&1
if not errorlevel 1 (
    set "BASE_PYTHON_EXE=python"
)

if not defined BASE_PYTHON_EXE (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "BASE_PYTHON_EXE=py"
        set "BASE_PYTHON_ARGS=-3"
    )
)

if not defined BASE_PYTHON_EXE (
    py --version >nul 2>&1
    if not errorlevel 1 (
        set "BASE_PYTHON_EXE=py"
    )
)

if not defined BASE_PYTHON_EXE (
    echo [ERROR] Python was not found.
    echo.
    echo Install Python 3.9 or later, then run this script again.
    echo Tip: On Windows, the Python Launcher ^("py"^) is enough; Python does not need to be in PATH.
    echo Visit: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM Check Python version
for /f "tokens=2" %%I in ('"%BASE_PYTHON_EXE%" %BASE_PYTHON_ARGS% --version 2^>^&1') do set "PYTHON_VERSION=%%I"
echo [INFO] Found Python: %PYTHON_VERSION%
echo.

REM Create virtual environment if it doesn't exist
if not exist "%VENV_PATH%" (
    echo [INFO] Creating virtual environment...
    "%BASE_PYTHON_EXE%" %BASE_PYTHON_ARGS% -m venv "%VENV_PATH%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Please check your Python installation and disk space.
        echo.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created at: %VENV_PATH%
    echo.
) else (
    echo [OK] Virtual environment already exists.
    echo.
)

REM Upgrade pip, setuptools, wheel
echo [INFO] Upgrading pip, setuptools, wheel...
"%PYTHON_EXE%" -m pip install --upgrade pip setuptools wheel >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Failed to upgrade pip/setuptools/wheel. Continuing anyway...
    echo.
) else (
    echo [OK] Upgraded pip, setuptools, wheel.
    echo.
)

REM Install requirements
echo [INFO] Installing dependencies from requirements.txt...
"%PYTHON_EXE%" -m pip install -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo.
    echo Please check:
    echo  - Internet connection
    echo  - Disk space
    echo  - requirements.txt file exists at: %SCRIPT_DIR%requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] ===================================================
echo [OK] Environment setup complete!
echo [OK] ===================================================
echo.
echo Next steps:
echo  1. Click "Launch-IMSControl.cmd" to start the application, or
echo  2. Run from command line: %PYTHON_EXE% -m ims_control.main
echo.
pause
