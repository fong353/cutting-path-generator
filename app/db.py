"""SQLite 访问。"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime

from app.config import DB_PATH, MATERIAL_SEED, ensure_dirs


def _connect():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS material (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS demand (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            customer_code TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            submitter TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS demand_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            demand_id INTEGER NOT NULL REFERENCES demand(id) ON DELETE CASCADE,
            ow REAL NOT NULL,
            oh REAL NOT NULL,
            iw REAL NOT NULL DEFAULT 0,
            ih REAL NOT NULL DEFAULT 0,
            qty INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS demand_material (
            demand_id INTEGER NOT NULL REFERENCES demand(id) ON DELETE CASCADE,
            material_id INTEGER NOT NULL REFERENCES material(id),
            status TEXT NOT NULL DEFAULT 'pending',
            PRIMARY KEY (demand_id, material_id)
        );
        CREATE TABLE IF NOT EXISTS job_run (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            demand_ids TEXT NOT NULL,
            materials_snapshot TEXT NOT NULL,
            eps_paths TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        cur = conn.execute('SELECT COUNT(*) AS c FROM material')
        if cur.fetchone()['c'] == 0:
            for i, name in enumerate(MATERIAL_SEED):
                conn.execute(
                    'INSERT INTO material (name, enabled, sort_order) VALUES (?,?,?)',
                    (name, 1, i + 1),
                )
        _ensure_item_offset_columns(conn)


def _ensure_item_offset_columns(conn):
    cols = {r[1] for r in conn.execute('PRAGMA table_info(demand_item)')}
    if 'hole_left' not in cols:
        conn.execute('ALTER TABLE demand_item ADD COLUMN hole_left REAL')
    if 'hole_bottom' not in cols:
        conn.execute('ALTER TABLE demand_item ADD COLUMN hole_bottom REAL')
    dm_cols = {r[1] for r in conn.execute('PRAGMA table_info(demand_material)')}
    if 'status' not in dm_cols:
        conn.execute(
            "ALTER TABLE demand_material ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )


def list_materials(enabled_only=True):
    with get_db() as conn:
        q = 'SELECT * FROM material'
        if enabled_only:
            q += ' WHERE enabled = 1'
        q += ' ORDER BY sort_order, id'
        return [dict(r) for r in conn.execute(q)]


def _attach_demand_extras(conn, d):
    items = conn.execute(
        'SELECT * FROM demand_item WHERE demand_id = ? ORDER BY id', (d['id'],)
    ).fetchall()
    d['item_rows'] = [dict(i) for i in items]
    mats = conn.execute(
        '''SELECT m.id, m.name, dm.status AS job_status FROM demand_material dm
           JOIN material m ON m.id = dm.material_id
           WHERE dm.demand_id = ?
           ORDER BY m.sort_order, m.id''',
        (d['id'],),
    ).fetchall()
    d['materials'] = [dict(m) for m in mats]
    return d


def create_demand(work_date, customer_code, items, note='', submitter='', material_ids=None):
    """items: (ow, oh, iw, ih, qty) 或 (ow, oh, iw, ih, qty, hole_left, hole_bottom)。"""
    now = datetime.now().isoformat(timespec='seconds')
    material_ids = list(dict.fromkeys(int(x) for x in (material_ids or [])))
    with get_db() as conn:
        if material_ids:
            placeholders = ','.join('?' * len(material_ids))
            rows = conn.execute(
                f'SELECT id FROM material WHERE enabled = 1 AND id IN ({placeholders})',
                material_ids,
            ).fetchall()
            if len(rows) != len(material_ids):
                raise ValueError('所选材料无效或已停用')
        cur = conn.execute(
            '''INSERT INTO demand (work_date, customer_code, note, submitter, status, created_at)
               VALUES (?,?,?,?, 'pending', ?)''',
            (work_date, customer_code.strip(), note or '', submitter or '', now),
        )
        did = cur.lastrowid
        for it in items:
            ow, oh, iw, ih, qty = it[0], it[1], it[2], it[3], it[4]
            hl = it[5] if len(it) > 5 else None
            hb = it[6] if len(it) > 6 else None
            conn.execute(
                '''INSERT INTO demand_item
                   (demand_id, ow, oh, iw, ih, qty, hole_left, hole_bottom)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (did, ow, oh, iw, ih, qty, hl, hb),
            )
        for mid in material_ids:
            conn.execute(
                '''INSERT INTO demand_material (demand_id, material_id, status)
                   VALUES (?,?, 'pending')''',
                (did, mid),
            )
        return did


def update_demand(demand_id, work_date, customer_code, items, note='', submitter='',
                  material_ids=None):
    """仅允许修改 pending 需求。"""
    material_ids = list(dict.fromkeys(int(x) for x in (material_ids or [])))
    with get_db() as conn:
        row = conn.execute('SELECT status FROM demand WHERE id = ?', (demand_id,)).fetchone()
        if not row:
            raise ValueError('需求不存在')
        if row['status'] != 'pending':
            raise ValueError('已拼板完成的需求不能修改')
        if material_ids:
            placeholders = ','.join('?' * len(material_ids))
            found = conn.execute(
                f'SELECT id FROM material WHERE enabled = 1 AND id IN ({placeholders})',
                material_ids,
            ).fetchall()
            if len(found) != len(material_ids):
                raise ValueError('所选材料无效或已停用')
        conn.execute(
            '''UPDATE demand SET work_date=?, customer_code=?, note=?, submitter=?
               WHERE id=?''',
            (work_date, customer_code.strip(), note or '', submitter or '', demand_id),
        )
        conn.execute('DELETE FROM demand_item WHERE demand_id = ?', (demand_id,))
        conn.execute('DELETE FROM demand_material WHERE demand_id = ?', (demand_id,))
        for it in items:
            ow, oh, iw, ih, qty = it[0], it[1], it[2], it[3], it[4]
            hl = it[5] if len(it) > 5 else None
            hb = it[6] if len(it) > 6 else None
            conn.execute(
                '''INSERT INTO demand_item
                   (demand_id, ow, oh, iw, ih, qty, hole_left, hole_bottom)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (demand_id, ow, oh, iw, ih, qty, hl, hb),
            )
        for mid in material_ids:
            conn.execute(
                '''INSERT INTO demand_material (demand_id, material_id, status)
                   VALUES (?,?, 'pending')''',
                (demand_id, mid),
            )


def list_demands(work_date=None, status=None):
    with get_db() as conn:
        clauses, args = [], []
        if work_date:
            clauses.append('work_date = ?')
            args.append(work_date)
        if status:
            clauses.append('status = ?')
            args.append(status)
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        rows = conn.execute(
            f'SELECT * FROM demand{where} ORDER BY work_date DESC, id DESC', args
        ).fetchall()
        return [_attach_demand_extras(conn, dict(r)) for r in rows]


def get_demands_by_ids(ids):
    if not ids:
        return []
    placeholders = ','.join('?' * len(ids))
    with get_db() as conn:
        rows = conn.execute(
            f'SELECT * FROM demand WHERE id IN ({placeholders}) ORDER BY id',
            list(ids),
        ).fetchall()
        return [_attach_demand_extras(conn, dict(r)) for r in rows]


def list_jobs(work_date=None, status=None):
    """
    按「客户 × 材料」拆行。
    status: 'pending' / 'done' / None(全部)。
    """
    with get_db() as conn:
        clauses, args = [], []
        if status:
            clauses.append('dm.status = ?')
            args.append(status)
        if work_date:
            clauses.append('d.work_date = ?')
            args.append(work_date)
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        rows = conn.execute(
            f'''SELECT d.id AS demand_id, d.work_date, d.customer_code, d.note,
                       d.submitter, d.created_at, d.status AS demand_status,
                       dm.status AS job_status,
                       m.id AS material_id, m.name AS material_name
                FROM demand_material dm
                JOIN demand d ON d.id = dm.demand_id
                JOIN material m ON m.id = dm.material_id
                {where}
                ORDER BY d.work_date DESC, m.sort_order, d.customer_code, d.id''',
            args,
        ).fetchall()
        result = []
        for r in rows:
            job = dict(r)
            items = conn.execute(
                'SELECT * FROM demand_item WHERE demand_id = ? ORDER BY id',
                (job['demand_id'],),
            ).fetchall()
            job['item_rows'] = [dict(i) for i in items]
            job['key'] = f"{job['demand_id']}-{job['material_id']}"
            result.append(job)
        return result


def list_pending_jobs(work_date=None):
    return list_jobs(work_date=work_date, status='pending')


def get_jobs_by_keys(keys):
    """keys: ['demandId-materialId', ...]"""
    parsed = []
    for k in keys or []:
        parts = str(k).strip().split('-')
        if len(parts) != 2:
            continue
        try:
            parsed.append((int(parts[0]), int(parts[1])))
        except ValueError:
            continue
    if not parsed:
        return []
    result = []
    with get_db() as conn:
        for did, mid in parsed:
            row = conn.execute(
                '''SELECT d.id AS demand_id, d.work_date, d.customer_code, d.note,
                          d.submitter, d.created_at, d.status AS demand_status,
                          dm.status AS job_status,
                          m.id AS material_id, m.name AS material_name
                   FROM demand_material dm
                   JOIN demand d ON d.id = dm.demand_id
                   JOIN material m ON m.id = dm.material_id
                   WHERE dm.demand_id = ? AND dm.material_id = ?''',
                (did, mid),
            ).fetchone()
            if not row:
                continue
            job = dict(row)
            items = conn.execute(
                'SELECT * FROM demand_item WHERE demand_id = ? ORDER BY id',
                (did,),
            ).fetchall()
            job['item_rows'] = [dict(i) for i in items]
            job['key'] = f'{did}-{mid}'
            result.append(job)
    return result


def mark_jobs_done(keys):
    """将指定 demand×material 标为 done；若该需求所有材料均完成则 demand 标 done。"""
    jobs = get_jobs_by_keys(keys)
    if not jobs:
        return
    with get_db() as conn:
        demand_ids = set()
        for j in jobs:
            conn.execute(
                '''UPDATE demand_material SET status = 'done'
                   WHERE demand_id = ? AND material_id = ?''',
                (j['demand_id'], j['material_id']),
            )
            demand_ids.add(j['demand_id'])
        for did in demand_ids:
            left = conn.execute(
                '''SELECT COUNT(*) AS c FROM demand_material
                   WHERE demand_id = ? AND status = 'pending' ''',
                (did,),
            ).fetchone()['c']
            if left == 0:
                conn.execute(
                    "UPDATE demand SET status = 'done' WHERE id = ?", (did,)
                )


def mark_demands_done(ids):
    if not ids:
        return
    placeholders = ','.join('?' * len(ids))
    with get_db() as conn:
        conn.execute(
            f"UPDATE demand SET status = 'done' WHERE id IN ({placeholders})",
            list(ids),
        )
        conn.execute(
            f"UPDATE demand_material SET status = 'done' WHERE demand_id IN ({placeholders})",
            list(ids),
        )


def delete_demand(demand_id, allow_done=False):
    """删除需求及其明细。默认仅 pending；allow_done=True 时已完成也可删。"""
    with get_db() as conn:
        row = conn.execute('SELECT status FROM demand WHERE id = ?', (demand_id,)).fetchone()
        if not row:
            raise ValueError('需求不存在')
        if row['status'] != 'pending' and not allow_done:
            raise ValueError('已拼板完成的需求不能删除')
        conn.execute('DELETE FROM demand_item WHERE demand_id = ?', (demand_id,))
        conn.execute('DELETE FROM demand_material WHERE demand_id = ?', (demand_id,))
        conn.execute('DELETE FROM demand WHERE id = ?', (demand_id,))


def save_job_run(demand_ids, materials_snapshot, eps_paths):
    now = datetime.now().isoformat(timespec='seconds')
    with get_db() as conn:
        conn.execute(
            '''INSERT INTO job_run (demand_ids, materials_snapshot, eps_paths, created_at)
               VALUES (?,?,?,?)''',
            (json.dumps(demand_ids), json.dumps(materials_snapshot, ensure_ascii=False),
             json.dumps(eps_paths, ensure_ascii=False), now),
        )


def today_str():
    return date.today().isoformat()
