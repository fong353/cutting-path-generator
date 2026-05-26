# 切割路径生成器

单文件 Python GUI 工具，为切割机生成 EPS 路径文件。

## 文件结构

| 文件 | 说明 |
|------|------|
| `generate_cut.py` | 全部代码（~870行），算法 + EPS生成 + GUI |
| `settings.json` | 运行时自动生成，持久化用户参数 |
| `.github/workflows/build-windows.yml` | push master 自动编译 Windows EXE，产物在 Actions artifact |

## 核心数据格式

- `placed` 7-tuple：`(typ, x, y, pw, ph, piw, pih)`，typ = `'frame'`/`'solid'`
- `secondary` 6-tuple：`(x, y, pw, ph, piw, pih)`（尾料填充件）
- `fill_sizes` 4-tuple：`(fw, fh, fiw, fih)`
- `_items_rows`：`App` 上保存必要件数据的列表，弹窗编辑后写回

## 核心函数

| 函数 | 作用 |
|------|------|
| `pack()` | 主排版入口，返回 `(sheets, n_remaining)` |
| `_process_holes()` | 内孔填充，必要件优先，迭代处理嵌套孔 |
| `_make_fill_groups()` | 尾料按外尺寸分组，面积降序 |
| `_apply_fill()` | 同组轮转填充至填满 |
| `make_eps()` | 输出 EPS，3色 Separation |

## EPS 颜色层

- `CutBorder`（黑）— 材料外框
- `CutOuter`（红）— 主件外轮廓
- `CutInner`（蓝）— 内孔轮廓

## GUI 布局

- 主窗口：`ttk.PanedWindow` 左右分栏，分割线可拖动，窗口可自由调大
- 左侧双栏：左栏（材料 + 必要件按钮）、右栏（尾料利用）
- 必要件：独立弹窗编辑（`_open_items_dialog`），保存后写入 `self._items_rows`
- 尾料表：`RowTable(has_enable=True)`，每行有勾选框按行启用
- 预览 canvas：随窗口/面板尺寸自动缩放重绘

## 打包

Windows EXE 由 GitHub Actions 自动构建（push master 触发），无需本地打包。
手动打包命令：
```bash
pyinstaller --onefile --windowed --name generate_cut generate_cut.py
```

## 关键实现细节

- **PyInstaller 路径**：用 `_app_dir()` 区分 frozen/开发环境，`settings.json` 和日期输出文件夹写在 EXE 同级目录
- **内孔迭代**：`pack()` 中循环调用 `_process_holes()`，直到无新件放入
- **行级启用**：`RowTable(has_enable=True)` 每行有勾选框，取消勾选行变灰；`get_rows()` 末尾追加 `'1'`/`'0'`
- **max_height 滚动**：`RowTable(max_height=N)` 用 Canvas+Scrollbar 包裹 body，支持鼠标滚轮
- **利用率**：`area_used += pw*ph - piw*pih`，避免内孔面积重复计算
- **旋转检测**：比较 `placed_r.width` 与 `fw+gap` 判断 rectpack 是否旋转了件
- **开发运行**：`/opt/homebrew/bin/python3 generate_cut.py`（macOS，rectpack 装在 Homebrew Python）
