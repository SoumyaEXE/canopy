@echo off
setlocal EnableDelayedExpansion
title CANOPY launcher
cd /d "%~dp0"

set API_PORT=8000
set WEB_PORT=5173

echo.
echo  CANOPY - starting everything
echo  ============================

rem ---- 1. Free the ports: kill whatever is listening on them (including a previous start.bat run) ----
for %%P in (%API_PORT% %WEB_PORT%) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /r /c:":%%P .*LISTENING"') do (
    if not "%%A"=="0" (
      echo  Port %%P is in use by PID %%A - stopping it
      taskkill /F /T /PID %%A >nul 2>&1
    )
  )
)
rem Close the console windows left over from the last run.
taskkill /F /FI "WINDOWTITLE eq CANOPY API*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq CANOPY Web*" >nul 2>&1
ping -n 2 127.0.0.1 >nul

rem ---- 2. Checks ----
if not exist "backend\.venv\Scripts\python.exe" (
  echo  [!] backend\.venv not found. Create it first:
  echo      cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements-dev.txt
  pause
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo  Installing frontend packages ^(first run only^)...
  pushd frontend
  call npm install
  popd
)
if not exist "backend\.env" echo  [!] backend\.env is missing - Canopy AI will show a setup message until a key is added.

rem ---- 3. Start the API and the web app, each in its own window ----
echo  Starting API on http://localhost:%API_PORT%
start "CANOPY API" /D "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port %API_PORT%"

echo  Starting web app on http://localhost:%WEB_PORT%
rem frontend\.env.local may point VITE_API_BASE at a hosted server. Vite never overrides a variable that is
rem already set, so "/" here (which the client trims to "") sends /api through the dev proxy to this local API.
start "CANOPY Web" /D "%~dp0frontend" cmd /k "set "VITE_API_BASE=/" && npm run dev -- --port %WEB_PORT% --strictPort"

rem ---- 4. Wait for the API to answer, then open the browser ----
echo  Waiting for the API...
set /a tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:%API_PORT%/healthz).StatusCode } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  if !tries! geq 60 (
    echo  [!] The API did not start within 60 s. Check the "CANOPY API" window.
    goto open
  )
  ping -n 2 127.0.0.1 >nul
  goto wait
)
echo  API is up.

:open
start "" http://localhost:%WEB_PORT%
echo.
echo  Running. Close the "CANOPY API" and "CANOPY Web" windows to stop,
echo  or just run start.bat again - it stops the old ones first.
echo.
ping -n 6 127.0.0.1 >nul
endlocal
