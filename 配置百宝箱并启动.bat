@echo off
setlocal
cd /d "%~dp0"
title A01 Baibaoxiang v1.8

set "PYTHON_CMD=python"
if exist "E:\Anaconda\python.exe" set "PYTHON_CMD=E:\Anaconda\python.exe"

echo Four inputs are required. Token input is hidden, so no characters will appear.
echo At each APP ID prompt, simply press Enter to accept the displayed default.
echo.
"%PYTHON_CMD%" run.py --configure-tbox-both --no-browser

echo.
echo The service has stopped or failed. Review the message above.
pause
endlocal
