@echo off
echo ========================================
echo  WeiLinkBot Command Environment (Embed)
echo ========================================
echo.

REM Check if embedded Python exists
if not exist "%~dp0python-3.12.9-embed\python.exe" (
    echo ERROR: Embedded Python not found!
    echo Please run setup_embed.bat first.
    pause
    exit /b 1
)

REM Set project root directory
set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

REM Add project root to Python path
set "PYTHONPATH=%PROJECT_ROOT%"

REM Add embedded Python to PATH
set "PATH=%PROJECT_ROOT%\python-3.12.9-embed;%PROJECT_ROOT%\python-3.12.9-embed\Scripts;%PATH%"

echo Embedded Python: python-3.12.9-embed\
echo.
echo You can now use:
echo   python --version
echo   pip list
echo   pip install [package]
echo.
echo To run the app:
echo   python -m weilinkbot.cli.main serve
echo.
echo To deactivate, simply close this window.
echo ========================================
echo.

cmd /k
