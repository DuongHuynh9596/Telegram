@echo off
chcp 65001 > nul
title XAUUSD Macro System

echo ========================================
echo  XAUUSD Macro Analyzer - Khoi dong...
echo ========================================
echo.

echo [1/2] Mo TradingView (CDP port 9222)...
PowerShell -WindowStyle Hidden -Command ^
  "Start-Process (Get-ChildItem 'C:\Program Files\WindowsApps\TradingView*\TradingView.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName) -ArgumentList '--remote-debugging-port=9222','--remote-allow-origins=*'"
timeout /t 5 /nobreak > nul

echo [2/2] Chay Python Analyzer (se tu dong mo MT5)...
start cmd /k "title Python Analyzer && color 0A && python C:\signal\analyzer.py"

echo.
echo ========================================
echo  Xong! Python se tu dong mo MT5.
echo  Kiem tra cua so Python Analyzer.
echo ========================================
timeout /t 3 /nobreak > nul
