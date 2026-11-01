@echo off
echo =========================================================
echo Building HikView Standalone Windows Application (.exe)
echo =========================================================
pyinstaller --noconfirm --clean --windowed --icon "app_icon.ico" --add-data "app_icon.ico;." --name "HikView" main.py
echo.
echo Build complete!
echo Standalone executable folder: dist\HikView\HikView.exe
pause
