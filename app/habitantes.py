"""Interiorização (Censo 2010→2022 por tamanho de município), depressão (PNS 2013 e 2019), trabalho por plataforma (PNAD 2025)
e crises e benefícios por estado (saúde mental, deficiência, autismo, Bolsa Família, Gás do Povo, nem-nem, analfabetismo).
Dados de scripts/habitantes_extra.py e scripts/crises_pessoas.py."""
from __future__ import annotations

import json
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "dados" / "habitantes_extra.json"
CRISES = Path(__file__).resolve().parent / "dados" / "crises_pessoas.json"


def extra() -> dict | None:
    """Os recortes, com o que cada um mede e o que não mede (chave 'crises' inclui os indicadores por estado).
    None se o arquivo principal não existe."""
    if not ARQUIVO.exists():
        return None
    r = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    if CRISES.exists():
        r["crises"] = json.loads(CRISES.read_text(encoding="utf-8"))
    return r
