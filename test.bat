@echo off
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\GetaJob\venv"
"%VENV%\Scripts\python.exe" -m pytest -q
pause
