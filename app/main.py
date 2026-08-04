from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import ensure_dirs
from app.db import init_db
from app.routes import ops, portal, sales


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    init_db()
    yield


app = FastAPI(title='切割路径生成器', lifespan=lifespan)
ROOT = Path(__file__).resolve().parent.parent
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')
app.include_router(portal.router)
app.include_router(sales.router)
app.include_router(ops.router)
