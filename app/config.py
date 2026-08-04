import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('CUT_DATA_DIR', ROOT / 'data'))
DB_PATH = DATA_DIR / 'app.db'
EPS_DIR = DATA_DIR / 'eps'
SETTINGS_PATH = DATA_DIR / 'ops_defaults.json'
OPS_PIN = os.environ.get('OPS_PIN', '').strip()
HOST = os.environ.get('CUT_HOST', '0.0.0.0')
PORT = int(os.environ.get('CUT_PORT', '8080'))

MATERIAL_SEED = [
    '黑卡纸',
    '黄卡纸',
    '绿卡纸',
    '蓝卡纸',
    '橙卡纸',
    '白卡纸',
    '白卡纸(无酸)',
]

# 标准板材尺寸（cm）；件外框须严格小于此（可旋转）
SHEET_W = 120.0
SHEET_H = 100.0


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EPS_DIR.mkdir(parents=True, exist_ok=True)


def fits_sheet(ow, oh, sw=None, sh=None):
    """外框能否放进板材（可旋转，须严格小于）。"""
    sw = SHEET_W if sw is None else sw
    sh = SHEET_H if sh is None else sh
    return (ow < sw and oh < sh) or (ow < sh and oh < sw)
