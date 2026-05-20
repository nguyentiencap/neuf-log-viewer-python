@echo off
setlocal EnableExtensions

REM Build Windows .exe files for NEUF Log Viewer (Python).
REM Output:
REM   dist\neuf-log-viewer-cli.exe
REM   dist\neuf-log-viewer-api.exe

cd /d "%~dp0"

echo [1/5] Installing required Python packages...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install runtime dependencies.
  exit /b 1
)
python -m pip install pyinstaller==6.13.0
if errorlevel 1 (
  echo Failed to install pyinstaller.
  exit /b 1
)

echo [2/5] Cleaning previous build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

echo [3/5] Building CLI executable...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --name neuf-log-viewer-cli ^
  --add-data "preset.json;." ^
  neuf_log_viewer_cli.py
if errorlevel 1 (
  echo CLI build failed.
  exit /b 1
)

echo [4/5] Building API executable...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --name neuf-log-viewer-api ^
  --add-data "preset.json;." ^
  neuf_log_viewer_api.py
if errorlevel 1 (
  echo API build failed.
  exit /b 1
)

echo [5/5] Copying runtime assets...
copy /Y "USERGUIDE.md" "dist\USERGUIDE.md" >nul

echo.
echo Build complete.
echo - CLI: dist\neuf-log-viewer-cli.exe
echo - API: dist\neuf-log-viewer-api.exe
echo - Asset: dist\USERGUIDE.md

endlocal
