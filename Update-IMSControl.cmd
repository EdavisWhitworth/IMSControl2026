@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "REPO_DIR=%SCRIPT_DIR%"
set "SETUP_SCRIPT=%SCRIPT_DIR%setup_env.bat"
set "GIT_EXE=git"
set "TARGET_BRANCH=main"

pushd "%REPO_DIR%" >nul
if errorlevel 1 (
    echo [ERROR] Could not open the repository folder:
    echo         %REPO_DIR%
    echo.
    pause
    exit /b 1
)

where %GIT_EXE% >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git was not found in PATH.
    echo.
    echo Please install Git for Windows and try again.
    echo https://git-scm.com/download/win
    echo.
    popd
    pause
    exit /b 1
)

if not exist ".git" (
    echo [ERROR] This folder does not appear to be a Git repository.
    echo.
    echo Folder:
    echo   %REPO_DIR%
    echo.
    popd
    pause
    exit /b 1
)

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "CURRENT_BRANCH=%%B"
if not defined CURRENT_BRANCH set "CURRENT_BRANCH=%TARGET_BRANCH%"

for /f "delims=" %%R in ('git remote get-url origin 2^>nul') do set "ORIGIN_URL=%%R"
if not defined ORIGIN_URL set "ORIGIN_URL=(unknown)"

echo [INFO] Repository: %REPO_DIR%
echo [INFO] Remote: %ORIGIN_URL%
echo [INFO] Current branch: %CURRENT_BRANCH%
echo.

git status --short
if errorlevel 1 (
    echo [ERROR] Could not read repository status.
    echo.
    popd
    pause
    exit /b 1
)

for /f "tokens=*" %%S in ('git status --short') do set "HAS_CHANGES=1"
if defined HAS_CHANGES (
    echo.
    echo [WARNING] Local changes are present in this repository.
    echo Update is safest when the working tree is clean.
    echo.
    set /p RESPONSE="Continue with git pull anyway? (y/n): "
    if /i not "!RESPONSE!"=="y" (
        echo [INFO] Update cancelled.
        echo.
        popd
        pause
        exit /b 1
    )
)

echo.
echo [INFO] Pulling the latest changes from origin/%TARGET_BRANCH%...

git pull --ff-only origin %TARGET_BRANCH%
if errorlevel 1 (
    echo.
    echo [ERROR] Update failed.
    echo.
    echo If you have local changes, stash or commit them first, then try again.
    echo.
    popd
    pause
    exit /b 1
)

echo.
echo [OK] Repository updated successfully.
echo.

if exist "%SETUP_SCRIPT%" (
    set /p RUN_SETUP="Reinstall/update Python dependencies now? (recommended after dependency changes) (y/n): "
    if /i "!RUN_SETUP!"=="y" (
        call "%SETUP_SCRIPT%"
        if errorlevel 1 (
            echo.
            echo [ERROR] Environment update failed.
            echo.
            popd
            pause
            exit /b 1
        )
    )
)

echo.
echo [INFO] You can now start the app with Launch-IMSControl.cmd

echo.
popd
pause
exit /b 0
