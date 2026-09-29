# Geox bootstrap: installs a private, self-contained Python runtime so the
# app works on any Windows PC without pre-installed Python or admin rights.
$ErrorActionPreference = "Stop"
$ver = "3.12.10"
$root = Split-Path -Parent $PSScriptRoot
$dst = Join-Path $root "runtime"

if (Test-Path (Join-Path $dst "python.exe")) {
    Write-Host "Python runtime already present."
    exit 0
}

New-Item -ItemType Directory -Force -Path $dst | Out-Null
$url = "https://www.python.org/ftp/python/$ver/python-$ver-embed-amd64.zip"
$zip = Join-Path $dst "python-embed.zip"

Write-Host "Downloading Python $ver (~11 MB)..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Expand-Archive $zip -DestinationPath $dst -Force
Remove-Item $zip

# embeddable Python needs "import site" for pip, and ".." so the geox
# package (one folder up) is importable
$pth = Join-Path $dst "python312._pth"
(Get-Content $pth) -replace '#import site', 'import site' | Set-Content $pth
Add-Content $pth ".."

Write-Host "Installing pip..."
$getpip = Join-Path $dst "get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip -UseBasicParsing
& (Join-Path $dst "python.exe") $getpip --no-warn-script-location --quiet
Remove-Item $getpip

Write-Host "Downloading Geox dependencies..."
$py = Join-Path $dst "python.exe"
& $py -m pip install --quiet --no-warn-script-location setuptools wheel
& $py -m pip install --quiet --no-warn-script-location -r (Join-Path $root "requirements.txt")
Write-Host "Setup complete."
