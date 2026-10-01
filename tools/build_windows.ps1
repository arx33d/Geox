<#
.SYNOPSIS
    Builds the native Geox.exe launcher and GeoxSetup.exe installer.
.DESCRIPTION
    Compiles tools/GeoxLauncher.cs into Geox.exe and tools/GeoxSetup.cs into GeoxSetup.exe
    using the built-in Microsoft .NET Framework C# compiler (csc.exe).
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "            Building Geox Windows Binaries                 " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) {
    Write-Error "Microsoft .NET C# compiler (csc.exe) not found at: $csc"
    exit 1
}

$iconPath = Join-Path $root "tools\geox.ico"
$launcherCs = Join-Path $root "tools\GeoxLauncher.cs"
$setupCs = Join-Path $root "tools\GeoxSetup.cs"

# 1. Compile Geox.exe
Write-Host "[1/2] Compiling Geox.exe (Native Console/GUI Launcher)..." -ForegroundColor Yellow
$launcherArgs = @(
    "/nologo",
    "/target:exe",
    "/out:Geox.exe",
    "/win32icon:$iconPath",
    $launcherCs
)
& $csc $launcherArgs
if ($LASTEXITCODE -eq 0 -and (Test-Path "Geox.exe")) {
    $size = (Get-Item "Geox.exe").Length
    Write-Host "[OK] Geox.exe built successfully ($size bytes)." -ForegroundColor Green
} else {
    Write-Error "Failed to compile Geox.exe"
    exit 1
}

# 2. Compile GeoxSetup.exe
Write-Host "[2/2] Compiling GeoxSetup.exe (Standalone Windows Installer)..." -ForegroundColor Yellow
$setupArgs = @(
    "/nologo",
    "/target:winexe",
    "/out:GeoxSetup.exe",
    "/win32icon:$iconPath",
    "/r:System.Windows.Forms.dll",
    "/r:System.Drawing.dll",
    "/r:System.IO.Compression.dll",
    "/r:System.IO.Compression.FileSystem.dll",
    $setupCs
)
& $csc $setupArgs
if ($LASTEXITCODE -eq 0 -and (Test-Path "GeoxSetup.exe")) {
    $size = (Get-Item "GeoxSetup.exe").Length
    Write-Host "[OK] GeoxSetup.exe built successfully ($size bytes)." -ForegroundColor Green
} else {
    Write-Error "Failed to compile GeoxSetup.exe"
    exit 1
}

Write-Host ""
Write-Host "All Windows binaries built successfully." -ForegroundColor Green
