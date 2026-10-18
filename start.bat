@echo off
cd /d "%~dp0"
py -3 --version >nul 2>nul && (py -3 server.py %* & exit /b)
python --version >nul 2>nul && (python server.py %* & exit /b)
echo Python 3 is required. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again.
pause
