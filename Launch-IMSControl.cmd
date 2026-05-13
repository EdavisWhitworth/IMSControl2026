@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
set "PYTHONPATH=%SCRIPT_DIR%src"
set "SETUP_SCRIPT=%SCRIPT_DIR%setup_env.bat"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python virtual environment not found at:
    echo         %PYTHON_EXE%
    echo.
    if exist "%SETUP_SCRIPT%" (
        echo Would you like to set up the environment automatically?
        echo.
        set /p RESPONSE="Run setup_env.bat now? (y/n): "
        if /i "!RESPONSE!"=="y" (
            call "%SETUP_SCRIPT%"
            if errorlevel 1 (
                echo [ERROR] Setup failed. Please fix the errors above and try again.
                echo.
                pause
                exit /b 1
            )
        ) else (
            echo [INFO] Setup skipped. To set up manually, run setup_env.bat
            echo.
            pause
            exit /b 1
        )
    ) else (
        echo Create it first, then install requirements:
        echo   py -m venv .venv
        echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

pushd "%SCRIPT_DIR%"
echo [INFO] Starting IMS Control...
echo [INFO] Python executable: %PYTHON_EXE%
echo [INFO] PYTHONPATH: %PYTHONPATH%
"%PYTHON_EXE%" -m ims_control.main
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] IMS Control exited with code %EXIT_CODE%.
    echo Press any key to close this window...
    pause
) else (
    echo [INFO] IMS Control closed normally.
)

exit /b %EXIT_CODE%
