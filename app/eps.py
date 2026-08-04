"""EPS 输出（切割路径；不写客户代码）。内孔首版居中。"""

CM = 28.34645669  # 1 cm = PT 点


def _rect(L, x1, y1, x2, y2):
    L += [f"{x2:.3f} {y2:.3f} m", f"{x2:.3f} {y1:.3f} l",
          f"{x1:.3f} {y1:.3f} l", f"{x1:.3f} {y2:.3f} l", f"{x2:.3f} {y2:.3f} l"]


def _inner_xy(x, y, pw, ph, piw, pih):
    """内孔左下/右上（cm）。居中；后期可改为 x+iox 等。"""
    return (x + (pw - piw) / 2, y + (ph - pih) / 2,
            x + (pw + piw) / 2, y + (ph + pih) / 2)


def make_eps(placed, path, mat_w, mat_h, secondary=None):
    """
    placed   : [(type, x, y, pw, ph, piw, pih[, customer_code])]  cm
    secondary: [(x, y, pw, ph, piw, pih)]  cm
    """
    def p(v):
        return v * CM

    sw, sh = p(mat_w), p(mat_h)
    sec = secondary or []

    def placed_geom(row):
        # 兼容 7 元组与带 customer_code 的 8 元组
        return row[0], row[1], row[2], row[3], row[4], row[5], row[6]

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
        "[ /Separation (CutOuter) /DeviceRGB",
        "{ dup 1.000000 mul exch dup 0.000000 mul exch 0.000000 mul }",
        "] setcolorspace", "1.0 setcolor", "newpath",
    ]
    for row in placed:
        _, x, y, pw, ph, _, _ = placed_geom(row)
        _rect(lines, p(x), p(y), p(x + pw), p(y + ph))
    for x, y, pw, ph, piw, pih in sec:
        _rect(lines, p(x), p(y), p(x + pw), p(y + ph))
    lines.append("stroke")

    inner_lines = []
    for row in placed:
        _, x, y, pw, ph, piw, pih = placed_geom(row)
        if piw > 0:
            x1, y1, x2, y2 = _inner_xy(x, y, pw, ph, piw, pih)
            _rect(inner_lines, p(x1), p(y1), p(x2), p(y2))
    for x, y, pw, ph, piw, pih in sec:
        if piw > 0:
            x1, y1, x2, y2 = _inner_xy(x, y, pw, ph, piw, pih)
            _rect(inner_lines, p(x1), p(y1), p(x2), p(y2))
    if inner_lines:
        lines += [
            "[ /Separation (CutInner) /DeviceRGB",
            "{ dup 0.000000 mul exch dup 0.000000 mul exch 1.000000 mul }",
            "] setcolorspace", "1.0 setcolor", "newpath",
        ] + inner_lines + ["stroke"]

    with open(path, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines) + '\n')
