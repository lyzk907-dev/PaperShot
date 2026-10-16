@echo off
setlocal
cd /d "%~dp0"
if exist "%USERPROFILE%\miniconda3\python.exe" (
  "%USERPROFILE%\miniconda3\python.exe" app.py
  if errorlevel 1 pause
  exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 app.py
  if errorlevel 1 pause
  exit /b
)
where python >nul 2>nul
if not errorlevel 1 (
  python app.py
  if errorlevel 1 pause
  exit /b
)
echo Python 3.10+ is required. Install Python with Tcl/Tk, then run Start.bat again.
pause
