# Pathwise — Pre-recording setup script
# Double-click this in PowerShell (or run: .\start_demo.ps1)
# Run this BEFORE every take. It takes ~10 seconds.

$ErrorActionPreference = "Stop"
$HOST.UI.RawUI.WindowTitle = "PATHWISE DEMO"

# 1. UTF-8
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

# 2. Check FalkorDB
Write-Host "[1/3] Checking FalkorDB..." -ForegroundColor Yellow
$containers = docker ps --format "{{.Names}}\t{{.Status}}" 2>&1
if ($containers -match "pathwise-falkordb") {
    Write-Host "      OK — FalkorDB is running" -ForegroundColor Green
} else {
    Write-Host "      Starting FalkorDB..." -ForegroundColor Yellow
    docker-compose up -d
    Write-Host "      Waiting 8s for startup..."
    Start-Sleep -Seconds 8
    Write-Host "      FalkorDB started" -ForegroundColor Green
}

# 3. Run dry-run (warm-up)
Write-Host ""
Write-Host "[2/3] Warm-up run (NOT recorded)..." -ForegroundColor Yellow
C:\Python312\python.exe scripts/demo.py | Out-Null
Write-Host "      Warm-up complete" -ForegroundColor Green

# 4. Ready signal
Write-Host ""
Write-Host "[3/3] Ready!" -ForegroundColor Green
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  START YOUR SCREEN RECORDER NOW, THEN PRESS ENTER" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
Read-Host ""

# 5. Clear terminal cleanly and run the real take
Clear-Host
C:\Python312\python.exe scripts/demo.py
