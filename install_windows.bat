@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo Multi-Engine Asset Browser -- install/update dependencies
echo ========================================================
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo Python 3.11 64-bit not found. Install it from python.org.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
echo.
echo Dependency install complete.
echo Unreal extraction also requires UE Viewer (umodel.exe), downloaded separately.
echo Visit https://www.gildor.org/en/projects/umodel
echo Double-click run_windows.bat to launch the browser.
pause
exit /b 0
:failed
echo.
echo Installation failed. Scroll up to see the pip error.
pause
exit /b 1
