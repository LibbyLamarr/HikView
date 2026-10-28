$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Version = "v1.0.0"
$DistAppDir = Join-Path $ProjectRoot "dist\HikView"
$ReleasesDir = Join-Path $ProjectRoot "releases"
$CSC = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path $DistAppDir)) {
    Write-Host "Building HikView.exe with PyInstaller first..." -ForegroundColor Cyan
    pyinstaller --noconfirm --clean --windowed --name "HikView" main.py
}

if (-not (Test-Path $ReleasesDir)) {
    New-Item -ItemType Directory -Path $ReleasesDir | Out-Null
}

# 1. Copy LICENSE and README.md into dist\HikView
Copy-Item -Path (Join-Path $ProjectRoot "LICENSE") -Destination (Join-Path $DistAppDir "LICENSE.txt") -Force
Copy-Item -Path (Join-Path $ProjectRoot "README.md") -Destination (Join-Path $DistAppDir "README.md") -Force

# Remove any existing Uninstall-HikView.exe before creating Portable ZIP
$UninstallerPath = Join-Path $DistAppDir "Uninstall-HikView.exe"
if (Test-Path $UninstallerPath) {
    Remove-Item $UninstallerPath -Force
}

# 2. Create Portable ZIP: releases\HikView-Portable-v1.0.0.zip
$PortableZip = Join-Path $ReleasesDir "HikView-Portable-$Version.zip"
if (Test-Path $PortableZip) {
    Remove-Item $PortableZip -Force
}
Write-Host "Creating Portable archive: $PortableZip ..." -ForegroundColor Cyan
Compress-Archive -Path $DistAppDir -DestinationPath $PortableZip -CompressionLevel Optimal
Write-Host "Portable ZIP created: $PortableZip" -ForegroundColor Green

# 3. Compile Uninstaller into dist\HikView\Uninstall-HikView.exe
Write-Host "Compiling Uninstall-HikView.exe ..." -ForegroundColor Cyan
& $CSC /nologo /target:winexe /out:$UninstallerPath `
    /r:System.dll /r:System.Windows.Forms.dll `
    (Join-Path $ProjectRoot "installer\Uninstaller.cs")

# 4. Create temporary payload ZIP (includes Uninstall-HikView.exe) for the Setup installer
$PayloadZip = Join-Path $ReleasesDir "_payload_temp.zip"
if (Test-Path $PayloadZip) {
    Remove-Item $PayloadZip -Force
}
Write-Host "Packaging installer payload ..." -ForegroundColor Cyan
Compress-Archive -Path $DistAppDir -DestinationPath $PayloadZip -CompressionLevel Optimal

# 5. Compile HikView-Setup-v1.0.0.exe with embedded payload
$SetupExe = Join-Path $ReleasesDir "HikView-Setup-$Version.exe"
if (Test-Path $SetupExe) {
    Remove-Item $SetupExe -Force
}
Write-Host "Compiling Windows Setup Wizard: $SetupExe ..." -ForegroundColor Cyan
& $CSC /nologo /target:winexe /out:$SetupExe `
    /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll `
    /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll `
    /resource:"$PayloadZip,HikViewPayload.zip" `
    (Join-Path $ProjectRoot "installer\SetupWizard.cs")

# Clean up temporary payload zip and remove Uninstaller from portable dist folder
if (Test-Path $PayloadZip) {
    Remove-Item $PayloadZip -Force
}

Write-Host ""
Write-Host "=========================================================" -ForegroundColor Green
Write-Host " Release Build Complete!" -ForegroundColor Green
Write-Host " 1. Installer : $SetupExe" -ForegroundColor Yellow
Write-Host " 2. Portable  : $PortableZip" -ForegroundColor Yellow
Write-Host "=========================================================" -ForegroundColor Green
