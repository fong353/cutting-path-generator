@echo off
setlocal
cd /d "%~dp0"

if not exist "data" mkdir data

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if "%CUT_HOST%"=="" set CUT_HOST=0.0.0.0
if "%CUT_PORT%"=="" set CUT_PORT=8080

"%PY%" -m uvicorn app.main:app --host %CUT_HOST% --port %CUT_PORT% >> "data\server.log" 2>&1
