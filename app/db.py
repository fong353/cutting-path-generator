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
        '''SELECT m.id, m.name FROM demand_material dm
           JOIN material m ON m.id = dm.material_id
           WHERE dm.demand_id = ?
           ORDER BY m.sort_order, m.id''',
        (d['id'],),
    ).fetchall()
    d['materials'] = [dict(m) for m in mats]
    return d


def create_demand(work_date, customer_code, items, note='', submitter='', material_ids=None):
    """items: list of (ow, oh, iw, ih, qty). material_ids: 业务员指定的卡纸种类。"""
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
        for ow, oh, iw, ih, qty in items:
            conn.execute(
                '''INSERT INTO demand_item (demand_id, ow, oh, iw, ih, qty)
                   VALUES (?,?,?,?,?,?)''',
                (did, ow, oh, iw, ih, qty),
            )
        for mid in material_ids:
            conn.execute(
                'INSERT INTO demand_material (demand_id, material_id) VALUES (?,?)',
                (did, mid),
            )
        return did


def update_demand(demand_id, work_date, customer_code, items, note='', submitter='',
                  material_ids=None):
    """仅允许修改 pending 需求。items/material_ids 规则同 create_demand。"""
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
        for ow, oh, iw, ih, qty in items:
            conn.execute(
                '''INSERT INTO demand_item (demand_id, ow, oh, iw, ih, qty)
                   VALUES (?,?,?,?,?,?)''',
                (demand_id, ow, oh, iw, ih, qty),
            )
        for mid in material_ids:
            conn.execute(
                'INSERT INTO demand_material (demand_id, material_id) VALUES (?,?)',
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


def mark_demands_done(ids):
    if not ids:
        return
    placeholders = ','.join('?' * len(ids))
    with get_db() as conn:
        conn.execute(
            f"UPDATE demand SET status = 'done' WHERE id IN ({placeholders})",
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
