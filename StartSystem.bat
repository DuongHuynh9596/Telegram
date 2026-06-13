@echo off
chcp 65001 > nul
title XAUUSD Macro System

echo ========================================
echo  XAUUSD Macro Analyzer - Khoi dong...
echo ========================================
echo.

echo [1/3] Mo TradingView tren Chrome (CDP port 9222)...
set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

start "" %CHROME% --remote-debugging-port=9222 --remote-allow-origins=* --start-maximized "https://www.tradingview.com/chart/"
timeout /t 8 /nobreak > nul

echo [2/3] Mo MT5...
set MT5_EXE=
for %%P in (
  "C:\Program Files\MetaTrader 5\terminal64.exe"
  "C:\Program Files (x86)\MetaTrader 5\terminal64.exe"
  "%LOCALAPPDATA%\Programs\MetaTrader 5\terminal64.exe"
) do (
  if exist %%P (
    set MT5_EXE=%%P
    goto :launch_mt5
  )
)
for /f "delims=" %%F in ('powershell -NoProfile -Command ^
  "Get-ChildItem 'C:\','D:\' -Recurse -Filter terminal64.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName"') do (
  set MT5_EXE=%%F
)

:launch_mt5
if "%MT5_EXE%"=="" (
  echo [!] Khong tim thay MT5 — Python se tu dong mo
) else (
  echo     Mo MT5: %MT5_EXE%
  start "" %MT5_EXE%
)
timeout /t 10 /nobreak > nul

echo [3/3] Chay Python Analyzer...
start cmd /k "title Python Analyzer && color 0A && python C:\signal\analyzer.py"

echo.
echo ========================================
echo  Xong! He thong dang chay.
echo  De VPS chay lien tuc, minimize RDP.
echo ========================================
timeout /t 3 /nobreak > nul
