"""内孔位置：相对外框左下角的 hole_left / hole_bottom；None 表示居中。"""


def resolve_hole_offset(pw, ph, piw, pih, hole_left=None, hole_bottom=None):
    """返回内孔相对外框左下角的 (hl, hb)。"""
    if piw <= 0 or pih <= 0:
        return 0.0, 0.0
    if hole_left is None or hole_bottom is None:
        return (pw - piw) / 2.0, (ph - pih) / 2.0
    return float(hole_left), float(hole_bottom)


def rotate_hole_90_cw(ow, oh, iw, ih, hl, hb):
    """
    外框 ow×oh、孔 iw×ih 在 (hl,hb) 时，整体顺时针转 90° 后
    新外框为 oh×ow，返回 (niw, nih, nhl, nhb)。
    """
    # (x,y) → (y, ow-x)；孔左下映射后取新包围盒左下
    nhl = hb
    nhb = ow - hl - iw
    return ih, iw, nhl, nhb


def margins_from_hole(ow, oh, iw, ih, hl, hb):
    """由孔位置得到四边边距（画框边宽）。"""
    left = hl
    bottom = hb
    right = ow - hl - iw
    top = oh - hb - ih
    return left, right, top, bottom
