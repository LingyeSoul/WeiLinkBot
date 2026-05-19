@echo off
echo ========================================
echo  WeiLinkBot Updater - Embed
echo ========================================
echo.

REM Check if this is a git repository
if not exist "%~dp0.git" (
    echo ERROR: Not a git repository!
    echo Please clone the repository first.
    pause
    exit /b 1
)

set "PYTHON_EXE=%~dp0python-3.12.9-embed\python.exe"

REM Check if embedded Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Embedded Python not found at %PYTHON_EXE%
    echo Please run setup_embed.bat first.
    pause
    exit /b 1
)

echo [INFO] Fetching updates from origin...
echo.

REM Fetch updates
git fetch origin

REM Check if there are updates
for /f %%i in ('git rev-parse HEAD') do set LOCAL=%%i
for /f %%i in ('git rev-parse origin/main') do set REMOTE=%%i

if "%LOCAL%"=="%REMOTE%" (
    echo [INFO] Already up to date!
    echo.
    goto :end
)

echo [INFO] New updates found! Pulling changes...
echo.

REM Pull changes (with autostash and rebase)
git pull --rebase --autostash origin main

echo.
echo ========================================
echo  Code update completed!
echo ========================================
echo.

REM Update dependencies
echo [INFO] Updating dependencies...
"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"

echo.
echo ========================================
echo  Update completed successfully!
echo ========================================
echo.

:end
pause
