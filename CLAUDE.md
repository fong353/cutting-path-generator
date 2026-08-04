# 切割路径生成器（局域网 Web 版）

公司内网服务：业务员提需求，操作员多客户混合拼板并生成 EPS。部署在 **M 系列 Mac**。

## 双入口

| 角色 | 路径 | 说明 |
|------|------|------|
| 门户 | `/` | 选「业务员」或「操作员」 |
| 业务员 | `/sales` | 一次可提**多个客户**；每客户多选卡纸种类 + 件尺寸/数量 |
| 业务员检查 | `/sales/demands` | 按日列表；`/sales/demands/{id}` 查看/修改（仅 pending） |
| 操作员 | `/ops` | 待拼池按「客户×材料」拆行；多选任务混拼；手填板材宽高；预览矩形内显示客户代码；生成 EPS |

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

## 数据要点

- 需求一单一个 `customer_code`；业务员指定卡纸种类（`demand_material`，含 `status` pending/done）
- 待拼单元 = 客户 × 材料（例：客户A·白卡、客户A·黄卡各一行）；生成 EPS 只完成所选材料行，该需求全部材料完成后才标 demand done
- 操作员池左右分栏：左「未完成」可勾选混拼，右「完成」当日保留不消失；建议同种卡纸一起拼
- 卡纸种类种子：黑/黄/绿/蓝/橙卡纸、白卡纸、白卡纸(无酸)（仅名称，宽高手填）
- 预览：每个必要件矩形内绘制客户代码，方便捡货
- 内孔默认居中；业务员可在「中孔偏移」二级弹窗（带图示）设置左边距/下边距，用于卡纸画框
- 成品语义：实心=整块矩形；带孔=外减孔的画框，孔内可再排料

## 核心函数

| 函数 | 作用 |
|------|------|
| `pack()` | 主排版，返回 sheets（placed 含 customer_code） |
| `_process_holes()` | 内孔填充，必要件优先 |
| `make_eps()` | 输出 EPS，3 色 Separation |

## EPS 输出命名

`{前缀}-板{编号}-{材料名}-{uid8}.eps`，例如 `卡纸路径-板1-黑卡纸-a1b2c3d4.eps`。


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

## 打包

旧 Windows EXE / PyInstaller GUI 流程已不再作为主交付；服务以源码 + venv 在 Mac 上常驻即可。
