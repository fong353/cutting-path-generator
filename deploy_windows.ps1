$ErrorActionPreference = 'Stop'
$APP = 'C:\cutting-path-generator'
$TASK = 'CuttingPathGenerator'
$PORT = 8080
$START = Join-Path $APP 'start_server.bat'
$PY = Join-Path $APP '.venv\Scripts\python.exe'

Set-Location $APP
if (-not (Test-Path $PY)) { throw "venv missing: $PY" }

# Rewrite start bat as ASCII CRLF (avoid encoding issues from macOS tar)
$startLines = @(
  '@echo off',
  'setlocal',
  'cd /d "%~dp0"',
  'if not exist "data" mkdir data',
  'set "PY=.venv\Scripts\python.exe"',
  'if "%CUT_HOST%"=="" set CUT_HOST=0.0.0.0',
  'if "%CUT_PORT%"=="" set CUT_PORT=8080',
  '"%PY%" -m uvicorn app.main:app --host %CUT_HOST% --port %CUT_PORT% >> "data\server.log" 2>&1'
)
[System.IO.File]::WriteAllText($START, ($startLines -join "`r`n") + "`r`n", [System.Text.Encoding]::ASCII)

Write-Host '[1/3] firewall'
cmd /c "netsh advfirewall firewall delete rule name=`"$TASK`" >nul 2>&1"
cmd /c "netsh advfirewall firewall add rule name=`"$TASK`" dir=in action=allow protocol=TCP localport=$PORT"
if ($LASTEXITCODE -ne 0) { Write-Warning "firewall rule may have failed" } else { Write-Host 'OK' }

Write-Host '[2/3] schtasks'
cmd /c "schtasks /Delete /TN `"$TASK`" /F >nul 2>&1"
$tr = "`"$START`""
cmd /c "schtasks /Create /TN `"$TASK`" /TR $tr /SC ONSTART /RU SYSTEM /RL HIGHEST /F /NP"
if ($LASTEXITCODE -ne 0) { throw 'schtasks create failed' }
Write-Host 'OK'

Write-Host '[3/3] run now'
Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | ForEach-Object {
  try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
}
Start-Sleep -Seconds 1
cmd /c "schtasks /Run /TN `"$TASK`""
Start-Sleep -Seconds 5

Write-Host '--- task ---'
schtasks /Query /TN $TASK /FO LIST /V
Write-Host '--- listen ---'
Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, State, OwningProcess | Format-Table -AutoSize
$log = Join-Path $APP 'data\server.log'
if (Test-Path $log) {
  Write-Host '--- log tail ---'
  Get-Content $log -Tail 40
}
Write-Host "DONE http://127.0.0.1:$PORT"
