#!/usr/bin/env bash
# 本机改完代码后，同步到 Windows 生产机 cutter 并重启服务。
# 用法:
#   ./deploy_to_cutter.sh           # 同步代码 + 重启（日常）
#   ./deploy_to_cutter.sh --deps    # 同步 + 重装依赖 + 重启
#   ./deploy_to_cutter.sh --init    # 首次：同步 + 建 venv + 装依赖 + 开机自启 + 启动
set -euo pipefail

HOST="${CUTTER_SSH_HOST:-cutter}"
REMOTE_DIR='C:/cutting-path-generator'
REMOTE_DIR_WIN='C:\cutting-path-generator'
REMOTE_TGZ='C:/Users/G/cpg-deploy.tgz'
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

echo "==> [1/4] SSH 连通 $HOST ..."
ssh -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "echo ok"

TGZ="$(mktemp -t cpg-deploy.XXXXXX).tgz"
cleanup() { rm -f "$TGZ"; }
trap cleanup EXIT

echo "==> [2/4] 打包并上传（不含 .venv / data / .git）..."
# 禁止 macOS 写入 ._ AppleDouble，避免污染 Windows 目录
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
scp -o BatchMode=yes "$TGZ" "${HOST}:${REMOTE_TGZ}"

ssh -o BatchMode=yes "$HOST" "powershell -NoProfile -Command \"
\$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force -Path '${REMOTE_DIR_WIN}' | Out-Null
tar -xzf '${REMOTE_TGZ//\//\\}' -C '${REMOTE_DIR_WIN}'
Remove-Item '${REMOTE_TGZ//\//\\}' -Force -ErrorAction SilentlyContinue
# 清掉偶发的 AppleDouble
Get-ChildItem -Path '${REMOTE_DIR_WIN}' -Recurse -Force -Filter '._*' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Write-Output 'extract_ok'
\""

if [[ "$DO_INIT" -eq 1 ]]; then
  echo "==> [3/4] 首次部署：venv + 依赖 + 开机自启 ..."
  ssh -o BatchMode=yes "$HOST" "powershell -NoProfile -Command \"
\$ErrorActionPreference='Stop'
Set-Location '${REMOTE_DIR_WIN}'
if (-not (Test-Path '.venv\\Scripts\\python.exe')) {
  py -3 -m venv .venv
}
& '.venv\\Scripts\\python.exe' -m pip install -q --upgrade pip
& '.venv\\Scripts\\pip.exe' install -r requirements.txt
Write-Output 'venv_ok'
\""
  ssh -o BatchMode=yes "$HOST" "powershell -NoProfile -ExecutionPolicy Bypass -File ${REMOTE_DIR_WIN}\\deploy_windows.ps1"
else
  if [[ "$DO_DEPS" -eq 1 ]]; then
    echo "==> [3/4] 更新依赖 ..."
    ssh -o BatchMode=yes "$HOST" "powershell -NoProfile -Command \"
\$ErrorActionPreference='Stop'
Set-Location '${REMOTE_DIR_WIN}'
if (-not (Test-Path '.venv\\Scripts\\python.exe')) { throw 'venv missing; run ./deploy_to_cutter.sh --init' }
& '.venv\\Scripts\\pip.exe' install -r requirements.txt
Write-Output 'deps_ok'
\""
  else
    echo "==> [3/4] 跳过依赖（需要时加 --deps）"
  fi

  echo "==> [4/4] 重启服务 ..."
  ssh -o BatchMode=yes "$HOST" "powershell -NoProfile -Command \"
\$ErrorActionPreference='Continue'
Get-NetTCPConnection -LocalPort ${PORT} -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  try { Stop-Process -Id \$_.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
}
Start-Sleep -Seconds 1
schtasks /Run /TN ${TASK}
if (\$LASTEXITCODE -ne 0) { throw 'schtasks Run failed; try --init' }
Start-Sleep -Seconds 4
\$listen = Get-NetTCPConnection -LocalPort ${PORT} -State Listen -ErrorAction SilentlyContinue
if (-not \$listen) {
  Write-Output '--- log ---'
  if (Test-Path '${REMOTE_DIR_WIN}\\data\\server.log') { Get-Content '${REMOTE_DIR_WIN}\\data\\server.log' -Tail 40 }
  throw 'port ${PORT} not listening'
}
Write-Output 'restart_ok'
\""
fi

echo "==> 健康检查 ${HEALTH_URL} ..."
code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 8 --max-time 15 "$HEALTH_URL" || true)"
if [[ "$code" != "200" ]]; then
  echo "健康检查失败 HTTP=${code:-无响应}" >&2
  ssh -o BatchMode=yes "$HOST" "powershell -NoProfile -Command \"if (Test-Path '${REMOTE_DIR_WIN}\\data\\server.log') { Get-Content '${REMOTE_DIR_WIN}\\data\\server.log' -Tail 40 }\"" || true
  exit 1
fi

echo "部署完成: ${HEALTH_URL}  (HTTP ${code})"
