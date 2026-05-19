@echo off
echo ========================================
echo  WeiLinkBot Environment Setup (Embed)
echo ========================================
echo.

set "EMBED_DIR=%~dp0python-3.12.9-embed"
set "PYTHON_EXE=%EMBED_DIR%\python.exe"
set "PTH_FILE=%EMBED_DIR%\python312._pth"

REM Check if embedded Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Embedded Python not found at %PYTHON_EXE%
    echo.
    echo Please download python-3.12.9-embed-amd64.zip from:
    echo   https://www.python.org/ftp/python/3.12.9/python-3.12.9-embed-amd64.zip
    echo.
    echo Then extract to: python-3.12.9-embed\
    echo And place get-pip.py in that directory from:
    echo   https://bootstrap.pypa.io/get-pip.py
    echo.
    pause
    exit /b 1
)

REM Check if get-pip.py exists
if not exist "%EMBED_DIR%\get-pip.py" (
    echo ERROR: get-pip.py not found at %EMBED_DIR%\get-pip.py
    echo.
    echo Please download get-pip.py from:
    echo   https://bootstrap.pypa.io/get-pip.py
    echo.
    echo And place it in the python-3.12.9-embed\ directory.
    echo.
    pause
    exit /b 1
)

echo [0/3] Configuring python312._pth...
(
    echo python312.zip
    echo .
    echo.
    echo # Uncomment to run site.main() automatically
    echo #import site
    echo ./Lib/site-packages
    echo ..
) > "%PTH_FILE%"
echo       python312._pth configured (site-packages + project root).

REM Create Lib/site-packages directory
if not exist "%EMBED_DIR%\Lib\site-packages" mkdir "%EMBED_DIR%\Lib\site-packages"

echo.
echo [1/3] Installing pip...
"%PYTHON_EXE%" "%EMBED_DIR%\get-pip.py"
if errorlevel 1 (
    echo ERROR: Failed to install pip.
    pause
    exit /b 1
)
"%PYTHON_EXE%" -m pip install --upgrade pip

echo.
echo [2/3] Installing dependencies...
"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ========================================
echo  Setup completed!
echo ========================================
echo.
echo Installed versions:
"%PYTHON_EXE%" --version
"%PYTHON_EXE%" -c "import fastapi; print(f'FastAPI: {fastapi.__version__}')"
"%PYTHON_EXE%" -c "import uvicorn; print(f'Uvicorn: {uvicorn.__version__}')"
echo.
echo You can now run: start_embed.bat
echo.
pause
