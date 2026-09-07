@echo off
REM Builds Filefinder.exe with PyInstaller (--onedir, matching what
REM Filefinder.iss's [Files] section expects: Filefinder.exe plus an
REM "_internal" subfolder next to it) and bundles the djvulibre tools/
REM DLLs directly into the build.
REM
REM Because these are bundled at the bundle root ("." in each
REM --add-binary line below), File Finder finds them automatically at
REM startup (see _default_djvu_tools_dir() in app/preview_pane.py,
REM which checks sys._MEIPASS - the "_internal" folder PyInstaller
REM extracts --add-binary files into for --onedir builds) - there's no
REM "set folder containing ddjvu.exe" button/step needed after this.
REM
REM Edit the paths below if your djvulibre binaries live somewhere
REM other than C:\PyLatexProj\Filefinder\.
REM
REM NOTE: this doesn't pin a PyInstaller version, so it builds with
REM whatever PyInstaller is currently installed. The "_internal"
REM subfolder layout is a PyInstaller 6.x thing - if you need guaranteed
REM Windows 7 32-bit compatibility, this project's build_exe.bat pins
REM the older PyInstaller 4.10 specifically for that (but builds
REM --onefile instead, so it won't have an _internal folder - update
REM Filefinder.iss's [Files] section, and the djvu auto-detect will
REM still work since it also checks sys.executable's own folder).
REM
REM Run this from the same machine/bitness you intend to run the
REM built .exe on - PyInstaller builds are not cross-platform.

setlocal
cd /d "%~dp0"

pyinstaller --clean --noconfirm --windowed ^
    --hidden-import fitz ^
    --hidden-import pymupdf ^
    --add-data "resources;resources" ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libdjvulibre.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libdjvulibre-21.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libgcc_s_seh-1.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libjpeg.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libstdc++-6.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libtiff.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libwinpthread-1.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\libz.dll;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\ddjvu.exe;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\djvused.exe;." ^
    --add-binary "C:\PyLatexProj\Filefinder\resources\djvulibre\djvutxt.exe;." ^
    --icon "resources\icon.ico" ^
    --name "Filefinder" ^
    main.py

if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build finished. The app is in dist\Filefinder\Filefinder.exe
pause
endlocal
