@echo off
REM ==============================================================================
REM Virtual Environment Setup Script for Kids Activity & Safety Monitoring System
REM ==============================================================================

cd /d "%~dp0"

echo [1/3] Creating Python virtual environment (venv)...
python -m venv venv
if %errorlevel% neq 0 (
    echo Error creating virtual environment. Ensure Python 3 is installed and added to PATH.
    pause
    exit /b %errorlevel%
)

echo [2/3] Upgrading pip and wheel...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel

echo [3/3] Installing dependencies from requirements.txt...
venv\Scripts\pip.exe install -r requirements.txt

echo.
echo ==============================================================================
echo   VIRTUAL ENVIRONMENT SETUP COMPLETE!
echo   To launch the application: run.bat
echo ==============================================================================
pause
