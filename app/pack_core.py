"""排版核心：矩形拼板 + 内孔嵌套 + 尾料填充。件与 placed 携带 customer_code。"""

from rectpack import newPacker, PackingMode, MaxRectsBssf


def _make_fill_groups(fill_sizes):
    """按外框尺寸分组（旋转等价同组），组间面积降序。"""
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
    """向 bin 分组轮询填充。返回 [(x, y, pw, ph, piw, pih)]。"""
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
    singles: [(typ, ow, oh, iw, ih, customer_code)]
    placed:  [(typ, x, y, pw, ph, piw, pih, customer_code)]
    """
    if not singles:
        return [], [], []

    packer = newPacker(mode=PackingMode.Offline, pack_algo=MaxRectsBssf, rotation=True)
    packer.add_bin(usable_w + gap, usable_h + gap)
    for i, (typ, ow, oh, iw, ih, _code) in enumerate(singles):
        packer.add_rect(ow + gap, oh + gap, rid=i)
    packer.pack()

    placed, placed_idx = [], set()
    secondary_outer = []

    for b in packer:
        for r in b:
            i = r.rid
            typ, ow, oh, iw, ih, code = singles[i]
            placed_idx.add(i)
            if abs(r.width - (ow + gap)) < 1e-6:
                pw, ph, piw, pih = ow, oh, iw, ih
            else:
                pw, ph, piw, pih = oh, ow, ih, iw
            placed.append((typ, float(r.x), float(r.y), pw, ph, piw, pih, code))

        if fill_sizes:
            secondary_outer.extend(_apply_fill(b, fill_sizes, gap))

    remaining = [singles[j] for j in range(len(singles)) if j not in placed_idx]
    return placed, remaining, secondary_outer


def _process_holes(placed_sheet, remaining, gap, fill_sizes):
    """
    placed_sheet: [(typ,x,y,pw,ph,piw,pih,code)]
    remaining:    [(typ,ow,oh,iw,ih,code)]
    内孔仍按居中（首版）；后期可改为外框+偏移。
    """
    hole_placed = []
    hole_secondary = []
    still_remaining = list(remaining)

    for typ, x, y, pw, ph, piw, pih, _code in placed_sheet:
        if typ != 'frame' or piw <= 0:
            continue
        # 同心：内孔原点 = 外框原点 + 居中偏移（后期可换 iox/ioy）
        hx = x + (pw - piw) / 2
        hy = y + (ph - pih) / 2
        avail_w = piw - 2 * gap
        avail_h = pih - 2 * gap
        if avail_w <= 0 or avail_h <= 0:
            continue

        hole_bin = MaxRectsBssf(avail_w + gap, avail_h + gap, rot=True)

        still_remaining.sort(key=lambda t: -(t[1] * t[2]))
        placed_set = set()
        for i, (rtyp, ow, oh, iw, ih, rcode) in enumerate(still_remaining):
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
                                rpw, rph, rpiw, rpih, rcode))
        still_remaining = [t for i, t in enumerate(still_remaining) if i not in placed_set]

        if fill_sizes:
            for rx, ry, rw, rh, riw, rih in _apply_fill(hole_bin, fill_sizes, gap):
                hole_secondary.append((hx + gap + rx, hy + gap + ry,
                                       rw, rh, riw, rih))

    return hole_placed, hole_secondary, still_remaining


def pack(items, materials, gap, fill_sizes=None, fill_last=True):
    """
    items      : [(type, ow, oh, iw, ih, qty, customer_code)]
    materials  : [(mat_w, mat_h, max_sheets)] 或 [(mat_w, mat_h, max_sheets, name)]
    fill_sizes : [(fw, fh, fiw, fih)] 或 None
    返回 (sheets, n_remaining)
    sheets: [(mat_w, mat_h, placed, secondary, mat_name)]
    placed: [(typ, x, y, pw, ph, piw, pih, customer_code)]
    secondary: [(x, y, pw, ph, piw, pih)]
    """
    singles = []
    for typ, ow, oh, iw, ih, qty, code in items:
        singles += [(typ, ow, oh, iw, ih, code)] * int(qty)
    singles.sort(key=lambda t: (-max(t[2], t[1]), -min(t[2], t[1])))

    all_sheets = []
    for mat in materials:
        if len(mat) >= 4:
            mat_w, mat_h, max_sheets, mat_name = mat[0], mat[1], mat[2], mat[3]
        else:
            mat_w, mat_h, max_sheets = mat[0], mat[1], mat[2]
            mat_name = f'{mat_w:g}x{mat_h:g}'
        mat_name = (mat_name or '').strip() or f'{mat_w:g}x{mat_h:g}'
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
            placed_off = [(t, x + gap, y + gap, pw, ph, piw, pih, code)
                          for t, x, y, pw, ph, piw, pih, code in placed]
            sec_outer_off = [(x + gap, y + gap, pw, ph, piw, pih)
                             for x, y, pw, ph, piw, pih in sec_outer]
            all_hole_secondary = []
            to_process = placed_off[:]
            while to_process:
                hole_placed, hole_secondary, singles = _process_holes(
                    to_process, singles, gap, fill_sizes)
                placed_off.extend(hole_placed)
                all_hole_secondary.extend(hole_secondary)
                to_process = hole_placed
            all_sheets.append((mat_w, mat_h, placed_off,
                               sec_outer_off + all_hole_secondary, mat_name))
            sheets_used += 1

    if not fill_last and all_sheets:
        mat_w, mat_h, placed, secondary, mat_name = all_sheets[-1]
        all_sheets[-1] = (mat_w, mat_h, placed, [], mat_name)

    return all_sheets, len(singles)


def sheets_to_json(sheets):
    """转为前端预览用的 JSON 结构。"""
    out = []
    for row in sheets:
        mat_w, mat_h, placed, secondary = row[0], row[1], row[2], row[3]
        mat_name = row[4] if len(row) > 4 else ''
        out.append({
            'mat_w': mat_w,
            'mat_h': mat_h,
            'mat_name': mat_name,
            'placed': [
                {
                    'typ': t, 'x': x, 'y': y, 'pw': pw, 'ph': ph,
                    'piw': piw, 'pih': pih, 'customer_code': code,
                }
                for t, x, y, pw, ph, piw, pih, code in placed
            ],
            'secondary': [
                {'x': x, 'y': y, 'pw': pw, 'ph': ph, 'piw': piw, 'pih': pih}
                for x, y, pw, ph, piw, pih in secondary
            ],
        })
    return out
