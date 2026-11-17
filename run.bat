@echo off
rem Opens the COC Bot window (no console). For the console version: python main.py --cli
cd /d "%~dp0"
where pythonw >nul 2>&1 && (start "" pythonw main.py) || (start "" pyw -3 main.py)
