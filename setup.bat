@echo off
cd /d "%~dp0"
title COC bot setup
python --version >nul 2>&1 || (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH". Then run setup.bat again.
    pause
    exit /b 1
)
python -m pip install -r requirements.txt --disable-pip-version-check
pause
