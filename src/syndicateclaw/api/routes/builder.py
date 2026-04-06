"""Serve visual workflow builder static shell."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["builder"])

_STATIC_DIR = Path(__file__).resolve().parents[2] / "static" / "builder"
_INDEX = _STATIC_DIR / "index.html"


@router.get("/builder/new", response_class=HTMLResponse)
async def builder_new() -> HTMLResponse:
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"))


@router.get("/builder/{workflow_id}", response_class=HTMLResponse)
async def builder_edit(workflow_id: str) -> HTMLResponse:
    _ = workflow_id
    return HTMLResponse(_INDEX.read_text(encoding="utf-8"))
