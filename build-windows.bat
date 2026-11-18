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

py -3 -m PyInstaller --noconfirm --clean --windowed --name COC-Bot --add-data "assets;assets" --collect-all PySide6 --collect-all cv2 --collect-all rapidocr_onnxruntime main.py
if errorlevel 1 goto :error

if not exist "dist\COC-Bot\config" mkdir "dist\COC-Bot\config"
copy /Y "config\attack_plans.json" "dist\COC-Bot\config\" >nul
copy /Y "README.md" "dist\COC-Bot\" >nul
echo.
echo Build complete: %CD%\dist\COC-Bot.exe
echo Keep the config folder next to the executable when distributing.
pause
exit /b 0

:error
echo.
echo Build failed. Review the error above.
pause
exit /b 1
