@echo off
setlocal

set "ROOT=%~dp0"

start "CANOPY Backend" /D "%ROOT%backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "CANOPY Frontend" /D "%ROOT%frontend" cmd /k "npm run dev"

echo CANOPY backend: http://localhost:8000
echo CANOPY frontend: http://localhost:5173