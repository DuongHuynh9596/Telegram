@echo off
chcp 65001 > nul
title XAUUSD Macro System

echo ========================================
echo  XAUUSD Macro Analyzer - Khoi dong...
echo ========================================
echo.

:: --- Tim duong dan MT5 tu dong ---
set MT5_EXE=

for %%P in (
  "C:\Program Files\MetaTrader 5\terminal64.exe"
  "C:\Program Files (x86)\MetaTrader 5\terminal64.exe"
  "%LOCALAPPDATA%\Programs\MetaTrader 5\terminal64.exe"
  "%APPDATA%\..\Local\Programs\MetaTrader 5\terminal64.exe"
) do (
  if exist %%P (
    set MT5_EXE=%%P
    goto :launch
  )
)

:: Tim them trong thu muc cai dat tuy chinh
for /f "delims=" %%F in ('powershell -NoProfile -Command ^
  "Get-ChildItem 'C:\','D:\','E:\' -Recurse -Filter terminal64.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName"') do (
  set MT5_EXE=%%F
)

:launch
echo [1/2] Chay Python Analyzer...
start cmd /k "title Python Analyzer && color 0A && python C:\signal\analyzer.py"
timeout /t 3 /nobreak > nul

if "%MT5_EXE%"=="" (
  echo.
  echo [!] Khong tim thay MT5 tu dong.
  echo     Vui long mo MT5 thu cong hoac dien MT5_PATH vao C:\signal\analyzer.py
) else (
  echo [2/2] Mo MT5: %MT5_EXE%
  start "" %MT5_EXE%
)

echo.
echo ========================================
echo  Xong! Kiem tra cua so Python Analyzer.
echo ========================================
timeout /t 3 /nobreak > nul
