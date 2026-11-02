@echo off
rem Starts GetaJob at http://127.0.0.1:8000 and opens it in your browser.
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\GetaJob\venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
echo First start? Look below for the ADMIN SETUP link and open it in your browser.
start "" http://127.0.0.1:8000
"%VENV%\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
