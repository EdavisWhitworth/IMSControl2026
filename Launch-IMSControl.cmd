@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "PYTHONPATH=%SCRIPT_DIR%src"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python virtual environment not found at:
    echo         %PYTHON_EXE%
    echo.
    echo Create it first, then install requirements:
    echo   py -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

pushd "%SCRIPT_DIR%"
"%PYTHON_EXE%" -m ims_control.main
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo IMS Control exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
