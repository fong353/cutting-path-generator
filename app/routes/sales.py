from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from urllib.parse import urlencode

from app import db
from app.config import SHEET_H, SHEET_W
from app.validate import parse_item_row

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / 'templates'))
router = APIRouter(prefix='/sales')


def _form_ctx(**extra):
    ctx = {
        'today': db.today_str(),
        'error': None,
        'catalog': db.list_materials(),
        'submitter': '',
        'sheet_w': SHEET_W,
        'sheet_h': SHEET_H,
    }
    ctx.update(extra)
    return ctx


def _parse_multi_customer_form(form):
    """
    解析一次提交的多客户表单。
    c_code / c_name / c_note：按客户块顺序
    m_block / m_mat / m_msec：材料段（属于某客户块，各自一种材料）
    i_msec / ow / oh / iw / ih / qty：件行，挂到材料段
    返回 (work_date, submitter, blocks)
    blocks: [{customer_code, customer_name, note, material_ids, items}, ...]
    每种材料一段 → 一条 demand（material_ids 仅一个）。
    """
    work_date = (form.get('work_date') or '').strip()
    submitter = (form.get('submitter') or '').strip()
    if not work_date:
        raise ValueError('请填写业务日期')
    if not submitter:
        raise ValueError('请填写提交人')

    codes = form.getlist('c_code')
    names = form.getlist('c_name')
    notes = form.getlist('c_note')
    if not codes:
        raise ValueError('请至少添加一个客户')

    m_blocks = form.getlist('m_block')
    m_mats = form.getlist('m_mat')
    m_msecs = form.getlist('m_msec')
    if len(m_blocks) != len(m_mats) or len(m_blocks) != len(m_msecs):
        raise ValueError('材料段数据不完整')

    sections = []  # [{msec, bi, mid}]
    msec_index = {}
    for i in range(len(m_msecs)):
        try:
            bi = int(m_blocks[i])
            mid = int(m_mats[i])
            msec = int(m_msecs[i])
        except (TypeError, ValueError):
            raise ValueError('材料选择无效') from None
        if bi < 0 or bi >= len(codes):
            raise ValueError('材料段客户块无效')
        if msec in msec_index:
            raise ValueError('材料段编号重复')
        sec = {'msec': msec, 'bi': bi, 'mid': mid}
        msec_index[msec] = sec
        sections.append(sec)

    items_by_msec = {s['msec']: [] for s in sections}
    i_msecs = form.getlist('i_msec')
    ow_list = form.getlist('ow')
    oh_list = form.getlist('oh')
    iw_list = form.getlist('iw')
    ih_list = form.getlist('ih')
    qty_list = form.getlist('qty')
    hl_list = form.getlist('hole_left')
    hb_list = form.getlist('hole_bottom')

    for i in range(len(ow_list)):
        row = {
            'ow': ow_list[i],
            'oh': oh_list[i] if i < len(oh_list) else '',
            'iw': iw_list[i] if i < len(iw_list) else '',
            'ih': ih_list[i] if i < len(ih_list) else '',
            'qty': qty_list[i] if i < len(qty_list) else '',
            'hole_left': hl_list[i] if i < len(hl_list) else '',
            'hole_bottom': hb_list[i] if i < len(hb_list) else '',
        }
        if not any(str(row[k]).strip() for k in ('ow', 'oh', 'iw', 'ih', 'qty')):
            continue
        try:
            msec = int(i_msecs[i]) if i < len(i_msecs) else -1
        except ValueError:
            raise ValueError(f'件第 {i + 1} 行：材料段无效') from None
        if msec not in items_by_msec:
            raise ValueError(f'件第 {i + 1} 行：材料段无效')
        bi = msec_index[msec]['bi']
        code = (codes[bi] if bi < len(codes) else '').strip() or '临时'
        _typ, ow, oh, iw, ih, qty, _c, hl, hb = parse_item_row(row, code, i)
        items_by_msec[msec].append((ow, oh, iw, ih, qty, hl, hb))

    blocks = []
    for bi, code in enumerate(codes):
        code = (code or '').strip()
        name = ((names[bi] if bi < len(names) else '') or '').strip()
        note = ((notes[bi] if bi < len(notes) else '') or '').strip()
        cust_secs = [s for s in sections if s['bi'] == bi]
        has_items = any(items_by_msec[s['msec']] for s in cust_secs)
        if not code and not cust_secs and not has_items:
            continue
        if not code:
            raise ValueError(f'客户块 {bi + 1}：请填写客户代码')
        if not cust_secs:
            raise ValueError(f'客户「{code}」：请至少添加一种材料')
        for s in cust_secs:
            items = items_by_msec[s['msec']]
            if not items:
                raise ValueError(f'客户「{code}」：每种材料请至少填写一件')
            blocks.append({
                'customer_code': code,
                'customer_name': name,
                'note': note,
                'material_ids': [s['mid']],
                'items': items,
            })
    if not blocks:
        raise ValueError('请至少填写一个客户的需求')
    return work_date, submitter, blocks


@router.get('', response_class=HTMLResponse)
def sales_form(request: Request):
    return templates.TemplateResponse('sales_form.html', {
        'request': request,
        **_form_ctx(),
    })


@router.post('/submit', response_class=HTMLResponse)
async def sales_submit(request: Request):
    form = await request.form()
    error = None
    created_ids = []
    work_date = (form.get('work_date') or '').strip()
    submitter = (form.get('submitter') or '').strip()
    try:
        work_date, submitter, blocks = _parse_multi_customer_form(form)
        for b in blocks:
            did = db.create_demand(
                work_date, b['customer_code'], b['items'],
                b['note'], submitter, b['material_ids'],
                customer_name=b.get('customer_name') or '',
            )
            created_ids.append(did)
    except ValueError as e:
        error = str(e)

    if error:
        return templates.TemplateResponse('sales_form.html', {
            'request': request,
            **_form_ctx(today=work_date or db.today_str(), error=error, submitter=submitter),
        }, status_code=400)

    qs = urlencode({'ids': ','.join(str(i) for i in created_ids)})
    return RedirectResponse(f'/sales/done?{qs}', status_code=303)


@router.get('/done', response_class=HTMLResponse)
def sales_done(request: Request, ids: str = '', id: int = 0):
    id_list = []
    if ids:
        for p in ids.split(','):
            p = p.strip()
            if p.isdigit():
                id_list.append(int(p))
    elif id:
        id_list = [id]
    demands = db.get_demands_by_ids(id_list)
    return templates.TemplateResponse('sales_done.html', {
        'request': request,
        'demands': demands,
    })


@router.get('/demands', response_class=HTMLResponse)
def sales_list(request: Request, date: str = '', customer: str = ''):
    work_date = date or db.today_str()
    customer_q = (customer or '').strip()
    demands = db.list_demands(
        work_date=work_date,
        customer_q=customer_q or None,
    )
    return templates.TemplateResponse('sales_list.html', {
        'request': request,
        'work_date': work_date,
        'customer': customer_q,
        'demands': demands,
    })


@router.get('/demands/{demand_id}', response_class=HTMLResponse)
def sales_detail(request: Request, demand_id: int):
    rows = db.get_demands_by_ids([demand_id])
    if not rows:
        return templates.TemplateResponse('sales_edit.html', {
            'request': request,
            'demand': None,
            'catalog': db.list_materials(),
            'error': '需求不存在',
            'readonly': True,
            'sheet_w': SHEET_W,
            'sheet_h': SHEET_H,
        }, status_code=404)
    demand = rows[0]
    return templates.TemplateResponse('sales_edit.html', {
        'request': request,
        'demand': demand,
        'catalog': db.list_materials(),
        'error': None,
        'readonly': demand['status'] != 'pending',
        'selected_ids': [m['id'] for m in demand.get('materials') or []],
        'sheet_w': SHEET_W,
        'sheet_h': SHEET_H,
    })


@router.post('/demands/{demand_id}', response_class=HTMLResponse)
async def sales_update(request: Request, demand_id: int):
    form = await request.form()
    rows = db.get_demands_by_ids([demand_id])
    if not rows:
        return templates.TemplateResponse('sales_edit.html', {
            'request': request,
            'demand': None,
            'catalog': db.list_materials(),
            'error': '需求不存在',
            'readonly': True,
            'sheet_w': SHEET_W,
            'sheet_h': SHEET_H,
        }, status_code=404)
    demand = rows[0]
    catalog = db.list_materials()

    work_date = (form.get('work_date') or '').strip()
    customer_code = (form.get('customer_code') or '').strip()
    customer_name = (form.get('customer_name') or '').strip()
    note = (form.get('note') or '').strip()
    submitter = (form.get('submitter') or '').strip()
    mat_raw = form.get('material_id')
    error = None
    try:
        if demand['status'] != 'pending':
            raise ValueError('已拼板完成的需求不能修改')
        if not work_date:
            raise ValueError('请填写业务日期')
        if not submitter:
            raise ValueError('请填写提交人')
        if not customer_code:
            raise ValueError('请填写客户代码')
        try:
            selected_ids = [int(mat_raw)] if str(mat_raw or '').strip() else []
        except ValueError:
            raise ValueError('材料选择无效') from None
        if not selected_ids:
            raise ValueError('请指定一种材料')
        items = []
        ow_list = form.getlist('ow')
        oh_list = form.getlist('oh')
        iw_list = form.getlist('iw')
        ih_list = form.getlist('ih')
        qty_list = form.getlist('qty')
        hl_list = form.getlist('hole_left')
        hb_list = form.getlist('hole_bottom')
        for i in range(len(ow_list)):
            row = {
                'ow': ow_list[i],
                'oh': oh_list[i] if i < len(oh_list) else '',
                'iw': iw_list[i] if i < len(iw_list) else '',
                'ih': ih_list[i] if i < len(ih_list) else '',
                'qty': qty_list[i] if i < len(qty_list) else '',
                'hole_left': hl_list[i] if i < len(hl_list) else '',
                'hole_bottom': hb_list[i] if i < len(hb_list) else '',
            }
            if not any(str(row[k]).strip() for k in ('ow', 'oh', 'iw', 'ih', 'qty')):
                continue
            _t, ow, oh, iw, ih, qty, _c, hl, hb = parse_item_row(row, customer_code, i)
            items.append((ow, oh, iw, ih, qty, hl, hb))
        if not items:
            raise ValueError('请至少填写一件')
        db.update_demand(
            demand_id, work_date, customer_code, items, note, submitter, selected_ids,
            customer_name=customer_name,
        )
        return RedirectResponse(f'/sales/demands/{demand_id}?saved=1', status_code=303)
    except ValueError as e:
        error = str(e)

    # 回显失败时的表单：重新读库 + 覆盖错误信息
    demand = dict(db.get_demands_by_ids([demand_id])[0])
    demand['customer_code'] = customer_code
    demand['customer_name'] = customer_name
    demand['note'] = note
    demand['submitter'] = submitter
    demand['work_date'] = work_date or demand.get('work_date')
    echo_ids = []
    if str(mat_raw or '').strip().isdigit():
        echo_ids = [int(mat_raw)]
    if not echo_ids:
        echo_ids = [m['id'] for m in demand.get('materials') or []]
    return templates.TemplateResponse('sales_edit.html', {
        'request': request,
        'demand': demand,
        'catalog': catalog,
        'error': error,
        'readonly': False,
        'selected_ids': echo_ids,
        'sheet_w': SHEET_W,
        'sheet_h': SHEET_H,
    }, status_code=400)


@router.post('/demands/{demand_id}/delete', response_class=HTMLResponse)
async def sales_delete(request: Request, demand_id: int):
    form = await request.form()
    work_date = (form.get('date') or '').strip() or db.today_str()
    customer_q = (form.get('customer') or '').strip()
    try:
        db.delete_demand(demand_id, allow_done=True)
    except ValueError as e:
        rows = db.get_demands_by_ids([demand_id])
        demand = rows[0] if rows else None
        return templates.TemplateResponse('sales_edit.html', {
            'request': request,
            'demand': demand,
            'catalog': db.list_materials(),
            'error': str(e),
            'readonly': not demand or demand['status'] != 'pending',
            'selected_ids': [m['id'] for m in (demand or {}).get('materials') or []],
            'sheet_w': SHEET_W,
            'sheet_h': SHEET_H,
        }, status_code=400)
    q = {'date': work_date, 'deleted': demand_id}
    if customer_q:
        q['customer'] = customer_q
    return RedirectResponse(
        f'/sales/demands?{urlencode(q)}',
        status_code=303,
    )
