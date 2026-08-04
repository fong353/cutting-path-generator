"""输入校验（无 GUI）。出错抛 ValueError，消息给人看。"""


def parse_gap(raw):
    try:
        gap = float(raw)
        if gap < 0:
            raise ValueError
        return gap
    except (TypeError, ValueError):
        raise ValueError('间距必须 ≥ 0') from None


def parse_materials(rows):
    """
    rows: [{'width':..,'height':..,'sheets':..,'name':..} | [w,h,sheets], ...]
    sheets 空/None = 不限
    返回 [(mw, mh, ms, name), ...]
    """
    materials = []
    for r, row in enumerate(rows or []):
        try:
            if isinstance(row, dict):
                mw = float(row['width'])
                mh = float(row['height'])
                ms_raw = row.get('sheets', None)
                name = str(row.get('name') or '').strip()
            else:
                mw = float(row[0])
                mh = float(row[1])
                ms_raw = row[2] if len(row) > 2 else None
                name = str(row[3]).strip() if len(row) > 3 and row[3] else ''
            if mw <= 0 or mh <= 0:
                raise ValueError()
            if ms_raw is None or ms_raw == '':
                ms = None
            else:
                ms = int(float(ms_raw))
                if ms <= 0:
                    raise ValueError()
        except (ValueError, TypeError, KeyError, IndexError):
            raise ValueError(f'材料第 {r + 1} 行：宽/高必须大于 0，张数为正整数或留空') from None
        if not name:
            name = f'{mw:g}x{mh:g}'
        materials.append((mw, mh, ms, name))
    if not materials:
        raise ValueError('请至少填写一种材料')
    return materials


def parse_item_row(vals, customer_code, row_index=0):
    """
    vals: dict 或 [ow,oh,iw,ih,qty]
    返回 (typ, ow, oh, iw, ih, qty, customer_code, hole_left, hole_bottom)
    hole_left/bottom 为 None 表示居中；仅带孔件有效。
    """
    r = row_index + 1
    code = (customer_code or '').strip()
    if not code:
        raise ValueError(f'件第 {r} 行：缺少客户代码')
    try:
        if isinstance(vals, dict):
            ow = float(vals['ow'])
            oh = float(vals['oh'])
            qty = int(float(vals.get('qty') or 0))
            iw_s = vals.get('iw', '')
            ih_s = vals.get('ih', '')
            iw_s = '' if iw_s is None else str(iw_s).strip()
            ih_s = '' if ih_s is None else str(ih_s).strip()
            hl_s = vals.get('hole_left', '')
            hb_s = vals.get('hole_bottom', '')
            hl_s = '' if hl_s is None else str(hl_s).strip()
            hb_s = '' if hb_s is None else str(hb_s).strip()
        else:
            ow = float(vals[0])
            oh = float(vals[1])
            qty = int(float(vals[4])) if len(vals) > 4 and vals[4] != '' else 0
            iw_s = str(vals[2]).strip() if len(vals) > 2 and vals[2] is not None else ''
            ih_s = str(vals[3]).strip() if len(vals) > 3 and vals[3] is not None else ''
            hl_s = str(vals[5]).strip() if len(vals) > 5 and vals[5] is not None else ''
            hb_s = str(vals[6]).strip() if len(vals) > 6 and vals[6] is not None else ''
        if ow <= 0 or oh <= 0 or qty <= 0:
            raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError):
        raise ValueError(f'件第 {r} 行：外框宽/高 和 数量 必须大于 0') from None

    has_w, has_h = iw_s != '', ih_s != ''
    if has_w != has_h:
        raise ValueError(f'件第 {r} 行：内孔宽和高要么都填，要么都空')
    hole_left = hole_bottom = None
    if has_w:
        try:
            iw, ih = float(iw_s), float(ih_s)
            if iw <= 0 or ih <= 0 or iw >= ow or ih >= oh:
                raise ValueError()
        except ValueError:
            raise ValueError(f'件第 {r} 行：内孔必须 > 0 且小于外框') from None
        typ = 'frame'
        if hl_s != '' or hb_s != '':
            if hl_s == '' or hb_s == '':
                raise ValueError(f'件第 {r} 行：中孔左边距与下边距需同时填写（或都留空=居中）')
            try:
                hole_left, hole_bottom = float(hl_s), float(hb_s)
            except ValueError:
                raise ValueError(f'件第 {r} 行：中孔边距必须是数字') from None
            if hole_left < 0 or hole_bottom < 0:
                raise ValueError(f'件第 {r} 行：中孔边距不能为负')
            if hole_left + iw > ow + 1e-9 or hole_bottom + ih > oh + 1e-9:
                raise ValueError(f'件第 {r} 行：中孔超出外框（检查左边距/下边距）')
            # 右边距、上边距自动 >= 0
            if ow - hole_left - iw < -1e-9 or oh - hole_bottom - ih < -1e-9:
                raise ValueError(f'件第 {r} 行：中孔超出外框')
    else:
        iw = ih = 0.0
        typ = 'solid'
    return (typ, ow, oh, iw, ih, qty, code, hole_left, hole_bottom)


def parse_fill_sizes(rows):
    """
    rows: dict 或 list；dict 可含 enabled=False 跳过。
    返回 [(fw,fh,fiw,fih), ...]
    """
    sizes = []
    for vals in rows or []:
        try:
            if isinstance(vals, dict):
                if vals.get('enabled') is False or vals.get('enabled') == 0:
                    continue
                fw, fh = float(vals['fw']), float(vals['fh'])
                fiw_s = vals.get('fiw', '')
                fih_s = vals.get('fih', '')
                fiw_s = '' if fiw_s is None else str(fiw_s).strip()
                fih_s = '' if fih_s is None else str(fih_s).strip()
            else:
                if vals and str(vals[-1]) == '0' and len(vals) >= 5:
                    continue
                fw, fh = float(vals[0]), float(vals[1])
                fiw_s = str(vals[2]).strip() if len(vals) > 2 and vals[2] else ''
                fih_s = str(vals[3]).strip() if len(vals) > 3 and vals[3] else ''
            if fw <= 0 or fh <= 0:
                continue
            has_w, has_h = fiw_s != '', fih_s != ''
            if has_w != has_h:
                continue
            if has_w:
                fiw, fih = float(fiw_s), float(fih_s)
                if fiw <= 0 or fih <= 0 or fiw >= fw or fih >= fh:
                    continue
            else:
                fiw = fih = 0.0
            sizes.append((fw, fh, fiw, fih))
        except (ValueError, TypeError, KeyError, IndexError):
            continue
    return sizes
