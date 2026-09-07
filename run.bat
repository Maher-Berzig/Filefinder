@echo off
REM Convenience launcher for Windows.
REM Creates a virtual environment on first run, installs dependencies,
REM then starts File Finder.

setlocal
cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing/updating dependencies...
pip install -r requirements.txt

echo Starting File Finder...
python main.py

endlocal
