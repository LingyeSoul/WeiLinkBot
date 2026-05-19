@echo off
echo ========================================
echo  WeiLinkBot Reinstaller - Embed
echo ========================================
echo.
echo This script will reinstall all dependencies.
echo Use this when encountering dependency issues.
echo.

set "PYTHON_EXE=%~dp0python-3.12.9-embed\python.exe"

REM Check if embedded Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Embedded Python not found at %PYTHON_EXE%
    echo Please run setup_embed.bat first.
    pause
    exit /b 1
)

echo [INFO] Reinstalling dependencies...
echo.

"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"

echo.
echo ========================================
echo  Reinstallation completed!
echo ========================================
echo.
pause
