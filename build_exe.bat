@echo off
REM Builds a standalone FileFinder.exe with PyInstaller.
REM Run this from a Windows 7 32-bit Python 3.8 environment so the
REM resulting executable stays compatible with 32-bit Windows 7.

setlocal
cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

pip install -r requirements.txt
pip install pyinstaller==4.10

pyinstaller --noconfirm --onefile --windowed ^
    --name FileFinder ^
    --icon resources\icon.ico ^
    main.py

echo.
echo Build finished. The executable is in dist\FileFinder.exe
endlocal
