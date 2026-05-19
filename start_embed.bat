@echo off
echo ========================================
echo  WeiLinkBot (Embed Python)
echo ========================================
echo.

set "PYTHON_EXE=%~dp0python-3.12.9-embed\python.exe"

REM Check if embedded Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Embedded Python not found!
    echo Please run setup_embed.bat first.
    pause
    exit /b 1
)

REM Run WeiLinkBot (default: serve command)
REM python312._pth includes '..' which points to the project root
"%PYTHON_EXE%" -s -m weilinkbot.cli.main serve

pause
