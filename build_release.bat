@echo off
echo =========================================================
echo Building HikView V1.0.0 GitHub Release Packages
echo (Setup Installer .exe + Portable .zip)
echo =========================================================
powershell -ExecutionPolicy Bypass -File "%~dp0build_release.ps1"
pause
