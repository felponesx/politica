"""Interiorização (Censo 2010→2022 por tamanho de município), depressão (PNS 2013) e trabalho por plataforma (PNAD 2025).
Dados de scripts/habitantes_extra.py."""
from __future__ import annotations

import json
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "dados" / "habitantes_extra.json"


def extra() -> dict | None:
    """Os três recortes, com o que cada um mede e o que não mede. None se o arquivo não existe."""
    if not ARQUIVO.exists():
        return None
    return json.loads(ARQUIVO.read_text(encoding="utf-8"))
