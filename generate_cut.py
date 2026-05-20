#!/usr/bin/env python3
"""切割机路径生成器"""

import os, sys, uuid, json
from datetime import datetime
from rectpack import newPacker, PackingMode, MaxRectsBssf

from PyQt6.QtCore import Qt, QRectF, QSize
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QLineEdit, QPushButton,
    QCheckBox, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QMessageBox,
    QInputDialog, QSizePolicy, QScrollArea, QGraphicsDropShadowEffect,
)

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
    placed   : [(type, x, y, pw, ph, piw, pih, off_x, off_y)]  单位 cm
    secondary: [(x, y, pw, ph, piw, pih)]                       填充件,单位 cm
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
    for typ, x, y, pw, ph, piw, pih, off_x, off_y in placed:
        _rect(lines, p(x), p(y), p(x+pw), p(y+ph))
    for x, y, pw, ph, piw, pih in sec:
        _rect(lines, p(x), p(y), p(x+pw), p(y+ph))
    lines.append("stroke")

    # ── 内孔路径 ──
    inner_lines = []
    for typ, x, y, pw, ph, piw, pih, off_x, off_y in placed:
        if piw > 0:
            xp, yp, pwp, php = p(x), p(y), p(pw), p(ph)
            piwp, pihp = p(piw), p(pih)
            oxp, oyp = p(off_x), p(off_y)
            _rect(inner_lines, xp+(pwp-piwp)/2+oxp, yp+(php-pihp)/2+oyp,
                               xp+(pwp+piwp)/2+oxp, yp+(php+pihp)/2+oyp)
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
    placed          : [(typ, x, y, pw, ph, piw, pih, off_x, off_y)]  bin 坐标
    secondary_outer : [(x, y, pw, ph, piw, pih)]                      bin 坐标
    """
    if not singles:
        return [], [], []

    packer = newPacker(mode=PackingMode.Offline, pack_algo=MaxRectsBssf, rotation=True)
    packer.add_bin(usable_w + gap, usable_h + gap)
    for i, (typ, ow, oh, iw, ih, ox, oy) in enumerate(singles):
        packer.add_rect(ow + gap, oh + gap, rid=i)
    packer.pack()

    placed, placed_idx = [], set()
    secondary_outer = []

    for b in packer:
        for r in b:
            i = r.rid
            typ, ow, oh, iw, ih, ox, oy = singles[i]
            placed_idx.add(i)
            if abs(r.width - (ow + gap)) < 1e-6:
                pw, ph, piw, pih, pox, poy = ow, oh, iw, ih, ox, oy
            else:
                # 件被 rectpack 旋转 90°(约定逆时针):偏移随件一起转
                pw, ph, piw, pih, pox, poy = oh, ow, ih, iw, -oy, ox
            placed.append((typ, float(r.x), float(r.y), pw, ph, piw, pih, pox, poy))

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
    hole_placed    : [(typ,x,y,pw,ph,piw,pih,off_x,off_y)]  必要件，加入 placed（sheet 坐标）
    hole_secondary : [(x,y,pw,ph,piw,pih)]                   填充件（sheet 坐标）
    still_remaining: 仍未排版的必要件
    """
    hole_placed = []
    hole_secondary = []
    still_remaining = list(remaining)

    for typ, x, y, pw, ph, piw, pih, off_x, off_y in placed_sheet:
        if typ != 'frame' or piw <= 0:
            continue
        hx = x + (pw - piw) / 2 + off_x
        hy = y + (ph - pih) / 2 + off_y
        avail_w = piw - 2 * gap
        avail_h = pih - 2 * gap
        if avail_w <= 0 or avail_h <= 0:
            continue

        hole_bin = MaxRectsBssf(avail_w + gap, avail_h + gap, rot=True)

        # 阶段 1：将剩余必要件（大→小）尽量塞入内孔
        still_remaining.sort(key=lambda t: -(t[1] * t[2]))
        placed_set = set()
        for i, (rtyp, ow, oh, iw, ih, rox, roy) in enumerate(still_remaining):
            placed_r = hole_bin.add_rect(ow + gap, oh + gap)
            if placed_r is None and ow != oh:
                placed_r = hole_bin.add_rect(oh + gap, ow + gap)
            if placed_r is None:
                continue
            placed_set.add(i)
            if abs(placed_r.width - (ow + gap)) < 1e-6:
                rpw, rph, rpiw, rpih, rpox, rpoy = ow, oh, iw, ih, rox, roy
            else:
                rpw, rph, rpiw, rpih, rpox, rpoy = oh, ow, ih, iw, -roy, rox
            hole_placed.append((rtyp,
                                hx + gap + float(placed_r.x),
                                hy + gap + float(placed_r.y),
                                rpw, rph, rpiw, rpih, rpox, rpoy))
        still_remaining = [t for i, t in enumerate(still_remaining) if i not in placed_set]

        # 阶段 2：用填充件填满剩余内孔空间
        if fill_sizes:
            for rx, ry, rw, rh, riw, rih in _apply_fill(hole_bin, fill_sizes, gap):
                hole_secondary.append((hx + gap + rx, hy + gap + ry,
                                       rw, rh, riw, rih))

    return hole_placed, hole_secondary, still_remaining


def pack(items, materials, gap, fill_sizes=None, fill_last=True):
    """
    items      : [(type, ow, oh, iw, ih, ox, oy, qty)]
    materials  : [(mat_w, mat_h, max_sheets)]
    fill_sizes : [(fw, fh, fiw, fih)] 或 None
    fill_last  : False 时最后一张不填充
    返回 (sheets, n_remaining)
    sheets: [(mat_w, mat_h, placed, secondary)]
    """
    singles = []
    for typ, ow, oh, iw, ih, ox, oy, qty in items:
        singles += [(typ, ow, oh, iw, ih, ox, oy)] * qty
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
            placed_off = [(t, x+gap, y+gap, pw, ph, piw, pih, ox, oy)
                          for t, x, y, pw, ph, piw, pih, ox, oy in placed]
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

MAT_HDR  = ["材料宽(cm)", "材料高(cm)", "可用张数\n(留空=不限)"]
MAT_WIDS = [80, 80, 100]
ITM_HDR  = ["外框宽(cm)", "外框高(cm)", "内孔宽(cm)\n留空=实心", "内孔高(cm)\n留空=实心",
            "X偏移(cm)\n右正,留空=0", "Y偏移(cm)\n上正,留空=0", "数量"]
ITM_WIDS = [78, 78, 90, 90, 90, 90, 56]
FILL_HDR  = ["外框宽(cm)", "外框高(cm)", "内孔宽(cm)\n留空=实心", "内孔高(cm)\n留空=实心"]
FILL_WIDS = [78, 78, 90, 90]


class RowTable(QWidget):
    """通用可增删行的表格组件。has_enable=True 时每行首列有启用勾选框。"""

    def __init__(self, headers, widths, init_rows=3, has_enable=False, parent=None):
        super().__init__(parent)
        self.headers = headers
        self.widths = widths
        self.has_enable = has_enable
        self.rows = []  # list of dicts: {'edits':[QLineEdit...], 'del':QPushButton, 'cb':QCheckBox|None}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # 表头
        self._hdr = QWidget()
        hdr_lay = QHBoxLayout(self._hdr)
        hdr_lay.setContentsMargins(0, 0, 0, 4)
        hdr_lay.setSpacing(4)
        if has_enable:
            lbl = QLabel("启用")
            lbl.setFixedWidth(38)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr_lay.addWidget(lbl)
        for h, w in zip(headers, widths):
            lbl = QLabel(h)
            lbl.setFixedWidth(w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr_lay.addWidget(lbl)
        # 删除按钮列占位
        sp = QLabel("")
        sp.setFixedWidth(26)
        hdr_lay.addWidget(sp)
        hdr_lay.addStretch()
        outer.addWidget(self._hdr)

        # 行容器
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(2)
        outer.addWidget(self._body)

        # 增加一行按钮
        add_btn = QPushButton("＋ 增加一行")
        add_btn.setFixedHeight(24)
        add_btn.clicked.connect(lambda: self.add_row())
        add_row_wrap = QHBoxLayout()
        add_row_wrap.setContentsMargins(0, 4, 0, 0)
        add_row_wrap.addWidget(add_btn)
        add_row_wrap.addStretch()
        outer.addLayout(add_row_wrap)

        for _ in range(init_rows):
            self.add_row()

    def add_row(self, prefill=None):
        n_data = len(self.widths)
        row_w = QWidget()
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(4)

        cb = None
        if self.has_enable:
            cb = QCheckBox()
            # prefill 最后一个元素为 '0' 时默认不启用
            init_on = True
            if prefill and len(prefill) > n_data:
                init_on = prefill[n_data] != '0'
            cb.setChecked(init_on)
            cb_wrap = QWidget()
            cb_wrap_lay = QHBoxLayout(cb_wrap)
            cb_wrap_lay.setContentsMargins(0, 0, 0, 0)
            cb_wrap_lay.addStretch()
            cb_wrap_lay.addWidget(cb)
            cb_wrap_lay.addStretch()
            cb_wrap.setFixedWidth(38)
            row_lay.addWidget(cb_wrap)

        edits = []
        for c, w in enumerate(self.widths):
            e = QLineEdit()
            e.setFixedWidth(w)
            pval = prefill[c] if prefill and c < len(prefill) else ''
            if pval:
                e.setText(str(pval))
            edits.append(e)
            row_lay.addWidget(e)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(26, 24)
        row_lay.addWidget(del_btn)
        row_lay.addStretch()

        row_info = {'widget': row_w, 'edits': edits, 'del': del_btn, 'cb': cb}
        del_btn.clicked.connect(lambda _=False, ri=row_info: self.del_row(ri))

        if cb is not None:
            def _toggle(state, edits=edits, cb=cb):
                on = cb.isChecked()
                for e in edits:
                    e.setEnabled(on)
                    # 视觉灰化
                    pal = e.palette()
                    if on:
                        e.setStyleSheet("")
                    else:
                        e.setStyleSheet("background: #eee; color: #888;")
            cb.stateChanged.connect(_toggle)
            if not cb.isChecked():
                _toggle(0)

        self.rows.append(row_info)
        self._body_lay.addWidget(row_w)

    def del_row(self, row_info):
        if len(self.rows) <= 1:
            return
        self.rows = [r for r in self.rows if r is not row_info]
        row_info['widget'].setParent(None)
        row_info['widget'].deleteLater()

    def get_rows(self):
        """返回每行的 [str, ...] 列表，跳过全空行。
        has_enable=True 时末尾追加 '1'/'0' 表示启用状态（用于持久化）。"""
        result = []
        for r in self.rows:
            vals = [e.text().strip() for e in r['edits']]
            if any(vals):
                if self.has_enable:
                    vals.append('1' if r['cb'].isChecked() else '0')
                result.append(vals)
        return result

    def clear(self, keep_rows=2):
        """清空所有行，保留 keep_rows 个空行。"""
        for r in list(self.rows):
            r['widget'].setParent(None)
            r['widget'].deleteLater()
        self.rows = []
        for _ in range(keep_rows):
            self.add_row()


class PrefixBar(QWidget):
    """一排可编辑、可选的前缀按钮，点击选中，文字可直接改。"""

    SEL_BG = '#0078d4'
    SEL_FG = 'white'
    NOR_BG = '#e8e8e8'
    NOR_FG = 'black'

    def __init__(self, defaults=("卡纸路径",), parent=None):
        super().__init__(parent)
        self._tags = []
        self._selected = None

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(6)

        self._tags_holder = QWidget()
        self._tags_lay = QHBoxLayout(self._tags_holder)
        self._tags_lay.setContentsMargins(0, 0, 0, 0)
        self._tags_lay.setSpacing(4)
        self._lay.addWidget(self._tags_holder)

        add_btn = QPushButton("＋")
        add_btn.setFixedSize(26, 26)
        add_btn.setFlat(True)
        add_btn.clicked.connect(lambda: self.add_tag())
        self._lay.addWidget(add_btn)
        self._lay.addStretch()

        for name in defaults:
            self.add_tag(name)

    def add_tag(self, text="新前缀"):
        tag_w = QFrame()
        tag_w.setFrameShape(QFrame.Shape.NoFrame)
        tag_lay = QHBoxLayout(tag_w)
        tag_lay.setContentsMargins(6, 3, 4, 3)
        tag_lay.setSpacing(2)

        edit = QLineEdit(text)
        edit.setFrame(False)
        fm = QFontMetrics(edit.font())
        edit.setFixedWidth(max(60, fm.horizontalAdvance(text) + 16))

        del_btn = QPushButton("×")
        del_btn.setFixedSize(16, 16)
        del_btn.setFlat(True)

        tag_lay.addWidget(edit)
        tag_lay.addWidget(del_btn)

        tag = {'edit': edit, 'frame': tag_w, 'del': del_btn}

        def _resize():
            t = edit.text()
            edit.setFixedWidth(max(60, fm.horizontalAdvance(t) + 16))
        edit.textChanged.connect(_resize)

        # 点击 edit 或 frame 都选中
        orig_focus_in = edit.focusInEvent
        def _focus_in(ev, t=tag):
            self._select(t)
            orig_focus_in(ev)
        edit.focusInEvent = _focus_in

        orig_mp = tag_w.mousePressEvent
        def _mp(ev, t=tag):
            self._select(t)
            orig_mp(ev)
        tag_w.mousePressEvent = _mp

        del_btn.clicked.connect(lambda _=False, t=tag: self._del_tag(t))

        self._tags.append(tag)
        self._tags_lay.addWidget(tag_w)
        if self._selected is None:
            self._select(tag)
        else:
            self._restyle()
        return tag

    def _del_tag(self, tag):
        if len(self._tags) <= 1:
            return
        was_sel = (self._selected is tag)
        self._tags.remove(tag)
        tag['frame'].setParent(None)
        tag['frame'].deleteLater()
        if was_sel:
            self._select(self._tags[0])
        else:
            self._restyle()

    def _select(self, tag):
        self._selected = tag
        self._restyle()

    def _restyle(self):
        for t in self._tags:
            sel = (t is self._selected)
            bg = self.SEL_BG if sel else self.NOR_BG
            fg = self.SEL_FG if sel else self.NOR_FG
            t['frame'].setStyleSheet(f"QFrame {{ background: {bg}; border-radius: 4px; }}")
            t['edit'].setStyleSheet(f"QLineEdit {{ background: {bg}; color: {fg}; border: none; }}")
            t['del'].setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {'white' if sel else '#888'}; "
                f"border: none; font-weight: bold; }}")

    def get(self):
        if self._selected:
            return self._selected['edit'].text().strip() or "卡纸路径"
        return "卡纸路径"

    def get_all(self):
        return [t['edit'].text() for t in self._tags]

    def reset(self, names):
        for t in list(self._tags):
            t['frame'].setParent(None)
            t['frame'].deleteLater()
        self._tags = []
        self._selected = None
        for name in (names or ["卡纸路径"]):
            self.add_tag(name)


class PreviewCanvas(QWidget):
    """排版预览画布,自绘。"""

    CVS_W, CVS_H, CVS_PAD = 460, 380, 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.CVS_W, self.CVS_H)
        self.setStyleSheet("background: white; border: 1px solid #888;")
        self._sheet = None  # (mat_w, mat_h, placed, secondary) 或 None

    def set_sheet(self, sheet):
        self._sheet = sheet
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 背景
        p.fillRect(self.rect(), QColor('white'))

        if self._sheet is None:
            p.setPen(QColor('#aaa'))
            f = QFont(); f.setPointSize(11)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "生成后显示预览")
            return

        mat_w, mat_h, placed, secondary = self._sheet
        pad = self.CVS_PAD
        scale = min((self.CVS_W - 2*pad) / mat_w, (self.CVS_H - 2*pad) / mat_h)
        W, H = mat_w * scale, mat_h * scale
        ox = pad + (self.CVS_W - 2*pad - W) / 2
        oy = pad + (self.CVS_H - 2*pad - H) / 2

        # 材料底
        p.setPen(QPen(QColor('#444'), 1.5))
        p.setBrush(QColor('#f5f5f5'))
        p.drawRect(QRectF(ox, oy, W, H))

        def cx(ex):       return ox + ex * scale
        def cy(ey, eh=0): return oy + (mat_h - ey - eh) * scale

        # 主件
        red_pen = QPen(QColor('#cc0000'), 1)
        for typ, x, y, pw, ph, piw, pih, off_x, off_y in placed:
            p.setPen(red_pen)
            p.setBrush(QColor('#ffe4e4'))
            p.drawRect(QRectF(cx(x), cy(y, ph), pw * scale, ph * scale))
            if typ == 'frame' and piw > 0:
                ix = x + (pw - piw) / 2 + off_x
                iy = y + (ph - pih) / 2 + off_y
                p.setBrush(QColor('white'))
                p.drawRect(QRectF(cx(ix), cy(iy, pih), piw * scale, pih * scale))

        # 尾料
        blue_pen = QPen(QColor('#0055cc'), 1)
        for x, y, pw, ph, piw, pih in secondary:
            p.setPen(blue_pen)
            p.setBrush(QColor('#ddeeff'))
            p.drawRect(QRectF(cx(x), cy(y, ph), pw * scale, ph * scale))
            if piw > 0:
                ix = x + (pw - piw) / 2
                iy = y + (ph - pih) / 2
                p.setBrush(QColor('white'))
                p.drawRect(QRectF(cx(ix), cy(iy, pih), piw * scale, pih * scale))

        p.end()


class App(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("切割路径生成器")
        self._sheets_data = []
        self._cur_sheet = 0
        self._ru_dan_url = ''
        self._build()
        self._load_settings()
        self._update_preview(None)

    # ── 构建 GUI ─────────────────────────────────────────────────────────────

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # —— 左侧参数区(整体可滚动) ——
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)
        left_scroll.setWidget(left)
        root.addWidget(left_scroll, 1)

        # 顶部设置行
        top = QWidget()
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(6)

        top_lay.addWidget(QLabel("文件前缀:"))
        self.prefix_bar = PrefixBar(defaults=("卡纸路径", "相框", "备用"))
        top_lay.addWidget(self.prefix_bar)

        top_lay.addSpacing(12)
        top_lay.addWidget(QLabel("间距(cm):"))
        self.e_gap = QLineEdit("1")
        self.e_gap.setFixedWidth(50)
        top_lay.addWidget(self.e_gap)
        gap_hint = QLabel("(0=共刀)")
        gap_hint.setStyleSheet("color: gray;")
        top_lay.addWidget(gap_hint)

        top_lay.addSpacing(20)
        pull_btn = QPushButton("📥 从服务器拉数据")
        pull_btn.clicked.connect(self._pull_from_server)
        top_lay.addWidget(pull_btn)
        top_lay.addStretch()

        left_lay.addWidget(top)

        # 双栏:左 材料+必要件,右 尾料利用
        cols = QWidget()
        cols_lay = QHBoxLayout(cols)
        cols_lay.setContentsMargins(0, 0, 0, 0)
        cols_lay.setSpacing(16)

        col0 = QWidget()
        col0_lay = QVBoxLayout(col0)
        col0_lay.setContentsMargins(0, 0, 0, 0)
        col0_lay.setSpacing(4)

        mat_title = QLabel("材料(按优先级从上到下)")
        f = QFont(); f.setBold(True); f.setPointSize(10)
        mat_title.setFont(f)
        col0_lay.addWidget(mat_title)
        self.mat_tbl = RowTable(MAT_HDR, MAT_WIDS, init_rows=2)
        col0_lay.addWidget(self.mat_tbl)
        col0_lay.addSpacing(10)

        itm_hdr_w = QWidget()
        itm_hdr_lay = QHBoxLayout(itm_hdr_w)
        itm_hdr_lay.setContentsMargins(0, 0, 0, 0)
        itm_title = QLabel("必要件")
        itm_title.setFont(f)
        itm_hdr_lay.addWidget(itm_title)
        itm_hdr_lay.addSpacing(8)
        clear_items_btn = QPushButton("清除全部")
        clear_items_btn.clicked.connect(self._clear_items)
        itm_hdr_lay.addWidget(clear_items_btn)
        itm_hdr_lay.addStretch()
        col0_lay.addWidget(itm_hdr_w)
        self.itm_tbl = RowTable(ITM_HDR, ITM_WIDS, init_rows=4)
        col0_lay.addWidget(self.itm_tbl)
        col0_lay.addStretch()

        cols_lay.addWidget(col0)

        col1 = QWidget()
        col1_lay = QVBoxLayout(col1)
        col1_lay.setContentsMargins(0, 0, 0, 0)
        col1_lay.setSpacing(4)

        fill_hdr_w = QWidget()
        fill_hdr_lay = QHBoxLayout(fill_hdr_w)
        fill_hdr_lay.setContentsMargins(0, 0, 0, 0)
        fill_title = QLabel("尾料利用")
        fill_title.setFont(f)
        fill_hdr_lay.addWidget(fill_title)
        fill_hdr_lay.addSpacing(8)
        clear_fill_btn = QPushButton("清除全部")
        clear_fill_btn.clicked.connect(self._clear_fill)
        fill_hdr_lay.addWidget(clear_fill_btn)
        fill_hdr_lay.addSpacing(12)
        self.cb_fill_last = QCheckBox("最后一张填充")
        self.cb_fill_last.setChecked(True)
        fill_hdr_lay.addWidget(self.cb_fill_last)
        fill_hdr_lay.addStretch()
        col1_lay.addWidget(fill_hdr_w)

        self.fill_tbl = RowTable(FILL_HDR, FILL_WIDS, init_rows=0, has_enable=True)
        self.fill_tbl.add_row(["42",   "29.7", "", "", "1"])
        self.fill_tbl.add_row(["29.7", "21",   "", "", "1"])
        self.fill_tbl.add_row(["21",   "14.8", "", "", "1"])
        col1_lay.addWidget(self.fill_tbl)
        col1_lay.addStretch()

        cols_lay.addWidget(col1)
        cols_lay.addStretch()
        left_lay.addWidget(cols)

        # 按钮行
        btn_row = QWidget()
        btn_lay = QHBoxLayout(btn_row)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(10)
        self.preview_btn = QPushButton("  预  览  ")
        self.preview_btn.setFixedHeight(36)
        self.preview_btn.clicked.connect(self._preview_only)
        btn_lay.addWidget(self.preview_btn)
        self.gen_btn = QPushButton("  生 成 EPS  ")
        self.gen_btn.setFixedHeight(36)
        self.gen_btn.clicked.connect(self._run)
        btn_lay.addWidget(self.gen_btn)
        btn_lay.addStretch()
        left_lay.addWidget(btn_row)

        # 状态行
        self.status = QLabel("填好参数后点生成")
        self.status.setStyleSheet("color: gray;")
        self.status.setWordWrap(True)
        left_lay.addWidget(self.status)
        left_lay.addStretch()

        # —— 分隔 ——
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # —— 右侧预览 ——
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        prev_title = QLabel("预览")
        prev_title.setFont(f)
        right_lay.addWidget(prev_title)

        self.canvas = PreviewCanvas()
        right_lay.addWidget(self.canvas)

        nav = QWidget()
        nav_lay = QHBoxLayout(nav)
        nav_lay.setContentsMargins(0, 4, 0, 0)
        nav_lay.addStretch()
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(36, 24)
        self.btn_prev.clicked.connect(self._prev_sheet)
        nav_lay.addWidget(self.btn_prev)
        self.lbl_sheet = QLabel("–")
        self.lbl_sheet.setFixedWidth(120)
        self.lbl_sheet.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_lay.addWidget(self.lbl_sheet)
        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(36, 24)
        self.btn_next.clicked.connect(self._next_sheet)
        nav_lay.addWidget(self.btn_next)
        nav_lay.addStretch()
        right_lay.addWidget(nav)

        self.lbl_util = QLabel("")
        self.lbl_util.setStyleSheet("color: gray;")
        self.lbl_util.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_lay.addWidget(self.lbl_util)
        right_lay.addStretch()

        root.addWidget(right)

    # ── 预览 ────────────────────────────────────────────────────────────────

    def _update_preview(self, idx):
        if idx is None or not self._sheets_data:
            self.canvas.set_sheet(None)
            self.lbl_sheet.setText('–')
            self.lbl_util.setText('')
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return

        self._cur_sheet = idx
        sheet = self._sheets_data[idx]
        mat_w, mat_h, placed, secondary = sheet
        self.canvas.set_sheet(sheet)

        area_used = 0
        for typ, x, y, pw, ph, piw, pih, off_x, off_y in placed:
            area_used += pw * ph - (piw * pih if piw > 0 else 0)
        n = len(self._sheets_data)
        util = area_used / (mat_w * mat_h) * 100
        self.lbl_sheet.setText(f"第 {idx+1} / {n} 张")
        fill_info = f"  +{len(secondary)} 填充" if secondary else ""
        self.lbl_util.setText(
            f"{len(placed)} 件{fill_info}   利用率 {util:.1f}%   ({mat_w}×{mat_h} cm)")
        self.btn_prev.setEnabled(idx > 0)
        self.btn_next.setEnabled(idx < n - 1)

    def _prev_sheet(self):
        if self._cur_sheet > 0:
            self._update_preview(self._cur_sheet - 1)

    def _next_sheet(self):
        if self._cur_sheet < len(self._sheets_data) - 1:
            self._update_preview(self._cur_sheet + 1)

    # ── 解析 & 生成 ─────────────────────────────────────────────────────────

    def _parse_inputs(self):
        """解析界面输入,返回 (gap, materials, items),出错时弹窗并返回 None。"""
        try:
            gap = float(self.e_gap.text())
            if gap < 0:
                raise ValueError
        except ValueError:
            QMessageBox.critical(self, "设置错误", "间距必须 ≥ 0")
            return None

        materials = []
        for r, vals in enumerate(self.mat_tbl.get_rows()):
            try:
                mw = float(vals[0]); mh = float(vals[1])
                if mw <= 0 or mh <= 0: raise ValueError()
                ms = int(float(vals[2])) if len(vals) > 2 and vals[2] else None
            except (ValueError, IndexError):
                QMessageBox.critical(self, "材料错误",
                                     f"材料第 {r+1} 行:宽/高必须大于 0,张数为正整数或留空")
                return None
            materials.append((mw, mh, ms))
        if not materials:
            QMessageBox.warning(self, "提示", "请至少填写一种材料")
            return None

        items = []
        for r, vals in enumerate(self.itm_tbl.get_rows()):
            # 兼容旧版本(只有 5 列):补齐到 7 列
            while len(vals) < 7:
                vals.insert(4, '')
            try:
                ow  = float(vals[0]); oh = float(vals[1])
                qty = int(float(vals[6])) if vals[6] else 0
                if ow <= 0 or oh <= 0 or qty <= 0: raise ValueError()
            except (ValueError, IndexError):
                QMessageBox.critical(self, "输入错误",
                                     f"件第 {r+1} 行:外框宽/高 和 数量 必须大于 0")
                return None
            has_w, has_h = vals[2] != '', vals[3] != ''
            if has_w != has_h:
                QMessageBox.critical(self, "输入错误",
                                     f"件第 {r+1} 行:内孔宽和高要么都填,要么都空")
                return None
            if has_w:
                try:
                    iw, ih = float(vals[2]), float(vals[3])
                    if iw <= 0 or ih <= 0 or iw >= ow or ih >= oh: raise ValueError()
                except ValueError:
                    QMessageBox.critical(self, "输入错误",
                                         f"件第 {r+1} 行:内孔必须 > 0 且小于外框")
                    return None
                typ = 'frame'
                try:
                    ox = float(vals[4]) if vals[4] else 0.0
                    oy = float(vals[5]) if vals[5] else 0.0
                except ValueError:
                    QMessageBox.critical(self, "输入错误",
                                         f"件第 {r+1} 行:偏移必须是数字")
                    return None
                max_ox = (ow - iw) / 2
                max_oy = (oh - ih) / 2
                if abs(ox) > max_ox + 1e-9 or abs(oy) > max_oy + 1e-9:
                    QMessageBox.critical(
                        self, "输入错误",
                        f"件第 {r+1} 行:偏移过大,内孔会超出外框\n"
                        f"X 偏移范围 ±{max_ox:g},Y 偏移范围 ±{max_oy:g}")
                    return None
            else:
                iw = ih = 0.0; typ = 'solid'
                if vals[4] or vals[5]:
                    QMessageBox.critical(self, "输入错误",
                                         f"件第 {r+1} 行:实心件不能有偏移")
                    return None
                ox = oy = 0.0
            items.append((typ, ow, oh, iw, ih, ox, oy, qty))
        if not items:
            QMessageBox.warning(self, "提示", "请至少填写一种件")
            return None

        return gap, materials, items

    def _read_fill_sizes(self):
        sizes = []
        for vals in self.fill_tbl.get_rows():
            try:
                # get_rows() 末尾追加 '1'/'0' 启用标志
                if vals and vals[-1] == '0':
                    continue
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
        """执行排版+填充并更新预览,返回 (sheets, n_remaining)。"""
        fill_sizes = self._read_fill_sizes() or None
        fill_last  = self.cb_fill_last.isChecked()
        sheets, n_remaining = pack(items, materials, gap, fill_sizes, fill_last)
        self._sheets_data = sheets
        self._update_preview(len(sheets) - 1 if sheets else None)
        if n_remaining > 0:
            QMessageBox.warning(
                self, "材料不足",
                f"仍有 {n_remaining} 件排不下。\n"
                f"请在材料列表中增加新材料(或增大可用张数)后重新生成。")
        return sheets, n_remaining

    def _clear_items(self):
        self.itm_tbl.clear()

    def _clear_fill(self):
        self.fill_tbl.clear(keep_rows=0)

    # ── 从 ru-dan-server 拉数据 ────────────────────────────────────────────
    def _pull_from_server(self):
        """业务员在 ru-dan 建单时录的切割结构化数据(orders.cut_items),按日期拉来填进必要件表。

        ru-dan-server 端点:GET /orders/cutting?day=YYYY-MM-DD
        Response: {items: [{order_id, customer_name, ship_date, cut_items: [{...}]}]}
        """
        import urllib.request, urllib.parse as up

        default_url = self._ru_dan_url or 'http://192.168.0.110:8080'
        url, ok = QInputDialog.getText(
            self, "服务器地址", "ru-dan-server URL(下次记住):",
            text=default_url)
        if not ok or not url:
            return
        self._ru_dan_url = url.strip().rstrip('/')

        default_day = datetime.now().strftime("%Y-%m-%d")
        day, ok = QInputDialog.getText(
            self, "日期", "按 ship_date 拉(YYYY-MM-DD):",
            text=default_day)
        if not ok or not day:
            return

        full_url = f"{self._ru_dan_url}/orders/cutting?day={up.quote(day)}"
        try:
            with urllib.request.urlopen(full_url, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            QMessageBox.critical(
                self, "拉取失败",
                f"{type(e).__name__}: {e}\n\nURL: {full_url}")
            return

        items = data.get('items', [])
        if not items:
            QMessageBox.information(
                self, "无数据",
                f"{day} 没有切割单(orders.cut_items 字段为空)")
            return

        n_rows = 0
        self.itm_tbl.clear(keep_rows=0)
        for order in items:
            for ci in order.get('cut_items', []):
                self.itm_tbl.add_row([
                    str(ci.get('outer_w', '')),
                    str(ci.get('outer_h', '')),
                    str(ci.get('inner_w') or ''),
                    str(ci.get('inner_h') or ''),
                    str(ci.get('offset_x') or ''),
                    str(ci.get('offset_y') or ''),
                    str(ci.get('qty', 1)),
                ])
                n_rows += 1

        # 持久化 url 给下次用
        self._save_settings()
        QMessageBox.information(
            self, "拉取成功",
            f"导入 {n_rows} 行(覆盖原必要件表)\n"
            f"日期: {day}\n订单: {len(items)} 单")

    # ── 持久化 ──────────────────────────────────────────────────────────────

    def _save_settings(self):
        try:
            data = {
                'prefixes':   self.prefix_bar.get_all(),
                'gap':        self.e_gap.text(),
                'materials':  self.mat_tbl.get_rows(),
                'items':      self.itm_tbl.get_rows(),
                'fill':       self.fill_tbl.get_rows(),
                'fill_last':  self.cb_fill_last.isChecked(),
                'ru_dan_url': self._ru_dan_url,
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
                self.e_gap.setText(data['gap'])
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
            self.cb_fill_last.setChecked(data.get('fill_last', True))
            self._ru_dan_url = data.get('ru_dan_url', '') or ''
        except Exception:
            pass

    def closeEvent(self, ev):
        self._save_settings()
        super().closeEvent(ev)

    def _preview_only(self):
        result = self._parse_inputs()
        if result is None: return
        gap, materials, items = result
        sheets, n_remaining = self._do_pack(gap, materials, items)
        total = sum(q for *_, q in items) - n_remaining
        msg = (f"预览:共 {len(sheets)} 张,{total} 件"
               f"{',' + str(n_remaining) + ' 件未排入' if n_remaining else ''}")
        self.status.setStyleSheet("color: #555;")
        self.status.setText(msg)

    def _run(self):
        result = self._parse_inputs()
        if result is None: return
        gap, materials, items = result
        sheets, n_remaining = self._do_pack(gap, materials, items)
        if not sheets:
            QMessageBox.critical(self, "错误", "所有件都无法放入任何材料,请检查尺寸与间距")
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
        msg = (f"✓  共 {len(sheets)} 张,{total} 件已排版"
               f"{',' + str(n_remaining) + ' 件未排入' if n_remaining else ''}\n"
               f"文件:{chr(10).join(fnames)}")
        color = 'darkgreen' if not n_remaining else 'darkorange'
        self.status.setStyleSheet(f"color: {color};")
        self.status.setText(msg)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = App()
    win.resize(1200, 700)
    win.show()
    sys.exit(app.exec())
