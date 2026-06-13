# XAUUSD Macro System - VPS Auto Installer
# Run: powershell -ExecutionPolicy Bypass -File install_vps.ps1

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
Log "Check Python..."
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Log "Installing Python 3.11..."
    $py = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $py
    Start-Process $py -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    $env:PATH += ";C:\Program Files\Python311;C:\Program Files\Python311\Scripts"
    OK "Python installed"
} else { OK "Python already installed: $(python --version 2>&1)" }

# 2. Python packages
Log "Installing Python packages..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet MetaTrader5 yfinance schedule requests websocket-client
OK "Python packages installed"

# 3. Node.js
Log "Check Node.js..."
if (!(Get-Command node -ErrorAction SilentlyContinue)) {
    Log "Installing Node.js LTS..."
    $node = "$env:TEMP\nodejs-installer.msi"
    Invoke-WebRequest "https://nodejs.org/dist/v20.18.0/node-v20.18.0-x64.msi" -OutFile $node
    Start-Process msiexec -ArgumentList "/i $node /quiet /norestart" -Wait
    $env:PATH += ";C:\Program Files\nodejs"
    OK "Node.js installed"
} else { OK "Node.js already installed: $(node --version)" }

# 4. Claude CLI
Log "Check Claude CLI..."
if (!(Get-Command claude -ErrorAction SilentlyContinue)) {
    Log "Installing Claude CLI..."
    npm install -g @anthropic-ai/claude-code 2>&1 | Out-Null
    OK "Claude CLI installed"
} else { OK "Claude CLI already installed" }

# 5. Download project files
Log "Downloading project files..."
New-Item -ItemType Directory -Force -Path "C:\signal" | Out-Null
Invoke-WebRequest "$RAW/signal/analyzer.py" -OutFile "C:\signal\analyzer.py"
Invoke-WebRequest "$RAW/StartSystem.bat"    -OutFile "$env:USERPROFILE\Desktop\StartSystem.bat"
OK "Files downloaded to C:\signal\ and Desktop"

# 6. Task Scheduler auto-start on login
Log "Setting up Task Scheduler..."
$taskName  = "XAUUSD Macro System"
$batPath   = "$env:USERPROFILE\Desktop\StartSystem.bat"
$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
OK "Task Scheduler configured - auto-start on login"

# 7. Chrome
Log "Check Chrome..."
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) {
    Log "Installing Chrome..."
    $chromeInst = "$env:TEMP\chrome-installer.exe"
    Invoke-WebRequest "https://dl.google.com/chrome/install/latest/chrome_installer.exe" -OutFile $chromeInst
    Start-Process $chromeInst -ArgumentList "/silent /install" -Wait
    OK "Chrome installed"
} else { OK "Chrome already installed" }

Write-Host ""
Write-Host "========================================" -ForegroundColor Yellow
Write-Host " INSTALLATION COMPLETE!" -ForegroundColor Yellow
Write-Host "========================================"  -ForegroundColor Yellow
Write-Host ""
Write-Host "NEXT STEPS (manual):" -ForegroundColor White
Write-Host " 1. Open C:\signal\analyzer.py with Notepad" -ForegroundColor White
Write-Host "    Fill in: MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH" -ForegroundColor White
Write-Host " 2. Install MetaTrader 5 from your broker (OANDA)" -ForegroundColor White
Write-Host " 3. Run: claude   (to login Anthropic account)" -ForegroundColor White
Write-Host " 4. Double-click StartSystem.bat on Desktop" -ForegroundColor White
Write-Host ""
