@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher was not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

py -3 -m pip install --upgrade pip
if errorlevel 1 goto :error
py -3 -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

rem Remove the old onedir output from earlier builds.
if exist "dist\COC-Bot" rmdir /s /q "dist\COC-Bot"

py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name COC-Bot --add-data "assets;assets" --add-data "config\attack_plans.json;config" --collect-all PySide6 --collect-all cv2 --collect-all rapidocr_onnxruntime main.py
if errorlevel 1 goto :error

if not exist "dist\COC-Bot.exe" (
  echo PyInstaller did not create dist\COC-Bot.exe
  goto :error
)

echo.
echo Build complete: %CD%\dist\COC-Bot.exe
echo This is a single EXE. The config and logs folders are created beside it on first run.
pause
exit /b 0

:error
echo.
echo Build failed. Review the error above.
pause
exit /b 1
