import json
from pathlib import Path

from app.config import SETTINGS_PATH, ensure_dirs

DEFAULT_OPS = {
    'gap': '1',
    'fill_last': True,
    'prefix': '卡纸路径',
    'materials': [
        {'material_id': None, 'name': '', 'width': '', 'height': '', 'sheets': ''},
    ],
    'fill': [
        {'fw': '42', 'fh': '29.7', 'fiw': '', 'fih': '', 'enabled': True},
        {'fw': '29.7', 'fh': '21', 'fiw': '', 'fih': '', 'enabled': True},
        {'fw': '21', 'fh': '14.8', 'fiw': '', 'fih': '', 'enabled': True},
    ],
}


def load_ops_defaults():
    ensure_dirs()
    if not SETTINGS_PATH.exists():
        return json.loads(json.dumps(DEFAULT_OPS))
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            data = json.load(f)
        out = json.loads(json.dumps(DEFAULT_OPS))
        out.update(data)
        return out
    except Exception:
        return json.loads(json.dumps(DEFAULT_OPS))


def save_ops_defaults(data: dict):
    ensure_dirs()
    cur = load_ops_defaults()
    cur.update(data)
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
