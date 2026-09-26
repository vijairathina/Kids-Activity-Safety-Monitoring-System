@echo off
REM ==============================================================================
REM Quick Launch script for Kids Activity & Safety Monitoring System (Windows)
REM ==============================================================================

cd /d "%~dp0"

IF EXIST "venv\Scripts\python.exe" (
    echo Starting Kids Safety Monitor with virtual environment...
    venv\Scripts\python.exe run.py %*
) ELSE (
    echo Virtual environment not found. Attempting to use system python...
    python run.py %*
)

pause
