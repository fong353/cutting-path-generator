#!/usr/bin/env python3
"""切割机路径生成器"""

import tkinter as tk
from tkinter import ttk, messagebox
import os, sys, uuid, json
from datetime import datetime
from rectpack import newPacker, PackingMode, MaxRectsBssf

CM = 28.34645669   # 1 cm = PT 点

def _app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(_app_dir(), 'settings.json')


# ── EPS ───────────────────────────────────────────────────────────────────────

def _rect(L, x1, y1, x2, y2):
    L += [f"{x2:.3f} {y2:.3f} m", f"{x2:.3f} {y1:.3f} l",
          f"{x1:.3f} {y1:.3f} l", f"{x1:.3f} {y2:.3f} l", f"{x2:.3f} {y2:.3f} l"]


def make_eps(placed, path, mat_w, mat_h, secondary=None):
    """
    placed   : [(type, x, y, pw, ph, piw, pih)]  单位 cm
    secondary: [(x, y, pw, ph, piw, pih)]         填充件，单位 cm
    EPS 双色：外框路径用 CutOuter（红），内孔路径用 CutInner（蓝）。
    """
    def p(v): return v * CM
    sw, sh = p(mat_w), p(mat_h)
    sec = secondary or []

    lines = [
        "%!PS-Adobe-2.0 EPSF-2.0",
        f"%%BoundingBox: 0 0 {sw:.3f} {sh:.3f}",
        "/bd{bind def}bind def /m{moveto}bd /l{lineto}bd",
        "%%DocumentCustomColors:(CutBorder)(CutOuter)(CutInner)",
        "%%RGBCustomColor:0.00 0.00 0.00(CutBorder)",
        "%%RGBCustomColor:1.00 0.00 0.00(CutOuter)",
        "%%RGBCustomColor:0.00 0.00 1.00(CutInner)",
        "[ /Separation (CutBorder) /DeviceRGB",
        "{ dup 0.000000 mul exch dup 0.000000 mul exch 0.000000 mul }",
        "] setcolorspace", "1.0 setcolor", "0.5 setlinewidth",
        f"newpath 0 0 m {sw:.3f} 0 l {sw:.3f} {sh:.3f} l 0 {sh:.3f} l closepath stroke",
        # ── 外框路径 ──
        "[ /Separation (CutOuter) /DeviceRGB",
        "{ dup 1.000000 mul exch dup 0.000000 mul exch 0.000000 mul }",
        "] setcolorspace", "1.0 setcolor", "newpath",
    ]
    for typ, x, y, pw, ph, piw, pih in placed:
        _rect(lines, p(x), p(y), p(x+pw), p(y+ph))
    for x, y, pw, ph, piw, pih in sec:
        _rect(lines, p(x), p(y), p(x+pw), p(y+ph))
    lines.append("stroke")

    # ── 内孔路径 ──
    inner_lines = []
    for typ, x, y, pw, ph, piw, pih in placed:
        if piw > 0:
            xp, yp, pwp, php = p(x), p(y), p(pw), p(ph)
            piwp, pihp = p(piw), p(pih)
            _rect(inner_lines, xp+(pwp-piwp)/2, yp+(php-pihp)/2,
                               xp+(pwp+piwp)/2, yp+(php+pihp)/2)
    for x, y, pw, ph, piw, pih in sec:
        if piw > 0:
            xp, yp, pwp, php = p(x), p(y), p(pw), p(ph)
            piwp, pihp = p(piw), p(pih)
            _rect(inner_lines, xp+(pwp-piwp)/2, yp+(php-pihp)/2,
                               xp+(pwp+piwp)/2, yp+(php+pihp)/2)
    if inner_lines:
        lines += [
            "[ /Separation (CutInner) /DeviceRGB",
            "{ dup 0.000000 mul exch dup 0.000000 mul exch 1.000000 mul }",
            "] setcolorspace", "1.0 setcolor", "newpath",
        ] + inner_lines + ["stroke"]

    with open(path, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines) + '\n')


# ── 排版 ──────────────────────────────────────────────────────────────────────

def _make_fill_groups(fill_sizes):
    """
    按外框尺寸分组（旋转等价视为同组），组内保持表格顺序，组间按面积降序。
    返回 [ [(fw,fh,fiw,fih), ...], ... ]
    """
    groups_dict = {}
    order = []
    for item in fill_sizes:
        fw, fh = item[0], item[1]
        key = (max(fw, fh), min(fw, fh))
        if key not in groups_dict:
            groups_dict[key] = []
            order.append(key)
        groups_dict[key].append(item)
    order.sort(key=lambda k: k[0] * k[1], reverse=True)
    return [groups_dict[k] for k in order]


def _apply_fill(bin_obj, fill_sizes, gap):
    """
    向 MaxRects bin 做分组轮询填充。
    每组内每轮各放一件；整组一轮都放不下则跳下一组。
    返回 [(x, y, pw, ph, piw, pih)]，坐标为 bin 坐标系。
    """
    results = []
    for group in _make_fill_groups(fill_sizes):
        while True:
            placed_any = False
            for fw, fh, fiw, fih in group:
                placed_r = bin_obj.add_rect(fw + gap, fh + gap)
                if placed_r is None and fw != fh:
                    placed_r = bin_obj.add_rect(fh + gap, fw + gap)
                if placed_r is None:
                    continue
                placed_any = True
                if abs(placed_r.width - (fw + gap)) < 1e-6:
                    aw, ah, aiw, aih = fw, fh, fiw, fih
                else:
                    aw, ah, aiw, aih = fh, fw, fih, fiw
                results.append((float(placed_r.x), float(placed_r.y),
                                aw, ah, aiw, aih))
            if not placed_any:
                break
    return results


def _pack_one_sheet(singles, usable_w, usable_h, gap, fill_sizes=None):
    """
    主件排版后，继续向同一 MaxRects bin 追加填充件（外部空闲区）。
    返回 (placed, remaining, secondary_outer)
    placed          : [(typ, x, y, pw, ph, piw, pih)]  bin 坐标
    secondary_outer : [(x, y, pw, ph, label)]           bin 坐标
    """
    if not singles:
        return [], [], []

    packer = newPacker(mode=PackingMode.Offline, pack_algo=MaxRectsBssf, rotation=True)
    packer.add_bin(usable_w + gap, usable_h + gap)
    for i, (typ, ow, oh, iw, ih) in enumerate(singles):
        packer.add_rect(ow + gap, oh + gap, rid=i)
    packer.pack()

    placed, placed_idx = [], set()
    secondary_outer = []

    for b in packer:
        for r in b:
            i = r.rid
            typ, ow, oh, iw, ih = singles[i]
            placed_idx.add(i)
            if abs(r.width - (ow + gap)) < 1e-6:
                pw, ph, piw, pih = ow, oh, iw, ih
            else:
                pw, ph, piw, pih = oh, ow, ih, iw
            placed.append((typ, float(r.x), float(r.y), pw, ph, piw, pih))

        if fill_sizes:
            secondary_outer.extend(_apply_fill(b, fill_sizes, gap))

    remaining = [singles[j] for j in range(len(singles)) if j not in placed_idx]
    return placed, remaining, secondary_outer


def _process_holes(placed_sheet, remaining, gap, fill_sizes):
    """
    对每个 frame 内孔：
      1. 优先将尚未排版的必要件（remaining）塞进去
      2. 剩余空间再填充填充件
    返回 (hole_placed, hole_secondary, still_remaining)
    hole_placed    : [(typ,x,y,pw,ph,piw,pih)]  必要件，加入 placed（sheet 坐标）
    hole_secondary : [(x,y,pw,ph,piw,pih)]       填充件（sheet 坐标）
    still_remaining: 仍未排版的必要件
    """
    hole_placed = []
    hole_secondary = []
    still_remaining = list(remaining)

    for typ, x, y, pw, ph, piw, pih in placed_sheet:
        if typ != 'frame' or piw <= 0:
            continue
        hx = x + (pw - piw) / 2
        hy = y + (ph - pih) / 2
        avail_w = piw - 2 * gap
        avail_h = pih - 2 * gap
        if avail_w <= 0 or avail_h <= 0:
            continue

        hole_bin = MaxRectsBssf(avail_w + gap, avail_h + gap, rot=True)

        # 阶段 1：将剩余必要件（大→小）尽量塞入内孔
        still_remaining.sort(key=lambda t: -(t[1] * t[2]))
        placed_set = set()
        for i, (rtyp, ow, oh, iw, ih) in enumerate(still_remaining):
            placed_r = hole_bin.add_rect(ow + gap, oh + gap)
            if placed_r is None and ow != oh:
                placed_r = hole_bin.add_rect(oh + gap, ow + gap)
            if placed_r is None:
                continue
            placed_set.add(i)
            if abs(placed_r.width - (ow + gap)) < 1e-6:
                rpw, rph, rpiw, rpih = ow, oh, iw, ih
            else:
                rpw, rph, rpiw, rpih = oh, ow, ih, iw
            hole_placed.append((rtyp,
                                hx + gap + float(placed_r.x),
                                hy + gap + float(placed_r.y),
                                rpw, rph, rpiw, rpih))
        still_remaining = [t for i, t in enumerate(still_remaining) if i not in placed_set]

        # 阶段 2：用填充件填满剩余内孔空间
        if fill_sizes:
            for rx, ry, rw, rh, riw, rih in _apply_fill(hole_bin, fill_sizes, gap):
                hole_secondary.append((hx + gap + rx, hy + gap + ry,
                                       rw, rh, riw, rih))

    return hole_placed, hole_secondary, still_remaining


def pack(items, materials, gap, fill_sizes=None, fill_last=True):
    """
    items      : [(type, ow, oh, iw, ih, qty)]
    materials  : [(mat_w, mat_h, max_sheets)]
    fill_sizes : [(fw, fh, fiw, fih)] 或 None
    fill_last  : False 时最后一张不填充
    返回 (sheets, n_remaining)
    sheets: [(mat_w, mat_h, placed, secondary)]
    """
    singles = []
    for typ, ow, oh, iw, ih, qty in items:
        singles += [(typ, ow, oh, iw, ih)] * qty
    singles.sort(key=lambda t: (-max(t[2], t[1]), -min(t[2], t[1])))

    all_sheets = []
    for mat_w, mat_h, max_sheets in materials:
        usable_w = mat_w - 2 * gap
        usable_h = mat_h - 2 * gap
        if usable_w <= 0 or usable_h <= 0:
            continue
        sheets_used = 0
        while singles and (max_sheets is None or sheets_used < max_sheets):
            placed, singles, sec_outer = _pack_one_sheet(
                singles, usable_w, usable_h, gap, fill_sizes)
            if not placed:
                break
            placed_off = [(t, x+gap, y+gap, pw, ph, piw, pih)
                          for t, x, y, pw, ph, piw, pih in placed]
            sec_outer_off = [(x+gap, y+gap, pw, ph, piw, pih)
                             for x, y, pw, ph, piw, pih in sec_outer]
            # 迭代处理嵌套内孔：每轮只处理本轮新放入孔中的件的内孔
            all_hole_secondary = []
            to_process = placed_off[:]   # 本轮待处理的框列表
            while to_process:
                hole_placed, hole_secondary, singles = _process_holes(
                    to_process, singles, gap, fill_sizes)
                placed_off.extend(hole_placed)
                all_hole_secondary.extend(hole_secondary)
                to_process = hole_placed  # 下一轮处理本轮新放入孔中的件
            all_sheets.append((mat_w, mat_h, placed_off, sec_outer_off + all_hole_secondary))
            sheets_used += 1

    if not fill_last and all_sheets:
        mat_w, mat_h, placed, secondary = all_sheets[-1]
        all_sheets[-1] = (mat_w, mat_h, placed, [])

    return all_sheets, len(singles)


# ── GUI ───────────────────────────────────────────────────────────────────────

MAT_HDR  = ["材料宽(cm)", "材料高(cm)", "可用张数\n(留空=不限)", ""]
MAT_WIDS = [10, 10, 12, 3]
ITM_HDR  = ["外框宽(cm)", "外框高(cm)", "内孔宽(cm)\n留空=实心", "内孔高(cm)\n留空=实心", "数量", ""]
ITM_WIDS = [9, 9, 11, 11, 6, 3]
FILL_HDR  = ["外框宽(cm)", "外框高(cm)", "内孔宽(cm)\n留空=实心", "内孔高(cm)\n留空=实心", ""]
FILL_WIDS = [9, 9, 11, 11, 3]


class RowTable(ttk.Frame):
    """通用可增删行的表格组件。"""

    def __init__(self, master, headers, widths, init_rows=3):
        super().__init__(master)
        self.widths = widths
        self.rows = []   # list of (entries_list, del_btn)

        # 表头
        for c, (h, w) in enumerate(zip(headers[:-1], widths[:-1])):
            ttk.Label(self, text=h, justify='center', anchor='center',
                      width=w).grid(row=0, column=c, padx=4, pady=(0, 4))

        self.body = ttk.Frame(self)
        self.body.grid(row=1, column=0, columnspan=len(headers))

        ttk.Button(self, text="＋ 增加一行", command=self.add_row).grid(
            row=2, column=0, columnspan=len(headers), sticky='w', pady=(4, 0))

        for _ in range(init_rows):
            self.add_row()

    def add_row(self, prefill=None):
        entries = []
        for c, w in enumerate(self.widths[:-1]):
            e = ttk.Entry(self.body, width=w)
            if prefill and c < len(prefill) and prefill[c]:
                e.insert(0, prefill[c])
            entries.append(e)
        btn = ttk.Button(self.body, text="✕", width=2,
                         command=lambda: self.del_row(entries))
        self.rows.append((entries, btn))
        self._redraw()

    def del_row(self, entries):
        if len(self.rows) <= 1:
            return
        self.rows = [(e, b) for e, b in self.rows if e is not entries]
        self._redraw()

    def _redraw(self):
        for w in self.body.grid_slaves():
            w.grid_forget()
        for r, (entries, btn) in enumerate(self.rows):
            for c, e in enumerate(entries):
                e.grid(row=r, column=c, padx=4, pady=2)
            btn.grid(row=r, column=len(self.widths)-1, padx=(2, 0), pady=2)

    def get_rows(self):
        """返回每行的 [str, ...] 列表，跳过全空行。"""
        result = []
        for entries, _ in self.rows:
            vals = [e.get().strip() for e in entries]
            if any(vals):
                result.append(vals)
        return result

    def clear(self, keep_rows=2):
        """清空所有行，保留 keep_rows 个空行。"""
        for entries, btn in self.rows:
            for e in entries: e.destroy()
            btn.destroy()
        self.rows = []
        for _ in range(keep_rows):
            self.add_row()


class PrefixBar(tk.Frame):
    """一排可编辑、可选的前缀按钮，点击选中，文字可直接改。"""

    SEL_BG = '#0078d4'
    SEL_FG = 'white'
    NOR_BG = '#e8e8e8'
    NOR_FG = 'black'

    def __init__(self, master, defaults=("卡纸路径",)):
        super().__init__(master)
        self._tags = []
        self._selected = None

        self._bar = tk.Frame(self)
        self._bar.grid(row=0, column=0, sticky='w')

        tk.Button(self, text="＋", width=2, relief='flat',
                  command=self.add_tag).grid(row=0, column=1, padx=(6, 0))

        for name in defaults:
            self.add_tag(name)

    def add_tag(self, text="新前缀"):
        var = tk.StringVar(value=text)
        frame = tk.Frame(self._bar, bg=self.NOR_BG, padx=4, pady=3)

        entry = tk.Entry(frame, textvariable=var, width=max(5, len(text)+1),
                         relief='flat', bd=0, bg=self.NOR_BG, fg=self.NOR_FG)
        entry.pack(side='left')

        # 自动调整宽度
        def _resize(e, ent=entry, v=var):
            ent.config(width=max(5, len(v.get()) + 1))
        entry.bind('<KeyRelease>', _resize)

        del_btn = tk.Button(frame, text="×", relief='flat', bd=0,
                            font=('', 8), padx=0, pady=0,
                            bg=self.NOR_BG, fg='#888',
                            activebackground=self.NOR_BG)
        del_btn.pack(side='left', padx=(2, 0))

        tag = {'var': var, 'frame': frame, 'entry': entry, 'del': del_btn}

        entry.bind('<Button-1>', lambda e, t=tag: self._select(t))
        entry.bind('<FocusIn>',  lambda e, t=tag: self._select(t))
        frame.bind('<Button-1>', lambda e, t=tag: self._select(t))
        del_btn.config(command=lambda t=tag: self._del_tag(t))

        self._tags.append(tag)
        self._redraw()
        if self._selected is None:
            self._select(tag)
        return tag

    def _del_tag(self, tag):
        if len(self._tags) <= 1:
            return
        was_sel = (self._selected is tag)
        self._tags.remove(tag)
        tag['frame'].destroy()
        self._redraw()
        if was_sel:
            self._select(self._tags[0])

    def _select(self, tag):
        self._selected = tag
        for t in self._tags:
            sel = (t is tag)
            bg = self.SEL_BG if sel else self.NOR_BG
            fg = self.SEL_FG if sel else self.NOR_FG
            t['frame'].config(bg=bg)
            t['entry'].config(bg=bg, fg=fg, insertbackground=fg)
            t['del'].config(bg=bg, fg=self.SEL_FG if sel else '#888',
                            activebackground=bg)

    def _redraw(self):
        for i, tag in enumerate(self._tags):
            tag['frame'].grid(row=0, column=i, padx=3, pady=2)

    def get(self):
        if self._selected:
            return self._selected['var'].get().strip() or "卡纸路径"
        return "卡纸路径"

    def get_all(self):
        return [t['var'].get() for t in self._tags]

    def reset(self, names):
        for tag in list(self._tags):
            tag['frame'].destroy()
        self._tags = []
        self._selected = None
        for name in (names or ["卡纸路径"]):
            self.add_tag(name)


class App(tk.Tk):
    CVS_W, CVS_H, CVS_PAD = 460, 380, 14

    def __init__(self):
        super().__init__()
        self.title("切割路径生成器")
        self.resizable(False, False)
        self._sheets_data = []
        self._cur_sheet   = 0
        self._build()
        self._load_settings()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _build(self):
        f = ttk.Frame(self, padding=14)
        f.grid()

        # —— 顶部设置行 ——
        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(top, text="文件前缀:").grid(row=0, column=0, sticky='e')
        self.prefix_bar = PrefixBar(top, defaults=("卡纸路径", "相框", "备用"))
        self.prefix_bar.grid(row=0, column=1, padx=(4, 20))
        ttk.Label(top, text="间距(cm):").grid(row=0, column=2, sticky='e')
        self.e_gap = ttk.Entry(top, width=6)
        self.e_gap.insert(0, "1")
        self.e_gap.grid(row=0, column=3, padx=(4, 0))
        ttk.Label(top, text="（0=共刀）", foreground='gray').grid(row=0, column=4, sticky='w', padx=(4,0))

        # —— 材料表 ——
        ttk.Label(f, text="材料（按优先级从上到下）",
                  font=('', 9, 'bold')).grid(row=1, column=0, sticky='w')
        self.mat_tbl = RowTable(f, MAT_HDR, MAT_WIDS, init_rows=2)
        self.mat_tbl.grid(row=2, column=0, sticky='ew', pady=(2, 10))

        # —— 件表 ——
        itm_hdr = ttk.Frame(f)
        itm_hdr.grid(row=3, column=0, sticky='ew')
        ttk.Label(itm_hdr, text="必要件", font=('', 9, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Button(itm_hdr, text="清除全部", command=self._clear_items).grid(
            row=0, column=1, padx=(12, 0))
        self.itm_tbl = RowTable(f, ITM_HDR, ITM_WIDS, init_rows=4)
        self.itm_tbl.grid(row=4, column=0, sticky='ew', pady=(2, 0))

        # —— 填充件表 ——
        fill_hdr = ttk.Frame(f)
        fill_hdr.grid(row=5, column=0, sticky='ew')
        ttk.Label(fill_hdr, text="尾料利用",
                  font=('', 9, 'bold')).grid(row=0, column=0, sticky='w')
        ttk.Button(fill_hdr, text="清除全部",
                   command=self._clear_fill).grid(row=0, column=1, padx=(12, 0))
        self.var_fill_enable = tk.BooleanVar(value=True)
        ttk.Checkbutton(fill_hdr, text="启用填充",
                        variable=self.var_fill_enable).grid(row=0, column=2, padx=(16, 0))
        self.var_fill_last = tk.BooleanVar(value=True)
        ttk.Checkbutton(fill_hdr, text="最后一张填充",
                        variable=self.var_fill_last).grid(row=0, column=3, padx=(12, 0))
        self.fill_tbl = RowTable(f, FILL_HDR, FILL_WIDS, init_rows=0)
        self.fill_tbl.add_row(["42", "29.7", "", ""])
        self.fill_tbl.add_row(["29.7", "21", "", ""])
        self.fill_tbl.add_row(["21", "14.8", "", ""])
        self.fill_tbl.grid(row=6, column=0, sticky='ew', pady=(2, 0))

        # —— 按钮行 ——
        btn_row = ttk.Frame(f)
        btn_row.grid(row=7, column=0, pady=12, sticky='w')
        ttk.Button(btn_row, text="  预  览  ", command=self._preview_only).grid(
            row=0, column=0, ipadx=10, ipady=6)
        ttk.Button(btn_row, text="  生 成 EPS  ", command=self._run).grid(
            row=0, column=1, padx=(10, 0), ipadx=10, ipady=6)

        self.status = ttk.Label(f, text="填好参数后点生成",
                                foreground='gray', wraplength=500, justify='left')
        self.status.grid(row=8, column=0, sticky='w')

        # —— 右侧预览 ——
        sep = ttk.Separator(f, orient='vertical')
        sep.grid(row=0, column=1, rowspan=9, sticky='ns', padx=(16, 0))

        pf = ttk.Frame(f)
        pf.grid(row=0, column=2, rowspan=9, padx=(12, 0), sticky='n')

        ttk.Label(pf, text="预览", font=('', 9, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0, 4))

        self.canvas = tk.Canvas(pf, width=self.CVS_W, height=self.CVS_H,
                                bg='white', relief='sunken', bd=1, cursor='crosshair')
        self.canvas.grid(row=1, column=0, columnspan=3)

        nav = ttk.Frame(pf)
        nav.grid(row=2, column=0, columnspan=3, pady=(8, 0))
        self._btn_prev = ttk.Button(nav, text="◀", width=3, command=self._prev_sheet)
        self._btn_prev.grid(row=0, column=0)
        self._lbl_sheet = ttk.Label(nav, text="–", width=14, anchor='center')
        self._lbl_sheet.grid(row=0, column=1, padx=8)
        self._btn_next = ttk.Button(nav, text="▶", width=3, command=self._next_sheet)
        self._btn_next.grid(row=0, column=2)

        self._lbl_util = ttk.Label(pf, text="", foreground='gray')
        self._lbl_util.grid(row=3, column=0, columnspan=3, pady=(4, 0))

        self._draw_preview(None)  # 空白占位

    # ── 预览 ────────────────────────────────────────────────────────────────

    def _draw_preview(self, idx):
        self.canvas.delete('all')
        if idx is None or not self._sheets_data:
            self.canvas.create_text(self.CVS_W // 2, self.CVS_H // 2,
                                    text="生成后显示预览", fill='#aaa', font=('', 11))
            self._lbl_sheet.config(text='–')
            self._lbl_util.config(text='')
            self._btn_prev.config(state='disabled')
            self._btn_next.config(state='disabled')
            return

        self._cur_sheet = idx
        mat_w, mat_h, placed, secondary = self._sheets_data[idx]

        pad = self.CVS_PAD
        scale = min((self.CVS_W - 2*pad) / mat_w, (self.CVS_H - 2*pad) / mat_h)
        W, H = mat_w * scale, mat_h * scale
        ox = pad + (self.CVS_W - 2*pad - W) / 2
        oy = pad + (self.CVS_H - 2*pad - H) / 2

        self.canvas.create_rectangle(ox, oy, ox+W, oy+H,
                                     outline='#444', width=1.5, fill='#f5f5f5')

        def cx(ex):       return ox + ex * scale
        def cy(ey, eh=0): return oy + (mat_h - ey - eh) * scale

        # 利用率：总切割面积（外框面积-内孔面积）/ 材料面积
        # 嵌套件各自算自己的净面积，不会重复计算
        area_used = 0
        for typ, x, y, pw, ph, piw, pih in placed:
            area_used += pw * ph - (piw * pih if piw > 0 else 0)
            self.canvas.create_rectangle(cx(x), cy(y, ph), cx(x+pw), cy(y),
                                         outline='#cc0000', width=1, fill='#ffe4e4')
            if typ == 'frame' and piw > 0:
                ix = x + (pw - piw) / 2
                iy = y + (ph - pih) / 2
                self.canvas.create_rectangle(
                    cx(ix), cy(iy, pih), cx(ix+piw), cy(iy),
                    outline='#cc0000', width=1, fill='white')

        for x, y, pw, ph, piw, pih in secondary:
            x1, y1, x2, y2 = cx(x), cy(y, ph), cx(x+pw), cy(y)
            self.canvas.create_rectangle(x1, y1, x2, y2,
                                         outline='#0055cc', width=1, fill='#ddeeff')
            if piw > 0:
                ix = x + (pw - piw) / 2
                iy = y + (ph - pih) / 2
                self.canvas.create_rectangle(
                    cx(ix), cy(iy, pih), cx(ix+piw), cy(iy),
                    outline='#0055cc', width=1, fill='white')

        n    = len(self._sheets_data)
        util = area_used / (mat_w * mat_h) * 100
        self._lbl_sheet.config(text=f"第 {idx+1} / {n} 张")
        fill_info = f"  +{len(secondary)} 填充" if secondary else ""
        self._lbl_util.config(
            text=f"{len(placed)} 件{fill_info}   利用率 {util:.1f}%   ({mat_w}×{mat_h} cm)")
        self._btn_prev.config(state='normal' if idx > 0   else 'disabled')
        self._btn_next.config(state='normal' if idx < n-1 else 'disabled')

    def _prev_sheet(self):
        if self._cur_sheet > 0:
            self._draw_preview(self._cur_sheet - 1)

    def _next_sheet(self):
        if self._cur_sheet < len(self._sheets_data) - 1:
            self._draw_preview(self._cur_sheet + 1)

    # ── 解析 & 生成 ─────────────────────────────────────────────────────────

    def _parse_inputs(self):
        """解析界面输入，返回 (gap, materials, items)，出错时弹窗并返回 None。"""
        try:
            gap = float(self.e_gap.get())
            if gap < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("设置错误", "间距必须 ≥ 0")
            return None

        materials = []
        for r, vals in enumerate(self.mat_tbl.get_rows()):
            try:
                mw = float(vals[0]); mh = float(vals[1])
                if mw <= 0 or mh <= 0: raise ValueError()
                ms = int(float(vals[2])) if vals[2] else None
            except (ValueError, IndexError):
                messagebox.showerror("材料错误", f"材料第 {r+1} 行：宽/高必须大于 0，张数为正整数或留空")
                return None
            materials.append((mw, mh, ms))
        if not materials:
            messagebox.showwarning("提示", "请至少填写一种材料")
            return None

        items = []
        for r, vals in enumerate(self.itm_tbl.get_rows()):
            try:
                ow  = float(vals[0]); oh = float(vals[1])
                qty = int(float(vals[4])) if vals[4] else 0
                if ow <= 0 or oh <= 0 or qty <= 0: raise ValueError()
            except (ValueError, IndexError):
                messagebox.showerror("输入错误", f"件第 {r+1} 行：外框宽/高 和 数量 必须大于 0")
                return None
            has_w, has_h = vals[2] != '', vals[3] != ''
            if has_w != has_h:
                messagebox.showerror("输入错误", f"件第 {r+1} 行：内孔宽和高要么都填，要么都空")
                return None
            if has_w:
                try:
                    iw, ih = float(vals[2]), float(vals[3])
                    if iw <= 0 or ih <= 0 or iw >= ow or ih >= oh: raise ValueError()
                except ValueError:
                    messagebox.showerror("输入错误", f"件第 {r+1} 行：内孔必须 > 0 且小于外框")
                    return None
                typ = 'frame'
            else:
                iw = ih = 0.0; typ = 'solid'
            items.append((typ, ow, oh, iw, ih, qty))
        if not items:
            messagebox.showwarning("提示", "请至少填写一种件")
            return None

        return gap, materials, items

    def _read_fill_sizes(self):
        sizes = []
        for vals in self.fill_tbl.get_rows():
            try:
                fw, fh = float(vals[0]), float(vals[1])
                if fw <= 0 or fh <= 0: continue
                has_w = len(vals) > 2 and vals[2] != ''
                has_h = len(vals) > 3 and vals[3] != ''
                if has_w != has_h: continue
                if has_w:
                    fiw, fih = float(vals[2]), float(vals[3])
                    if fiw <= 0 or fih <= 0 or fiw >= fw or fih >= fh: continue
                else:
                    fiw = fih = 0.0
                sizes.append((fw, fh, fiw, fih))
            except (ValueError, IndexError):
                continue
        return sizes  # 顺序由 _make_fill_groups 按面积分组排序

    def _do_pack(self, gap, materials, items):
        """执行排版+填充并更新预览，返回 (sheets, n_remaining)。"""
        if self.var_fill_enable.get():
            fill_sizes = self._read_fill_sizes()
            fill_last  = self.var_fill_last.get()
        else:
            fill_sizes = None
            fill_last  = True
        sheets, n_remaining = pack(items, materials, gap, fill_sizes, fill_last)
        self._sheets_data = sheets
        self._draw_preview(len(sheets) - 1 if sheets else None)
        if n_remaining > 0:
            messagebox.showwarning(
                "材料不足",
                f"仍有 {n_remaining} 件排不下。\n"
                f"请在材料列表中增加新材料（或增大可用张数）后重新生成。")
        return sheets, n_remaining

    def _clear_items(self):
        self.itm_tbl.clear()

    def _clear_fill(self):
        self.fill_tbl.clear(keep_rows=0)

    # ── 持久化 ──────────────────────────────────────────────────────────────
    def _save_settings(self):
        try:
            data = {
                'prefixes': self.prefix_bar.get_all(),
                'gap':      self.e_gap.get(),
                'materials': self.mat_tbl.get_rows(),
                'items':    self.itm_tbl.get_rows(),
                'fill':     self.fill_tbl.get_rows(),
                'fill_enable': self.var_fill_enable.get(),
                'fill_last':   self.var_fill_last.get(),
            }
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_settings(self):
        if not os.path.exists(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'prefixes' in data:
                self.prefix_bar.reset(data['prefixes'])
            if 'gap' in data:
                self.e_gap.delete(0, 'end')
                self.e_gap.insert(0, data['gap'])
            if 'materials' in data:
                self.mat_tbl.clear(keep_rows=0)
                for row in data['materials']:
                    self.mat_tbl.add_row(row)
            if 'items' in data:
                self.itm_tbl.clear(keep_rows=0)
                for row in data['items']:
                    self.itm_tbl.add_row(row)
            if 'fill' in data:
                self.fill_tbl.clear(keep_rows=0)
                for row in data['fill']:
                    self.fill_tbl.add_row(row)
            self.var_fill_enable.set(data.get('fill_enable', True))
            self.var_fill_last.set(data.get('fill_last', True))
        except Exception:
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()

    def _preview_only(self):
        result = self._parse_inputs()
        if result is None: return
        gap, materials, items = result
        sheets, n_remaining = self._do_pack(gap, materials, items)
        total = sum(q for *_, q in items) - n_remaining
        msg = (f"预览：共 {len(sheets)} 张，{total} 件"
               f"{'，' + str(n_remaining) + ' 件未排入' if n_remaining else ''}")
        self.status.configure(text=msg, foreground='#555')

    def _run(self):
        result = self._parse_inputs()
        if result is None: return
        gap, materials, items = result
        sheets, n_remaining = self._do_pack(gap, materials, items)
        if not sheets:
            messagebox.showerror("错误", "所有件都无法放入任何材料，请检查尺寸与间距")
            return

        prefix = self.prefix_bar.get()
        date   = datetime.now().strftime("%Y%m%d")
        base   = os.path.join(_app_dir(), date)
        os.makedirs(base, exist_ok=True)
        uid    = uuid.uuid4().hex[:8]
        fnames = []
        for i, (mat_w, mat_h, placed, secondary) in enumerate(self._sheets_data):
            fname = f"{prefix}-{i+1}-{uid}.eps"
            make_eps(placed, os.path.join(base, fname), mat_w, mat_h, secondary)
            fnames.append(fname)

        total = sum(q for *_, q in items) - n_remaining
        msg = (f"✓  共 {len(sheets)} 张，{total} 件已排版"
               f"{'，' + str(n_remaining) + ' 件未排入' if n_remaining else ''}\n"
               f"文件：{chr(10).join(fnames)}")
        self.status.configure(text=msg, foreground='darkgreen' if not n_remaining else 'darkorange')


if __name__ == '__main__':
    App().mainloop()
