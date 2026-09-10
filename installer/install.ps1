# Cyan Server installer for Windows.
# Usage: irm https://install.cyanserver.dev/windows | iex

$ErrorActionPreference = "Stop"

$InstallDir = "$env:LOCALAPPDATA\CyanServer"
$RepoUrl = "https://github.com/nadeemmhdm/cyan-server"  # real, published repo

Write-Host "Cyan Server Installer" -ForegroundColor Cyan
Write-Host "======================"

# --- 1. Detect platform -------------------------------------------------------
Write-Host "Detected platform: windows" -ForegroundColor Green

# --- 2. Detect architecture ----------------------------------------------------
$Arch = if ([Environment]::Is64BitOperatingSystem) {
    if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x86_64" }
} else { "x86" }
Write-Host "Detected architecture: $Arch" -ForegroundColor Green

# --- 3. Check requirements ------------------------------------------------------
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "python was not found. Install Python 3.10+ from https://python.org and re-run." -ForegroundColor Red
    exit 1
}
$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "Found python ($pyVersion)" -ForegroundColor Green

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "git was not found. Install git and re-run." -ForegroundColor Red
    exit 1
}
Write-Host "Found git" -ForegroundColor Green

$caddy = Get-Command caddy -ErrorAction SilentlyContinue
if (-not $caddy) {
    Write-Host "caddy not found — required for Web Server hosting (Storage/Apps work without it)." -ForegroundColor Yellow
    Write-Host "  Install via: winget install CaddyServer.Caddy" -ForegroundColor Yellow
} else {
    Write-Host "Found caddy" -ForegroundColor Green
}

# --- 4/5. Install agent + dependencies ------------------------------------------
if (Test-Path $InstallDir) {
    Write-Host "Existing install found, updating..."
    Push-Location $InstallDir
    try { git pull --ff-only } catch { Write-Host "  (skipping update)" }
    Pop-Location
} else {
    Write-Host "Cloning Cyan Server to $InstallDir"
    try {
        git clone --depth 1 $RepoUrl $InstallDir
    } catch {
        Write-Host "  (repo not reachable — creating empty install dir for local builds)"
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    }
}

Write-Host "Creating virtual environment"
python -m venv "$InstallDir\venv"
& "$InstallDir\venv\Scripts\pip.exe" install --quiet --upgrade pip
& "$InstallDir\venv\Scripts\pip.exe" install --quiet -r "$InstallDir\requirements.txt"

# --- 6. Create cyan.cmd shim ----------------------------------------------------
$ShimDir = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
$ShimPath = Join-Path $ShimDir "cyan.cmd"
"@echo off`r`n`"$InstallDir\venv\Scripts\python.exe`" `"$InstallDir\cli\main.py`" %*" |
    Out-File -Encoding ascii -FilePath $ShimPath
Write-Host "Installed 'cyan' CLI to $ShimPath" -ForegroundColor Green

# --- 7/8. Start agent ------------------------------------------------------------
Write-Host "Starting Cyan Agent"
Start-Process -WindowStyle Hidden -FilePath "$InstallDir\venv\Scripts\python.exe" `
    -ArgumentList "$InstallDir\agent\main.py" `
    -RedirectStandardOutput "$InstallDir\agent.log" `
    -RedirectStandardError "$InstallDir\agent.err.log"
Start-Sleep -Seconds 2

# --- 9. Generate secure credentials ----------------------------------------------
$SecretPath = "$InstallDir\.cyan_secret"
if (-not (Test-Path $SecretPath)) {
    python -c "import secrets; print(secrets.token_hex(32))" | Out-File -Encoding ascii $SecretPath
    Write-Host "Generated local agent secret" -ForegroundColor Green
}

# --- 10/11. Health check ----------------------------------------------------------
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:7331/api/health" -TimeoutSec 5
    Write-Host "Agent healthy" -ForegroundColor Green
} catch {
    Write-Host "Agent did not respond. Check $InstallDir\agent.log" -ForegroundColor Red
    exit 1
}

# --- 12. Show dashboard address ----------------------------------------------------
Write-Host ""
Write-Host "Cyan Server is ready." -ForegroundColor Cyan
Write-Host "  Local: http://localhost:7331"
Write-Host ""
Write-Host "Run 'cyan status' or 'cyan setup' to continue."
