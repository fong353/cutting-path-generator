from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / 'templates'))

router = APIRouter()


@router.get('/', response_class=HTMLResponse)
def portal(request: Request):
    return templates.TemplateResponse('portal.html', {'request': request})
