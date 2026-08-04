"""排版核心：矩形拼板 + 内孔嵌套 + 尾料填充。件与 placed 携带 customer_code 与孔偏移。"""

from rectpack import newPacker, PackingMode, MaxRectsBssf

from app.hole_geom import resolve_hole_offset, rotate_hole_90_cw


def _norm_item(row):
    """统一为 (typ, ow, oh, iw, ih, qty, code, hl, hb)。"""
    typ, ow, oh, iw, ih, qty, code = row[:7]
    hl = row[7] if len(row) > 7 else None
    hb = row[8] if len(row) > 8 else None
    return typ, ow, oh, iw, ih, qty, code, hl, hb


def _make_fill_groups(fill_sizes):
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


def _place_dims(ow, oh, iw, ih, hl, hb, placed_r, gap):
    """根据 rectpack 是否旋转，返回 pw,ph,piw,pih,hl,hb。"""
    if abs(placed_r.width - (ow + gap)) < 1e-6:
        rhl, rhb = resolve_hole_offset(ow, oh, iw, ih, hl, hb)
        return ow, oh, iw, ih, rhl, rhb
    # 旋转 90° CW
    rhl0, rhb0 = resolve_hole_offset(ow, oh, iw, ih, hl, hb)
    if iw > 0 and ih > 0:
        niw, nih, nhl, nhb = rotate_hole_90_cw(ow, oh, iw, ih, rhl0, rhb0)
    else:
        niw, nih, nhl, nhb = ih, iw, 0.0, 0.0
    return oh, ow, niw, nih, nhl, nhb


def _pack_one_sheet(singles, usable_w, usable_h, gap, fill_sizes=None):
    """
    singles: [(typ, ow, oh, iw, ih, code, hl, hb)]
    placed:  [(typ, x, y, pw, ph, piw, pih, code, hl, hb)]
    """
    if not singles:
        return [], [], []

    packer = newPacker(mode=PackingMode.Offline, pack_algo=MaxRectsBssf, rotation=True)
    packer.add_bin(usable_w + gap, usable_h + gap)
    for i, (typ, ow, oh, iw, ih, _code, _hl, _hb) in enumerate(singles):
        packer.add_rect(ow + gap, oh + gap, rid=i)
    packer.pack()

    placed, placed_idx = [], set()
    secondary_outer = []

    for b in packer:
        for r in b:
            i = r.rid
            typ, ow, oh, iw, ih, code, hl, hb = singles[i]
            placed_idx.add(i)
            pw, ph, piw, pih, rhl, rhb = _place_dims(ow, oh, iw, ih, hl, hb, r, gap)
            placed.append((typ, float(r.x), float(r.y), pw, ph, piw, pih, code, rhl, rhb))

        if fill_sizes:
            secondary_outer.extend(_apply_fill(b, fill_sizes, gap))

    remaining = [singles[j] for j in range(len(singles)) if j not in placed_idx]
    return placed, remaining, secondary_outer


def _process_holes(placed_sheet, remaining, gap, fill_sizes):
    """
    placed_sheet: [(typ,x,y,pw,ph,piw,pih,code,hl,hb)]
    remaining:    [(typ,ow,oh,iw,ih,code,hl,hb)]
    """
    hole_placed = []
    hole_secondary = []
    still_remaining = list(remaining)

    for typ, x, y, pw, ph, piw, pih, _code, hl, hb in placed_sheet:
        if typ != 'frame' or piw <= 0:
            continue
        rhl, rhb = resolve_hole_offset(pw, ph, piw, pih, hl, hb)
        hx = x + rhl
        hy = y + rhb
        avail_w = piw - 2 * gap
        avail_h = pih - 2 * gap
        if avail_w <= 0 or avail_h <= 0:
            continue

        hole_bin = MaxRectsBssf(avail_w + gap, avail_h + gap, rot=True)

        still_remaining.sort(key=lambda t: -(t[1] * t[2]))
        placed_set = set()
        for i, (rtyp, ow, oh, iw, ih, rcode, rhl0, rhb0) in enumerate(still_remaining):
            placed_r = hole_bin.add_rect(ow + gap, oh + gap)
            if placed_r is None and ow != oh:
                placed_r = hole_bin.add_rect(oh + gap, ow + gap)
            if placed_r is None:
                continue
            placed_set.add(i)
            rpw, rph, rpiw, rpih, nhl, nhb = _place_dims(
                ow, oh, iw, ih, rhl0, rhb0, placed_r, gap)
            hole_placed.append((rtyp,
                                hx + gap + float(placed_r.x),
                                hy + gap + float(placed_r.y),
                                rpw, rph, rpiw, rpih, rcode, nhl, nhb))
        still_remaining = [t for i, t in enumerate(still_remaining) if i not in placed_set]

        if fill_sizes:
            for rx, ry, rw, rh, riw, rih in _apply_fill(hole_bin, fill_sizes, gap):
                hole_secondary.append((hx + gap + rx, hy + gap + ry,
                                       rw, rh, riw, rih))

    return hole_placed, hole_secondary, still_remaining


def pack(items, materials, gap, fill_sizes=None, fill_last=True):
    """
    items: [(type, ow, oh, iw, ih, qty, customer_code)] 或再加 (hl, hb)
    materials: [(mat_w, mat_h, max_sheets)] 或带 name
    sheets: [(mat_w, mat_h, placed, secondary, mat_name)]
    placed: [(typ, x, y, pw, ph, piw, pih, customer_code, hl, hb)]
    """
    singles = []
    for row in items:
        typ, ow, oh, iw, ih, qty, code, hl, hb = _norm_item(row)
        singles += [(typ, ow, oh, iw, ih, code, hl, hb)] * int(qty)
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
            placed_off = [(t, x + gap, y + gap, pw, ph, piw, pih, code, hl, hb)
                          for t, x, y, pw, ph, piw, pih, code, hl, hb in placed]
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
    out = []
    for row in sheets:
        mat_w, mat_h, placed, secondary = row[0], row[1], row[2], row[3]
        mat_name = row[4] if len(row) > 4 else ''
        placed_json = []
        for p in placed:
            t, x, y, pw, ph, piw, pih, code = p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]
            hl = p[8] if len(p) > 8 else None
            hb = p[9] if len(p) > 9 else None
            rhl, rhb = resolve_hole_offset(pw, ph, piw, pih, hl, hb)
            placed_json.append({
                'typ': t, 'x': x, 'y': y, 'pw': pw, 'ph': ph,
                'piw': piw, 'pih': pih, 'customer_code': code,
                'hole_left': rhl, 'hole_bottom': rhb,
            })
        out.append({
            'mat_w': mat_w,
            'mat_h': mat_h,
            'mat_name': mat_name,
            'placed': placed_json,
            'secondary': [
                {'x': x, 'y': y, 'pw': pw, 'ph': ph, 'piw': piw, 'pih': pih}
                for x, y, pw, ph, piw, pih in secondary
            ],
        })
    return out
