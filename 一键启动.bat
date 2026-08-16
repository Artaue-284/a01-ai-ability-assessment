@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD=python"
if exist "E:\Anaconda\python.exe" set "PYTHON_CMD=E:\Anaconda\python.exe"

"%PYTHON_CMD%" -c "import fastapi,uvicorn,pydantic" >nul 2>nul
if errorlevel 1 goto missing_dependencies

echo Starting AI Assessment...
echo The local and teammate access addresses will be listed below.
echo Keep this window open during testing.
"%PYTHON_CMD%" run.py %*
if errorlevel 1 goto start_failed
goto end

:missing_dependencies
echo Required Python packages are missing.
echo Run: "%PYTHON_CMD%" -m pip install -r backend\requirements.txt
pause
exit /b 1

:start_failed
echo The service failed to start. Check whether port 8000 is already in use.
pause
exit /b 1

:end
endlocal
