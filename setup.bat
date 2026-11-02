@echo off
rem One-time setup: creates a Python environment outside OneDrive and installs the app.
rem Uses Python 3.13, 3.12 or 3.11 (newer versions do not have the libraries built yet).
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\GetaJob\venv"
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V --version >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  echo.
  echo GetaJob needs Python 3.13, 3.12 or 3.11. None of these was found.
  echo Python 3.14 and 3.15 are too new: the libraries it uses are not built for them yet.
  echo.
  echo Install Python 3.13 from https://www.python.org/downloads/windows/
  echo   ^(pick "Windows installer 64-bit" under the latest Python 3.13 release^),
  echo tick "Add python.exe to PATH", then run setup.bat again.
  echo You can keep your other Python version installed alongside it.
  pause
  exit /b 1
)
echo Using:
%PY% --version
if exist "%VENV%\Scripts\python.exe" (
  "%VENV%\Scripts\python.exe" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" || (
    echo Removing an environment made with an unsupported Python version...
    rmdir /s /q "%VENV%"
  )
)
if not exist "%VENV%\Scripts\python.exe" %PY% -m venv "%VENV%"
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 (
  echo Installing packages failed. Check your internet connection and run setup.bat again.
  pause
  exit /b 1
)
if not exist .env copy .env.example .env >nul
echo.
echo Setup complete. Double-click run.bat to start GetaJob.
pause
