# Pathwise -- Pre-recording setup script
# Run: powershell -ExecutionPolicy Bypass -File scripts\start_demo.ps1

$ErrorActionPreference = "Stop"
$HOST.UI.RawUI.WindowTitle = "PATHWISE DEMO"

chcp 65001 | Out-Null
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "c:\Users\Asus\Desktop\Pathwise"
$env:ALLOWED_ROOT = "c:\Users\Asus\Desktop\Pathwise"

Set-Location "c:\Users\Asus\Desktop\Pathwise"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  PATHWISE DEMO SETUP" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check FalkorDB
Write-Host "[1/3] Checking FalkorDB..." -ForegroundColor Yellow
$dockerOut = docker ps 2>&1
if ($dockerOut -match "pathwise-falkordb") {
    Write-Host "      OK -- FalkorDB is running" -ForegroundColor Green
} else {
    Write-Host "      Starting FalkorDB..." -ForegroundColor Yellow
    docker-compose up -d
    Write-Host "      Waiting 10s for startup..."
    Start-Sleep -Seconds 10
    Write-Host "      FalkorDB started" -ForegroundColor Green
}

# Warm-up run
Write-Host ""
Write-Host "[2/3] Warm-up run (NOT recorded)..." -ForegroundColor Yellow
C:\Python312\python.exe scripts/demo.py | Out-Null
Write-Host "      Warm-up complete" -ForegroundColor Green

# Ready signal
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  START YOUR SCREEN RECORDER, THEN PRESS ENTER" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Read-Host "Press Enter to begin recording"

# Real take
Clear-Host
C:\Python312\python.exe scripts/demo.py
