@echo off
REM 以管理员运行一次：创建开机自启任务 + 防火墙放行
setlocal
cd /d "%~dp0"

set "APP_DIR=%CD%"
set "TASK=CuttingPathGenerator"
set "PORT=8080"
set "START_BAT=%APP_DIR%\start_server.bat"

if not exist "%APP_DIR%\.venv\Scripts\python.exe" (
  echo [ERR] 未找到 .venv\Scripts\python.exe
  echo 请先: py -3 -m venv .venv ^& .venv\Scripts\pip install -r requirements.txt
  exit /b 1
)

echo [1/3] 防火墙放行 TCP %PORT% ...
netsh advfirewall firewall delete rule name="CuttingPathGenerator" >nul 2>&1
netsh advfirewall firewall add rule name="CuttingPathGenerator" dir=in action=allow protocol=TCP localport=%PORT%
if errorlevel 1 (
  echo [WARN] 防火墙规则可能失败，请手动放行 %PORT%
) else (
  echo OK
)

echo [2/3] 注册计划任务（开机启动，SYSTEM）...
schtasks /Delete /TN "%TASK%" /F >nul 2>&1
schtasks /Create /TN "%TASK%" /TR "\"%START_BAT%\"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F /NP
if errorlevel 1 (
  echo [ERR] 创建计划任务失败
  exit /b 1
)
echo OK

echo [3/3] 立即启动服务...
schtasks /Run /TN "%TASK%"
timeout /t 3 /nobreak >nul
echo.
echo 部署完成。
echo   本机: http://127.0.0.1:%PORT%
echo   局域网: http://192.168.0.115:%PORT%
echo   日志: %APP_DIR%\data\server.log
echo   任务名: %TASK%
endlocal
