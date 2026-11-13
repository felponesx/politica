"""Empresas públicas, de economia mista, privadas e concessões, com faturamento e dívida (arquivo gerado pela tarefa empresas-tipo).
A rota não fica sob /empresas/… porque /empresas/{documento} já existe."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["Empresas"])
ARQUIVO = Path(__file__).resolve().parents[1] / "dados" / "empresas_tipos.json"


@lru_cache(maxsize=1)
def _carregar() -> dict | None:
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@router.get("/empresas-tipos", summary="Empresas públicas, de economia mista, privadas e concessões")
def empresas_tipos():
    d = _carregar()
    if not d:
        return {"disponivel": False, "empresas": []}
    return {"disponivel": True, **d}
