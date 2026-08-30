@echo off
setlocal
title Build ATR-1000 TCI Protection Monitor

echo ==========================================
echo ATR-1000 TCI Protection Monitor EXE Builder
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py
) else (
    set PY=python
)

echo Installing/updating required packages...
%PY% -m pip install --upgrade pip
%PY% -m pip install --upgrade pyinstaller websocket-client
if errorlevel 1 goto :error

echo.
echo Building Windows EXE...
%PY% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "ATR1000_Protection_Monitor" ^
  atr1000_tci_protection_monitor_v6_no_login.py

if errorlevel 1 goto :error

echo.
echo ==========================================
echo BUILD COMPLETE
echo.
echo Your EXE is here:
echo dist\ATR1000_Protection_Monitor.exe
echo ==========================================
echo.
pause
exit /b 0

:error
echo.
echo ==========================================
echo BUILD FAILED
echo Please read the error messages above.
echo ==========================================
echo.
pause
exit /b 1
