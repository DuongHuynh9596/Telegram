# XAUUSD Macro System - VPS Auto Installer
# Chay bang: powershell -ExecutionPolicy Bypass -File install_vps.ps1

$ErrorActionPreference = "Continue"
$BRANCH = "claude/tradingview-mcp-setup-7KmJ6"
$RAW    = "https://raw.githubusercontent.com/duonghuynh9596/telegram/$BRANCH"

function Log($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function OK($msg)  { Write-Host "[OK] $msg" -ForegroundColor Green }
function ERR($msg) { Write-Host "[!!] $msg" -ForegroundColor Red }

Log "========================================"
Log " XAUUSD Macro System - VPS Installer"
Log "========================================"

# 1. Python
Log "Kiem tra Python..."
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Log "Cai Python 3.11..."
    $py = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $py
    Start-Process $py -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    $env:PATH += ";C:\Program Files\Python311;C:\Program Files\Python311\Scripts"
    OK "Python da cai xong"
} else { OK "Python da co san: $(python --version)" }

# 2. Python packages
Log "Cai Python packages..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet MetaTrader5 yfinance schedule requests websocket-client
OK "Python packages OK"

# 3. Node.js
Log "Kiem tra Node.js..."
if (!(Get-Command node -ErrorAction SilentlyContinue)) {
    Log "Cai Node.js LTS..."
    $node = "$env:TEMP\nodejs-installer.msi"
    Invoke-WebRequest "https://nodejs.org/dist/v20.18.0/node-v20.18.0-x64.msi" -OutFile $node
    Start-Process msiexec -ArgumentList "/i $node /quiet /norestart" -Wait
    $env:PATH += ";C:\Program Files\nodejs"
    OK "Node.js da cai xong"
} else { OK "Node.js da co san: $(node --version)" }

# 4. Claude CLI
Log "Kiem tra Claude CLI..."
if (!(Get-Command claude -ErrorAction SilentlyContinue)) {
    Log "Cai Claude CLI..."
    npm install -g @anthropic-ai/claude-code | Out-Null
    OK "Claude CLI da cai xong"
} else { OK "Claude CLI da co san" }

# 5. Thu muc va file
Log "Download file project..."
New-Item -ItemType Directory -Force -Path "C:\signal" | Out-Null
Invoke-WebRequest "$RAW/signal/analyzer.py" -OutFile "C:\signal\analyzer.py"
Invoke-WebRequest "$RAW/StartSystem.bat"    -OutFile "$env:USERPROFILE\Desktop\StartSystem.bat"
OK "Files da download"

# 6. Task Scheduler - auto start khi login
Log "Thiet lap Task Scheduler auto-start..."
$taskName   = "XAUUSD Macro System"
$batPath    = "$env:USERPROFILE\Desktop\StartSystem.bat"
$action     = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$trigger    = New-ScheduledTaskTrigger -AtLogOn
$settings   = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal  = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
                       -Settings $settings -Principal $principal | Out-Null
OK "Task Scheduler OK — tu dong chay khi login VPS"

# 7. Chrome check
Log "Kiem tra Chrome..."
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) {
    Log "Cai Chrome..."
    $chromeInst = "$env:TEMP\chrome-installer.exe"
    Invoke-WebRequest "https://dl.google.com/chrome/install/latest/chrome_installer.exe" -OutFile $chromeInst
    Start-Process $chromeInst -ArgumentList "/silent /install" -Wait
    OK "Chrome da cai xong"
} else { OK "Chrome da co san" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Yellow
Write-Host " CAI DAT HOAN TAT!" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "VIEC CON LAI (thu cong):" -ForegroundColor White
Write-Host " 1. Mo C:\signal\analyzer.py bang Notepad" -ForegroundColor White
Write-Host "    Dien MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH" -ForegroundColor White
Write-Host " 2. Cai MetaTrader 5 tu trang broker (OANDA)" -ForegroundColor White
Write-Host " 3. Chay: claude  (de dang nhap Anthropic account)" -ForegroundColor White
Write-Host " 4. Double-click StartSystem.bat tren Desktop" -ForegroundColor White
Write-Host ""
