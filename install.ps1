<#
.SYNOPSIS
    Geox One-Click Windows Downloader and Installer.
.DESCRIPTION
    Downloads, installs, and configures Geox on Windows.
    Creates desktop and start menu shortcuts and launches Geox.
.PARAMETER InstallDir
    Target installation directory (default: %LOCALAPPDATA%\Programs\Geox).
.PARAMETER Branch
    Git branch or tag to download (default: main).
.PARAMETER NoLaunch
    Skip launching Geox after installation completes.
.EXAMPLE
    irm https://raw.githubusercontent.com/arx33d/Geox/main/install.ps1 | iex
#>

[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\Geox"),
    [string]$Branch = "main",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[Geox] $Message" -ForegroundColor Cyan
}

function Write-Good {
    param([string]$Message)
    Write-Host "[Geox] $Message" -ForegroundColor Green
}

function Write-WarnMsg {
    param([string]$Message)
    Write-Host "[Geox] $Message" -ForegroundColor Yellow
}

function Write-ErrMsg {
    param([string]$Message)
    Write-Host "[Geox Error] $Message" -ForegroundColor Red
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "                GEOX - WINDOWS INSTALLER                    " -ForegroundColor Green
Write-Host "        Precision GPS location spoofer for iOS & Android    " -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# 1. Enable TLS 1.2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13

# 2. Prepare Destination
Write-Step "Destination folder: $InstallDir"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$tempZip = Join-Path $env:TEMP "geox-install-$((Get-Random)).zip"
$tempExtract = Join-Path $env:TEMP "geox-extract-$((Get-Random))"

try {
    # 3. Download Archive
    $zipUrl = "https://github.com/arx33d/Geox/archive/refs/heads/$Branch.zip"
    Write-Step "Downloading Geox from GitHub ($zipUrl)..."
    
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("User-Agent", "Geox-Windows-Installer")
    $wc.DownloadFile($zipUrl, $tempZip)
    Write-Good "Download complete."

    # 4. Extract Archive
    Write-Step "Extracting files..."
    if (Test-Path $tempExtract) {
        Remove-Item -Recurse -Force $tempExtract
    }
    Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

    # GitHub archives extract into a subfolder like 'Geox-main'
    $extractedRoot = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1
    if ($extractedRoot) {
        $sourceDir = $extractedRoot.FullName
    } else {
        $sourceDir = $tempExtract
    }

    Write-Step "Copying files to $InstallDir..."
    Copy-Item -Path "$sourceDir\*" -Destination $InstallDir -Recurse -Force
    Write-Good "Files placed successfully."
}
catch {
    Write-ErrMsg "Failed to download or extract Geox: $_"
    exit 1
}
finally {
    if (Test-Path $tempZip) { Remove-Item -Force $tempZip -ErrorAction SilentlyContinue }
    if (Test-Path $tempExtract) { Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue }
}

# 5. Setup Python Environment
Write-Step "Configuring runtime environment..."
$pyExe = $null

# Check if a usable system python exists
$sysPy = (Get-Command py -ErrorAction SilentlyContinue)
if ($sysPy) {
    $verCheck = & py -3 -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
    if ($verCheck -eq "True") {
        Write-Step "Found system Python via py launcher. Setting up virtual environment..."
        $venvDir = Join-Path $InstallDir ".venv"
        if (-not (Test-Path (Join-Path $venvDir "Scripts\python.exe"))) {
            & py -3 -m venv $venvDir
        }
        $pyCandidate = Join-Path $venvDir "Scripts\python.exe"
        if (Test-Path $pyCandidate) {
            Write-Step "Installing dependencies in virtualenv..."
            & $pyCandidate -m pip install --quiet --disable-pip-version-check -r (Join-Path $InstallDir "requirements.txt")
            $pyExe = $pyCandidate
        }
    }
}

if (-not $pyExe) {
    $sysPyDirect = (Get-Command python -ErrorAction SilentlyContinue)
    if ($sysPyDirect) {
        $verCheck = & python -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
        if ($verCheck -eq "True") {
            Write-Step "Found system Python. Setting up virtual environment..."
            $venvDir = Join-Path $InstallDir ".venv"
            if (-not (Test-Path (Join-Path $venvDir "Scripts\python.exe"))) {
                & python -m venv $venvDir
            }
            $pyCandidate = Join-Path $venvDir "Scripts\python.exe"
            if (Test-Path $pyCandidate) {
                Write-Step "Installing dependencies in virtualenv..."
                & $pyCandidate -m pip install --quiet --disable-pip-version-check -r (Join-Path $InstallDir "requirements.txt")
                $pyExe = $pyCandidate
            }
        }
    }
}

# If still no python, run the self-contained embeddable bootstrap
if (-not $pyExe) {
    Write-Step "No system Python detected. Downloading private embeddable Python runtime..."
    $bootstrapScript = Join-Path $InstallDir "tools\bootstrap_python.ps1"
    if (Test-Path $bootstrapScript) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrapScript
        $runtimePy = Join-Path $InstallDir "runtime\python.exe"
        if (Test-Path $runtimePy) {
            $firstRun = Join-Path $InstallDir "geox\first_run.py"
            if (Test-Path $firstRun) {
                & $runtimePy $firstRun
            }
            $pyExe = $runtimePy
        }
    }
}

# 6. Build native Geox.exe launcher if not already compiled
$geoxExe = Join-Path $InstallDir "Geox.exe"
$cscPath = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$launcherCs = Join-Path $InstallDir "tools\GeoxLauncher.cs"
$iconPath = Join-Path $InstallDir "tools\geox.ico"

if (Test-Path $cscPath -and (Test-Path $launcherCs)) {
    Write-Step "Building native Geox.exe executable..."
    $cscArgs = @(
        "/nologo",
        "/target:exe",
        "/out:$geoxExe",
        $launcherCs
    )
    if (Test-Path $iconPath) {
        $cscArgs = @("/nologo", "/target:exe", "/out:$geoxExe", "/win32icon:$iconPath", $launcherCs)
    }
    & $cscPath $cscArgs | Out-Null
    if (Test-Path $geoxExe) {
        Write-Good "Geox.exe compiled successfully."
    }
}

# 7. Create Shortcuts (Desktop & Start Menu)
Write-Step "Creating shortcuts..."
try {
    $wsh = New-Object -ComObject WScript.Shell
    
    # Desktop shortcut
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $shortcutDesktop = $wsh.CreateShortcut((Join-Path $desktopPath "Geox.lnk"))
    $shortcutDesktop.TargetPath = if (Test-Path $geoxExe) { $geoxExe } else { Join-Path $InstallDir "run_geox.bat" }
    $shortcutDesktop.WorkingDirectory = $InstallDir
    if (Test-Path $iconPath) { $shortcutDesktop.IconLocation = $iconPath }
    $shortcutDesktop.Description = "Geox GPS Location Spoofer"
    $shortcutDesktop.Save()

    # Start Menu shortcut
    $startMenuPrograms = [Environment]::GetFolderPath("Programs")
    $shortcutStart = $wsh.CreateShortcut((Join-Path $startMenuPrograms "Geox.lnk"))
    $shortcutStart.TargetPath = if (Test-Path $geoxExe) { $geoxExe } else { Join-Path $InstallDir "run_geox.bat" }
    $shortcutStart.WorkingDirectory = $InstallDir
    if (Test-Path $iconPath) { $shortcutStart.IconLocation = $iconPath }
    $shortcutStart.Description = "Geox GPS Location Spoofer"
    $shortcutStart.Save()

    Write-Good "Shortcuts created on Desktop and Start Menu."
}
catch {
    Write-WarnMsg "Could not create shortcuts: $_"
}

Write-Host ""
Write-Good "============================================================"
Write-Good "             GEOX INSTALLATION COMPLETED                    "
Write-Good "============================================================"
Write-Host "Location: $InstallDir"
Write-Host "Executable: $geoxExe"
Write-Host ""

# 8. Launch Geox unless requested not to
if (-not $NoLaunch) {
    Write-Step "Launching Geox..."
    if (Test-Path $geoxExe) {
        Start-Process -FilePath $geoxExe -WorkingDirectory $InstallDir
    } else {
        Start-Process -FilePath (Join-Path $InstallDir "run_geox.bat") -WorkingDirectory $InstallDir
    }
}
