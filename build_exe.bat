@echo off
echo =========================================================
echo Building HikView Standalone Windows Application (.exe)
echo =========================================================
pyinstaller --noconfirm --clean --windowed --name "HikView" main.py
echo.
echo Build complete!
echo Standalone executable folder: dist\HikView\HikView.exe
pause
