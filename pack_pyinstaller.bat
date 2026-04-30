@echo off
setlocal

cd /d "%~dp0"
if errorlevel 1 goto :fail_cd

rem Virtual environment
set "VENV_DIR=%CD%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [pack_pyinstaller.bat] Creating virtual environment in .venv ...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 goto :fail_venv

    echo [pack_pyinstaller.bat] Upgrading pip in .venv ...
    "%VENV_PYTHON%" -m pip install --upgrade pip
    if errorlevel 1 goto :fail_pip

    echo [pack_pyinstaller.bat] Installing packaging dependencies into .venv ...
    "%VENV_PYTHON%" -m pip install ".[packaging]"
    if errorlevel 1 goto :fail_packaging

    echo [pack_pyinstaller.bat] Installing project into .venv ...
    "%VENV_PYTHON%" -m pip install -e .
    if errorlevel 1 goto :fail_project
) else (
    echo [pack_pyinstaller.bat] Using existing .venv; skipping dependency installation.
)

echo [pack_pyinstaller.bat] Launching pack_pyinstaller.py using .venv\Scripts\python.exe ...
"%VENV_PYTHON%" pack_pyinstaller.py
if errorlevel 1 goto :fail_build

echo [pack_pyinstaller.bat] Build completed successfully.
pause
exit /b 0

:fail_cd
echo [ERROR] Failed to enter project directory.
pause
exit /b 1

:fail_venv
echo [ERROR] Failed to create .venv.
pause
exit /b 1

:fail_pip
echo [ERROR] pip upgrade failed.
pause
exit /b 1

:fail_packaging
echo [ERROR] Failed to install packaging dependencies.
pause
exit /b 1

:fail_project
echo [ERROR] Failed to install project.
pause
exit /b 1

:fail_build
echo [ERROR] pack_pyinstaller.py failed.
pause
exit /b 1
