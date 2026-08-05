#!/usr/bin/env bash
# 本机改完代码后，同步到 Windows 生产机 cutter 并重启服务。
# 用法:
#   ./deploy_to_cutter.sh           # 同步代码 + 重启（日常）
#   ./deploy_to_cutter.sh --deps    # 同步 + 重装依赖 + 重启
#   ./deploy_to_cutter.sh --init    # 首次：同步 + 建 venv + 装依赖 + 开机自启 + 启动
set -euo pipefail

HOST="${CUTTER_SSH_HOST:-cutter}"
REMOTE_DIR_WIN='C:\cutting-path-generator'
REMOTE_TGZ_WIN='C:\Users\G\cpg-deploy.tgz'
REMOTE_TGZ_SCP='C:/Users/G/cpg-deploy.tgz'
REMOTE_UPDATE_PS1='C:\Users\G\cpg_update.ps1'
TASK='CuttingPathGenerator'
PORT=8080
HEALTH_URL="http://192.168.0.115:${PORT}/"

DO_DEPS=0
DO_INIT=0
for arg in "$@"; do
  case "$arg" in
    --deps) DO_DEPS=1 ;;
    --init) DO_INIT=1; DO_DEPS=1 ;;
    -h|--help)
      cat <<'EOF'
用法:
  ./deploy_to_cutter.sh          # 同步代码 + 重启（日常）
  ./deploy_to_cutter.sh --deps   # 同步 + 重装依赖 + 重启
  ./deploy_to_cutter.sh --init   # 首次：venv + 依赖 + 开机自启 + 启动
EOF
      exit 0
      ;;
    *)
      echo "未知参数: $arg" >&2
      exit 1
      ;;
  esac
done

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "==> [1/5] SSH 连通 $HOST ..."
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "echo ok"

TGZ="$(mktemp -t cpg-deploy).tgz"
UPDATE_PS1="$(mktemp -t cpg-update).ps1"
cleanup() { rm -f "$TGZ" "$UPDATE_PS1"; }
trap cleanup EXIT

echo "==> [2/5] 打包并上传（不含 .venv / data / .git）..."
export COPYFILE_DISABLE=1
tar czf "$TGZ" \
  --exclude './.venv' \
  --exclude './__pycache__' \
  --exclude './.git' \
  --exclude './data' \
  --exclude './.claude' \
  --exclude './settings.json' \
  --exclude './.DS_Store' \
  --exclude './._*' \
  .
scp -o BatchMode=yes "$TGZ" "${HOST}:${REMOTE_TGZ_SCP}"

# 远端更新脚本：先停进程，再解压，清 pycache，最后启动
cat > "$UPDATE_PS1" <<'PSEOF'
$ErrorActionPreference = 'Stop'
$APP = 'C:\cutting-path-generator'
$TGZ = 'C:\Users\G\cpg-deploy.tgz'
$TASK = 'CuttingPathGenerator'
$PORT = 8080
$DoDeps = $env:CPG_DO_DEPS -eq '1'
$DoInit = $env:CPG_DO_INIT -eq '1'

Write-Host 'stop server'
Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue | ForEach-Object {
  try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
}
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -match 'python|uvicorn' -and $_.CommandLine -match 'cutting-path-generator|uvicorn' } |
  ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
Start-Sleep -Seconds 2

Write-Host 'extract'
if (-not (Test-Path $TGZ)) { throw "missing $TGZ" }
New-Item -ItemType Directory -Force -Path $APP | Out-Null
& tar -xzf $TGZ -C $APP
if ($LASTEXITCODE -ne 0) { throw "tar extract failed: $LASTEXITCODE" }
Remove-Item $TGZ -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $APP -Recurse -Force -Filter '._*' -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path (Join-Path $APP 'app') -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$marker = Join-Path $APP 'templates\sales_list.html'
$txt = Get-Content -Raw -Encoding UTF8 $marker
if ($txt -notmatch 'name="customer"') {
  throw 'extract verify failed: sales_list.html missing customer field'
}
if ($txt -notmatch 'cols-3') {
  throw 'extract verify failed: sales_list.html missing cols-3'
}
$py = Get-Content -Raw -Encoding UTF8 (Join-Path $APP 'app\routes\sales.py')
if ($py -notmatch 'customer_code=customer_q') {
  throw 'extract verify failed: sales.py missing customer filter'
}
Write-Host 'extract_ok'

$venvPy = Join-Path $APP '.venv\Scripts\python.exe'
$venvPip = Join-Path $APP '.venv\Scripts\pip.exe'
if ($DoInit -or $DoDeps) {
  Set-Location $APP
  if (-not (Test-Path $venvPy)) {
    if (-not $DoInit) { throw 'venv missing; run ./deploy_to_cutter.sh --init' }
    py -3 -m venv .venv
  }
  & $venvPy -m pip install -q --upgrade pip
  & $venvPip install -r requirements.txt
  Write-Host 'deps_ok'
}
if ($DoInit) {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $APP 'deploy_windows.ps1')
  Write-Host 'init_ok'
  exit 0
}

Write-Host 'start server'
schtasks /Run /TN $TASK | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'schtasks Run failed; try --init' }
Start-Sleep -Seconds 4
$listen = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue
if (-not $listen) {
  $log = Join-Path $APP 'data\server.log'
  if (Test-Path $log) { Get-Content $log -Tail 40 }
  throw "port $PORT not listening"
}
Write-Host 'restart_ok'
PSEOF

# 写成 UTF-8 BOM，避免 Windows PowerShell 5 默认 ANSI 把脚本弄坏
python3 - <<PY
from pathlib import Path
p = Path("$UPDATE_PS1")
text = p.read_text(encoding="utf-8")
p.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
PY
scp -o BatchMode=yes "$UPDATE_PS1" "${HOST}:C:/Users/G/cpg_update.ps1"

echo "==> [3/5] 远端停服 / 解压 / 校验 ..."
ssh -o BatchMode=yes "$HOST" \
  "set CPG_DO_DEPS=$DO_DEPS&& set CPG_DO_INIT=$DO_INIT&& powershell -NoProfile -ExecutionPolicy Bypass -File ${REMOTE_UPDATE_PS1}"

echo "==> [4/5] 健康检查 ${HEALTH_URL} ..."
code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 8 --max-time 15 "$HEALTH_URL" || true)"
if [[ "$code" != "200" ]]; then
  echo "健康检查失败 HTTP=${code:-无响应}" >&2
  ssh -o BatchMode=yes "$HOST" "powershell -NoProfile -Command \"Get-Content '${REMOTE_DIR_WIN}\\data\\server.log' -Tail 40\"" || true
  exit 1
fi

echo "==> [5/5] 校验 /sales/demands 客户查询 ..."
page="$(curl -sS --connect-timeout 8 --max-time 15 "${HEALTH_URL}sales/demands?customer=TESTMARK" || true)"
if ! printf '%s' "$page" | grep -q 'name="customer"'; then
  echo "页面校验失败：未见客户查询框" >&2
  exit 1
fi
if ! printf '%s' "$page" | grep -q 'value="TESTMARK"'; then
  echo "页面校验失败：customer 查询参数未回填（后端可能仍是旧代码）" >&2
  exit 1
fi

ssh -o BatchMode=yes "$HOST" "del /f /q C:\\Users\\G\\cpg_update.ps1 >nul 2>&1" || true
echo "部署完成: ${HEALTH_URL}  (HTTP ${code})"
