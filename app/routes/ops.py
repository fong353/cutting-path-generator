"""操作员：待拼池、混拼、预览、生成。"""

import io
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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

_DAY_RE = re.compile(r'^\d{8}$')
_EPS_NAME_RE = re.compile(r'^[^\\/]+\.eps$', re.IGNORECASE)


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


def _resolve_eps(day: str, filename: str) -> Path:
    if not _DAY_RE.match(day or '') or not _EPS_NAME_RE.match(filename or ''):
        raise HTTPException(404, '文件不存在')
    root = EPS_DIR.resolve()
    path = (root / day / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(404, '文件不存在')
    if not path.is_file():
        raise HTTPException(404, '文件不存在')
    return path


def _eps_file_info(day: str, filename: str) -> dict:
    return {
        'day': day,
        'name': filename,
        'url': f'/ops/eps/{day}/{quote(filename)}',
    }


def _files_from_paths(paths):
    """绝对路径 → 可下载文件信息（仅仍存在的文件）。"""
    files = []
    root = EPS_DIR.resolve()
    for raw in paths or []:
        try:
            path = Path(raw).resolve()
            path.relative_to(root)
        except (OSError, ValueError):
            continue
        if not path.is_file():
            continue
        day = path.parent.name
        if not _DAY_RE.match(day):
            continue
        files.append(_eps_file_info(day, path.name))
    return files


def _enrich_job_runs(runs):
    """为生成记录补全下载链接与摘要。"""
    out = []
    for run in runs:
        files = _files_from_paths(run.get('eps_paths'))
        customers = []
        materials = []
        seen_c, seen_m = set(), set()
        for j in run.get('jobs') or []:
            c = j.get('customer_code') or ''
            m = j.get('material_name') or ''
            if c and c not in seen_c:
                seen_c.add(c)
                customers.append(c)
            if m and m not in seen_m:
                seen_m.add(m)
                materials.append(m)
        zip_url = ''
        if files:
            zip_url = '/ops/eps-zip?files=' + quote(
                ','.join(f'{f["day"]}/{f["name"]}' for f in files)
            )
        item = dict(run)
        item['eps_files'] = files
        item['customers'] = customers
        item['material_names'] = materials
        item['zip_url'] = zip_url
        out.append(item)
    return out


def _attach_downloads_to_jobs(jobs, runs):
    """给完成任务挂上最近一次生成中的下载文件与同批任务 keys（供拼版检查）。"""
    latest = {}
    for run in runs:
        files = run.get('eps_files') or []
        keys = list(run.get('keys') or [])
        if not files and not keys:
            continue
        info = {
            'eps_files': files,
            'zip_url': run.get('zip_url') or '',
            'run_id': run.get('id'),
            'created_at': run.get('created_at'),
            'keys': keys,
            'materials_snapshot': run.get('materials_snapshot') or [],
        }
        for key in keys:
            if key not in latest:
                latest[key] = info
    for j in jobs:
        j['downloads'] = latest.get(j.get('key'))
    return jobs


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
    jobs: List[str] = Field(min_length=1)  # "demandId-materialId"
    materials: List[MaterialRow]
    fill: List[FillRow] = []
    gap: Any = 1
    fill_last: bool = True
    prefix: str = '卡纸路径'
    save_defaults: bool = True
    # 仍有件排不下时，需前端二次确认后为 True 才允许生成并标完成
    confirm_incomplete: bool = False


def _require_same_material(jobs):
    """混拼任务必须同一材料。"""
    if not jobs:
        raise ValueError('未选择有效任务')
    mids = {j['material_id'] for j in jobs}
    if len(mids) > 1:
        names = '、'.join(sorted({j['material_name'] for j in jobs}))
        raise ValueError(f'只能相同材料一起混拼，当前混选了：{names}')


def _items_from_jobs(jobs):
    """每个「客户×材料」任务贡献一套件（同需求多材料会重复件，符合分材料下单）。"""
    items = []
    for j in jobs:
        code = j['customer_code']
        for it in j.get('item_rows', []):
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
    jobs = db.get_jobs_by_keys(body.jobs)
    found = {j['key'] for j in jobs}
    if any(k not in found for k in body.jobs):
        raise ValueError('部分待拼任务不存在')
    _require_same_material(jobs)
    items = _items_from_jobs(jobs)
    if not items:
        raise ValueError('所选任务没有件')
    gap = parse_gap(body.gap)
    materials = parse_materials([m.model_dump() for m in body.materials])
    fill_sizes = parse_fill_sizes([f.model_dump() for f in body.fill]) or None
    sheets, n_remaining = pack(items, materials, gap, fill_sizes, body.fill_last)
    return jobs, sheets, n_remaining


def _group_jobs_by_material(jobs):
    """按材料归组，保持材料首次出现顺序。"""
    groups = []
    index = {}
    for j in jobs or []:
        mid = j.get('material_id')
        if mid not in index:
            index[mid] = len(groups)
            groups.append({
                'material_id': mid,
                'material_name': j.get('material_name') or '材料',
                'jobs': [],
                'job_keys': [],
            })
        g = groups[index[mid]]
        g['jobs'].append(j)
        g['job_keys'].append(j['key'])
    return groups


@router.get('', response_class=HTMLResponse)
def ops_list(request: Request, date: str = '', pin: str = ''):
    if OPS_PIN and pin != OPS_PIN:
        return templates.TemplateResponse('ops_pin.html', {
            'request': request,
            'error': bool(pin),
        })
    work_date = date or db.today_str()
    pending_jobs = db.list_jobs(work_date=work_date, status='pending')
    done_jobs = db.list_jobs(work_date=work_date, status='done')
    runs = _enrich_job_runs(db.list_job_runs(work_date=work_date))
    _attach_downloads_to_jobs(done_jobs, runs)
    return templates.TemplateResponse('ops_list.html', {
        'request': request,
        'work_date': work_date,
        'pending_jobs': pending_jobs,
        'pending_groups': _group_jobs_by_material(pending_jobs),
        'done_jobs': done_jobs,
        'pin': pin if OPS_PIN else '',
        'need_pin': bool(OPS_PIN),
    })


@router.get('/board', response_class=HTMLResponse)
def ops_board(request: Request, jobs: str = '', pin: str = '', mode: str = ''):
    if OPS_PIN and pin != OPS_PIN:
        return templates.TemplateResponse('ops_pin.html', {
            'request': request,
            'error': bool(pin),
        })
    review = (mode or '').strip().lower() in ('check', 'review', '1')
    keys = [x.strip() for x in jobs.split(',') if x.strip()]
    selected = db.get_jobs_by_keys(keys)
    try:
        _require_same_material(selected)
    except ValueError as e:
        wd = db.today_str()
        runs = _enrich_job_runs(db.list_job_runs(work_date=wd))
        done = db.list_jobs(work_date=wd, status='done')
        _attach_downloads_to_jobs(done, runs)
        pending = db.list_jobs(work_date=wd, status='pending')
        return templates.TemplateResponse('ops_list.html', {
            'request': request,
            'work_date': wd,
            'pending_jobs': pending,
            'pending_groups': _group_jobs_by_material(pending),
            'done_jobs': done,
            'pin': pin if OPS_PIN else '',
            'need_pin': bool(OPS_PIN),
            'error': str(e),
        }, status_code=400)
    materials = db.list_materials()
    defaults = load_ops_defaults()
    # 拼版检查：尽量用该次生成时保存的板材宽高；否则按材料种类预填空宽高
    suggested_mats = None
    if review:
        runs = _enrich_job_runs(db.list_job_runs(work_date=None, limit=120))
        keyset = set(keys)
        for run in runs:
            rkeys = set(run.get('keys') or [])
            if keyset & rkeys:
                snap = run.get('materials_snapshot') or []
                if snap:
                    suggested_mats = []
                    for m in snap:
                        suggested_mats.append({
                            'material_id': m.get('material_id'),
                            'name': m.get('name') or '',
                            'width': m.get('width') or '',
                            'height': m.get('height') or '',
                            'sheets': m.get('sheets') or '',
                        })
                    break
    if not suggested_mats:
        seen = {}
        for j in selected:
            seen[j['material_id']] = j['material_name']
        suggested_mats = [
            {'material_id': mid, 'name': name, 'width': '', 'height': '', 'sheets': ''}
            for mid, name in seen.items()
        ]
    return templates.TemplateResponse('ops_board.html', {
        'request': request,
        'jobs': selected,
        'job_keys': [j['key'] for j in selected],
        'catalog': materials,
        'defaults': defaults,
        'suggested_mats': suggested_mats,
        'pin': pin if OPS_PIN else '',
        'review': review,
    })


@router.post('/board/preview')
def ops_preview(body: BoardBody, _: None = Depends(_check_pin)):
    try:
        jobs, sheets, n_remaining = _run_pack(body)
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
            'customers': sorted({j['customer_code'] for j in jobs}),
        }
    except ValueError as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)


@router.post('/board/generate')
def ops_generate(body: BoardBody, _: None = Depends(_check_pin)):
    try:
        jobs, sheets, n_remaining = _run_pack(body)
        if not sheets:
            raise ValueError('没有生成任何板材，请检查材料尺寸')
        if n_remaining > 0 and not body.confirm_incomplete:
            return JSONResponse({
                'ok': False,
                'error': f'仍有 {n_remaining} 件排不下',
                'need_confirm_incomplete': True,
                'n_remaining': n_remaining,
                'sheets': sheets_to_json(sheets),
            }, status_code=409)

        pending = [j for j in jobs if j.get('job_status') == 'pending']
        all_keys = [j['key'] for j in jobs]

        ensure_dirs()
        day = datetime.now().strftime('%Y%m%d')
        out_dir = EPS_DIR / day
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = (body.prefix or '卡纸路径').strip() or '卡纸路径'
        paths = []
        eps_files = []
        for i, sheet in enumerate(sheets, 1):
            mat_w, mat_h, placed, secondary = sheet[0], sheet[1], sheet[2], sheet[3]
            mat_name = sheet[4] if len(sheet) > 4 else f'{mat_w:g}x{mat_h:g}'
            uid = uuid.uuid4().hex[:8]
            safe_mat = _safe_filename(mat_name)
            fname = f'{prefix}-{day}-板{i}-{safe_mat}-{uid}.eps'
            fpath = out_dir / fname
            make_eps(placed, str(fpath), mat_w, mat_h, secondary)
            paths.append(str(fpath))
            eps_files.append(_eps_file_info(day, fname))

        marked_done = False
        if pending:
            db.mark_jobs_done([j['key'] for j in pending])
            marked_done = True
        db.save_job_run(
            all_keys,
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
        zip_q = 'files=' + quote(','.join(f'{f["day"]}/{f["name"]}' for f in eps_files))
        return {
            'ok': True,
            'sheets': sheets_to_json(sheets),
            'n_remaining': n_remaining,
            'eps_paths': paths,
            'eps_files': eps_files,
            'zip_url': f'/ops/eps-zip?{zip_q}' if eps_files else '',
            'customers': sorted({j['customer_code'] for j in jobs}),
            'marked_done': marked_done,
        }
    except ValueError as e:
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=400)


@router.get('/eps/{day}/{filename}')
def download_eps(day: str, filename: str, pin: str = '',
                 x_ops_pin: Optional[str] = Header(default=None)):
    _check_pin(x_ops_pin=x_ops_pin, pin=pin)
    path = _resolve_eps(day, filename)
    return FileResponse(
        path,
        filename=path.name,
        media_type='application/postscript',
        content_disposition_type='attachment',
    )


@router.get('/eps-zip')
def download_eps_zip(files: str = '', pin: str = '',
                     x_ops_pin: Optional[str] = Header(default=None)):
    _check_pin(x_ops_pin=x_ops_pin, pin=pin)
    parts = [p.strip() for p in (files or '').split(',') if p.strip()]
    if not parts:
        raise HTTPException(400, '未指定文件')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for part in parts:
            if '/' not in part:
                raise HTTPException(400, '文件参数无效')
            day, name = part.split('/', 1)
            path = _resolve_eps(day, name)
            zf.write(path, arcname=path.name)
    buf.seek(0)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    return StreamingResponse(
        buf,
        media_type='application/zip',
        headers={
            'Content-Disposition': f'attachment; filename="eps-{stamp}.zip"',
        },
    )
