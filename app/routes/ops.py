"""操作员：待拼池、混拼、预览、生成。"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from typing import Any, List, Optional

from app import db
from app.config import EPS_DIR, OPS_PIN, ensure_dirs
from app.eps import make_eps
from app.ops_settings import load_ops_defaults, save_ops_defaults
from app.pack_core import pack, sheets_to_json
from app.validate import parse_fill_sizes, parse_gap, parse_materials

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / 'templates'))
router = APIRouter(prefix='/ops')


def _safe_filename(name: str) -> str:
    """文件名安全片段：去掉路径分隔与非法字符。"""
    bad = '\\/:*?"<>|\n\r\t'
    out = ''.join('_' if c in bad else c for c in (name or '').strip())
    out = out.strip(' .') or '材料'
    return out[:40]


def _check_pin(x_ops_pin: Optional[str] = Header(default=None), pin: Optional[str] = None):
    if not OPS_PIN:
        return
    got = (x_ops_pin or pin or '').strip()
    if got != OPS_PIN:
        raise HTTPException(401, '需要操作员口令')


class MaterialRow(BaseModel):
    material_id: Optional[int] = None
    name: str = ''
    width: Any
    height: Any
    sheets: Any = ''


class FillRow(BaseModel):
    fw: Any
    fh: Any
    fiw: Any = ''
    fih: Any = ''
    enabled: bool = True


class BoardBody(BaseModel):
    demand_ids: List[int] = Field(min_length=1)
    materials: List[MaterialRow]
    fill: List[FillRow] = []
    gap: Any = 1
    fill_last: bool = True
    prefix: str = '卡纸路径'
    save_defaults: bool = True


def _items_from_demands(demands):
    items = []
    for d in demands:
        code = d['customer_code']
        for it in d.get('item_rows', []):
            typ = 'frame' if float(it['iw'] or 0) > 0 else 'solid'
            hl = it.get('hole_left')
            hb = it.get('hole_bottom')
            items.append((
                typ,
                float(it['ow']), float(it['oh']),
                float(it['iw'] or 0), float(it['ih'] or 0),
                int(it['qty']),
                code,
                hl, hb,
            ))
    return items


def _run_pack(body: BoardBody):
    demands = db.get_demands_by_ids(body.demand_ids)
    if len(demands) != len(set(body.demand_ids)):
        raise ValueError('部分需求不存在')
    missing = [d['id'] for d in demands if d['status'] != 'pending']
    # 允许对已 done 再预览，但生成时再检查
    items = _items_from_demands(demands)
    if not items:
        raise ValueError('所选需求没有件')
    gap = parse_gap(body.gap)
    materials = parse_materials([m.model_dump() for m in body.materials])
    fill_sizes = parse_fill_sizes([f.model_dump() for f in body.fill]) or None
    sheets, n_remaining = pack(items, materials, gap, fill_sizes, body.fill_last)
    return demands, sheets, n_remaining


@router.get('', response_class=HTMLResponse)
def ops_list(request: Request, date: str = '', pin: str = ''):
    if OPS_PIN and pin != OPS_PIN:
        return templates.TemplateResponse('ops_pin.html', {
            'request': request,
            'error': bool(pin),
        })
    work_date = date or db.today_str()
    demands = db.list_demands(work_date=work_date, status='pending')
    return templates.TemplateResponse('ops_list.html', {
        'request': request,
        'work_date': work_date,
        'demands': demands,
        'pin': pin if OPS_PIN else '',
        'need_pin': bool(OPS_PIN),
    })


@router.get('/board', response_class=HTMLResponse)
def ops_board(request: Request, ids: str = '', pin: str = ''):
    if OPS_PIN and pin != OPS_PIN:
        return templates.TemplateResponse('ops_pin.html', {
            'request': request,
            'error': bool(pin),
        })
    try:
        demand_ids = [int(x) for x in ids.split(',') if x.strip()]
    except ValueError:
        demand_ids = []
    demands = db.get_demands_by_ids(demand_ids)
    materials = db.list_materials()
    defaults = load_ops_defaults()
    # 从业务员指定材料汇总预填种类行（宽高仍空，由操作员手填）
    seen = {}
    for d in demands:
        for m in d.get('materials') or []:
            seen[m['id']] = m['name']
    suggested_mats = [
        {'material_id': mid, 'name': name, 'width': '', 'height': '', 'sheets': ''}
        for mid, name in seen.items()
    ]
    return templates.TemplateResponse('ops_board.html', {
        'request': request,
        'demands': demands,
        'demand_ids': [d['id'] for d in demands],
        'catalog': materials,
        'defaults': defaults,
        'suggested_mats': suggested_mats,
        'pin': pin if OPS_PIN else '',
    })


@router.post('/board/preview')
def ops_preview(body: BoardBody, _: None = Depends(_check_pin)):
    try:
        demands, sheets, n_remaining = _run_pack(body)
        if body.save_defaults:
            save_ops_defaults({
                'gap': str(body.gap),
                'fill_last': body.fill_last,
                'prefix': body.prefix,
                'materials': [m.model_dump() for m in body.materials],
                'fill': [f.model_dump() for f in body.fill],
            })
        return {
            'ok': True,
            'sheets': sheets_to_json(sheets),
            'n_remaining': n_remaining,
            'customers': sorted({d['customer_code'] for d in demands}),
        }
    except ValueError as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)


@router.post('/board/generate')
def ops_generate(body: BoardBody, _: None = Depends(_check_pin)):
    try:
        demands, sheets, n_remaining = _run_pack(body)
        pending = [d for d in demands if d['status'] == 'pending']
        if not pending:
            raise ValueError('所选需求均已完成，无法再次生成')
        if not sheets:
            raise ValueError('没有生成任何板材，请检查材料尺寸')

        ensure_dirs()
        day = datetime.now().strftime('%Y%m%d')
        out_dir = EPS_DIR / day
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = (body.prefix or '卡纸路径').strip() or '卡纸路径'
        paths = []
        for i, sheet in enumerate(sheets, 1):
            mat_w, mat_h, placed, secondary = sheet[0], sheet[1], sheet[2], sheet[3]
            mat_name = sheet[4] if len(sheet) > 4 else f'{mat_w:g}x{mat_h:g}'
            uid = uuid.uuid4().hex[:8]
            safe_mat = _safe_filename(mat_name)
            # 自定义前缀 + 板材编号 + 材料名
            fname = f'{prefix}-板{i}-{safe_mat}-{uid}.eps'
            fpath = out_dir / fname
            make_eps(placed, str(fpath), mat_w, mat_h, secondary)
            paths.append(str(fpath))

        ids = [d['id'] for d in pending]
        db.mark_demands_done(ids)
        db.save_job_run(
            ids,
            [m.model_dump() for m in body.materials],
            paths,
        )
        if body.save_defaults:
            save_ops_defaults({
                'gap': str(body.gap),
                'fill_last': body.fill_last,
                'prefix': body.prefix,
                'materials': [m.model_dump() for m in body.materials],
                'fill': [f.model_dump() for f in body.fill],
            })
        return {
            'ok': True,
            'sheets': sheets_to_json(sheets),
            'n_remaining': n_remaining,
            'eps_paths': paths,
            'customers': sorted({d['customer_code'] for d in demands}),
        }
    except ValueError as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)
