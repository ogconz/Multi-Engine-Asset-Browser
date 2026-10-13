@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo Multi-Engine Asset Browser - Windows standalone EXE
echo ========================================================
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6.13,<7"
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" tools\build_exe.py
if errorlevel 1 goto :failed
echo.
echo EXE is ready: dist\MultiEngineAssetBrowser.exe
pause
exit /b 0
:failed
echo.
echo Build failed. See the error above.
pause
exit /b 1
