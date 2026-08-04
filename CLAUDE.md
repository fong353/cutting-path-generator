# 切割路径生成器（局域网 Web 版）

公司内网服务：业务员提需求，操作员多客户混合拼板并生成 EPS。

**当前生产机**：Windows `cutter`（`192.168.0.115`，SSH 经 `mac-company` 跳板），目录 `C:\cutting-path-generator`，端口 **8080**，计划任务 `CuttingPathGenerator` 开机自启（SYSTEM）。

## 双入口

| 角色 | 路径 | 说明 |
|------|------|------|
| 门户 | `/` | 选「业务员」或「操作员」 |
| 业务员 | `/sales` | 一次可提**多个客户**；每客户可「添加材料」分多段（分隔线），**每种材料各自件明细**；提交时一段材料一条 demand；提交人首次必填，之后本机 localStorage 记住 |
| 业务员检查 | `/sales/demands` | 按日列表；pending 可改内容，done 只读；均可删除 |
| 操作员 | `/ops` | 待拼池按材料归组一键混拼；手填板材宽高；预览；生成 EPS（有剩余件需确认才标完成） |

## 文件结构

| 路径 | 说明 |
|------|------|
| `app/main.py` | FastAPI 入口 |
| `app/pack_core.py` | 拼板算法（`placed` 带 `customer_code`） |
| `app/eps.py` | EPS 输出（切割路径，不写客户字） |
| `app/validate.py` | 输入校验 |
| `app/db.py` | SQLite |
| `app/routes/` | portal / sales / ops |
| `templates/` | Jinja2 页面 |
| `static/` | CSS |
| `data/` | `app.db`、`eps/`、操作员默认参数（运行时生成） |
| `generate_cut.py` | 旧桌面 GUI（保留至迁移验证后可删） |
| `start_server.sh` | macOS 启动脚本 |
| `start_server.bat` | Windows 启动（写 `data\server.log`） |
| `deploy_to_cutter.sh` | **本机一键部署/更新**到 cutter（日常用这个） |
| `deploy_windows.ps1` / `install_windows_service.bat` | 远端首次：防火墙 + 开机计划任务（由 `--init` 调用） |

## 数据要点

- 需求一单一个 `customer_code` + 一种材料；新提交/编辑均按「一材料一段」；编辑保留材料拼板状态，不能丢掉已 done 的材料
- `demand_material.status`：pending/done；待拼单元 = 客户 × 材料；生成 EPS 时若仍有件排不下需二次确认才标完成
- 操作员池：未完成按材料归组，组内一键「混拼」（无需勾选）；右「完成」可检查/下载；不同材料不可混拼
- 生成 EPS 后本页触发下载，不整页跳转
- 卡纸种类种子：黑/黄/绿/蓝/橙卡纸、白卡纸、白卡纸(无酸)（仅名称，宽高手填）
- 预览：每个必要件矩形内绘制客户代码，方便捡货
- 内孔默认居中；业务员可在「中孔偏移」二级弹窗（带图示）设置左边距/下边距，用于卡纸画框
- 成品语义：实心=整块矩形；带孔=外减孔的画框，孔内可再排料
- 件明细前端防呆：外框须严格小于标准板材 120×100 cm（可旋转）；内孔须小于外框、宽高同填或同空；标红并拦提交（后端 `parse_item_row` 同步校验）
- 标准板材尺寸常量：`app/config.py` 的 `SHEET_W` / `SHEET_H`

## 核心函数

| 函数 | 作用 |
|------|------|
| `pack()` | 主排版，返回 sheets（placed 含 customer_code） |
| `_process_holes()` | 内孔填充，必要件优先 |
| `make_eps()` | 输出 EPS，3 色 Separation |

## EPS 输出命名

`{前缀}-板{编号}-{材料名}-{uid8}.eps`，例如 `卡纸路径-板1-黑卡纸-a1b2c3d4.eps`。
落盘：`data/eps/YYYYMMDD/`；生成后页面提供单文件下载，多板时另有 ZIP 打包下载（`/ops/eps/...`、`/ops/eps-zip`）。


- `CutBorder`（黑）— 材料外框
- `CutOuter`（红）— 主件外轮廓
- `CutInner`（蓝）— 内孔轮廓

## 本地运行（Mac）

```bash
cd /path/to/cutting-path-generator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x start_server.sh
./start_server.sh
```

访问：`http://127.0.0.1:8080` 或 `http://<Mac局域网IP>:8080`

可选环境变量：`CUT_PORT`、`CUT_HOST`、`OPS_PIN`（操作员口令）、`CUT_DATA_DIR`。

## Windows 生产部署（cutter）

SSH：`Host cutter` → `192.168.0.115`，`ProxyJump mac-company`（该机常关机，SSH 可能不通）。

```text
代码目录: C:\cutting-path-generator
Python:   3.11 + .venv
访问:     http://192.168.0.115:8080
任务名:   CuttingPathGenerator（ONSTART / SYSTEM）
日志:     C:\cutting-path-generator\data\server.log
```

**本机改完 → 更新生产**（在仓库根目录）：

```bash
./deploy_to_cutter.sh          # 同步代码 + 重启（日常）
./deploy_to_cutter.sh --deps   # 改了 requirements.txt 时
./deploy_to_cutter.sh --init   # 首次装机（venv + 防火墙 + 开机自启）
```

脚本会：tar+scp 同步（排除 `.venv`/`data`/`.git`，保留远端数据库与 EPS）、按需装依赖、重启计划任务、请求首页做健康检查。远端无 rsync，不要手写 scp 步骤。

依赖须钉版本（见 `requirements.txt`）；勿装过新 FastAPI/Starlette（`TemplateResponse` API 不兼容会 500）。

## 打包

旧 Windows EXE / PyInstaller GUI 流程已不再作为主交付；生产以源码 + venv 在 cutter 上常驻。
