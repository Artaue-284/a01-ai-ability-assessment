@echo off
setlocal
cd /d "%~dp0"

if not exist "tools\cloudflared\cloudflared.exe" goto missing_tunnel

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\start_remote_test.ps1"
if errorlevel 1 goto start_failed
goto end

:missing_tunnel
echo cloudflared.exe is missing from tools\cloudflared.
pause
exit /b 1

:start_failed
echo Remote testing failed to start. Review the messages above.
pause
exit /b 1

:end
endlocal
