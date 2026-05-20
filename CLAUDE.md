# 切割路径生成器

单文件 Python GUI 工具，为切割机生成 EPS 路径文件。

## 文件结构

| 文件 | 说明 |
|------|------|
| `generate_cut.py` | 全部代码（~830行），算法 + EPS生成 + GUI |
| `dist/generate_cut.exe` | PyInstaller 打包产物 |
| `settings.json` | 运行时自动生成，持久化用户参数 |

## 核心数据格式

- `placed` 7-tuple：`(typ, x, y, pw, ph, piw, pih)`，typ = `'frame'`/`'solid'`
- `secondary` 6-tuple：`(x, y, pw, ph, piw, pih)`（尾料填充件）
- `fill_sizes` 4-tuple：`(fw, fh, fiw, fih)`

## 核心函数

| 函数 | 作用 |
|------|------|
| `pack()` | 主排版入口，返回 `(sheets, n_remaining)` |
| `_process_holes()` | 内孔填充，必要件优先，迭代处理嵌套孔 |
| `_make_fill_groups()` | 尾料按外尺寸分组，面积降序 |
| `_apply_fill()` | 同组轮转填充至填满 |
| `fill_secondary()` | 外部空间余料填充（Guillotine分割） |
| `make_eps()` | 输出 EPS，3色 Separation |

## EPS 颜色层

- `CutBorder`（黑）— 材料外框
- `CutOuter`（红）— 主件外轮廓
- `CutInner`（蓝）— 内孔轮廓

## 打包命令

```bash
python -m PyInstaller --onefile --windowed --name generate_cut generate_cut.py
```

## 关键实现细节

- **PyInstaller 路径**：用 `_app_dir()` 区分 frozen/开发环境，`settings.json` 和日期输出文件夹写在 EXE 同级目录
- **内孔迭代**：`pack()` 中循环调用 `_process_holes()`，直到无新件放入
- **行级启用**：`RowTable(has_enable=True)` 每行有勾选框，取消勾选行变灰；`get_rows()` 末尾追加 `'1'`/`'0'`
- **利用率**：`area_used += pw*ph - piw*pih`，避免内孔面积重复计算
- **旋转检测**：比较 `placed_r.width` 与 `fw+gap` 判断 rectpack 是否旋转了件
