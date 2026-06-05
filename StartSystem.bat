@echo off
chcp 65001 > nul
title XAUUSD Macro System

echo ========================================
echo  XAUUSD Macro Analyzer - Khoi dong...
echo ========================================
echo.

echo [1/3] Mo TradingView (CDP port 9222)...
PowerShell -WindowStyle Hidden -Command ^
  "Start-Process (Get-ChildItem 'C:\Program Files\WindowsApps\TradingView*\TradingView.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName) -ArgumentList '--remote-debugging-port=9222','--remote-allow-origins=*'"
timeout /t 8 /nobreak > nul

echo [2/3] Mo MT5 (Python se tu dang nhap)...
start "" "C:\Program Files\MetaTrader 5\terminal64.exe"
timeout /t 10 /nobreak > nul

echo [3/3] Chay Python Analyzer...
start cmd /k "title Python Analyzer && color 0A && python C:\signal\analyzer.py"

echo.
echo ========================================
echo  He thong da khoi dong!
echo  Kiem tra cua so Python Analyzer.
echo ========================================
timeout /t 3 /nobreak > nul
