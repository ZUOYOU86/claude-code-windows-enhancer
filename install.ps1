# Claude Code Windows Enhancer - One-Click Install
# Run: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Claude Code Windows Enhancer - Installer" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[1/4] Checking Python ..." -ForegroundColor Yellow
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Host "ERROR: Python not found. Install Python 3.8+ first." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "  Python: $python" -ForegroundColor Green

# 2. Initialize
Write-Host "[2/4] Initializing (protocol + shortcut) ..." -ForegroundColor Yellow
python "$ScriptDir\notify.py" --setup
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Setup failed." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "  Setup complete." -ForegroundColor Green

# 3. Install hooks
Write-Host "[3/4] Installing Claude Code hooks ..." -ForegroundColor Yellow
python "$ScriptDir\setup_hooks.py" install @args
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Hook install failed." -ForegroundColor Red
    pause
    exit 1
}
Write-Host "  Hooks installed." -ForegroundColor Green

# 4. Diagnostics
Write-Host "[4/4] Running diagnostics ..." -ForegroundColor Yellow
python "$ScriptDir\notify.py" --check
Write-Host ""

Write-Host "============================================" -ForegroundColor Green
Write-Host " Installation complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Test a notification now?"
Write-Host "  python setup_hooks.py test"
Write-Host ""
Write-Host "Or send a single test:"
Write-Host "  python notify.py Stop"
Write-Host ""
Write-Host "Restart Claude Code to activate hooks."
pause
