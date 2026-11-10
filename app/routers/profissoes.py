"""Salários por profissão (RAIS, microdados públicos do Ministério do Trabalho).

Só agregados: nenhuma pessoa, nenhum CPF e nenhuma empresa aparecem. Profissões com menos de 30 vínculos
já vêm fora do arquivo. Os dados são lidos de app/dados/profissoes_rais.json (gerado pelo coletor).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["Salários por profissão"])

ARQUIVO = Path(__file__).resolve().parents[1] / "dados" / "profissoes_rais.json"

AVISO = (
    "Dados da RAIS (Ministério do Trabalho e Emprego). Mostra a média e a distribuição dos salários de cada profissão "
    "(vínculos ativos em 31/12 do ano). Não identifica pessoas nem empresas. A RAIS não informa a escala de trabalho "
    "(6x1, 5x2): só o número de horas contratadas. Salário médio não é o que uma pessoa específica recebe."
)


@lru_cache(maxsize=1)
def _carregar() -> dict | None:
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _arredonda(v, casas=2):
    return None if v is None else round(float(v), casas)


@router.get("/profissoes", summary="Salários por profissão (RAIS)")
def profissoes():
    d = _carregar()
    if not d or not d.get("profissoes"):
        return {"disponivel": False, "aviso": AVISO, "profissoes": []}
    lista = []
    for cbo, p in d["profissoes"].items():
        lista.append({
            "cbo": cbo,
            "vinculos": p.get("vinculos"),
            "media": _arredonda(p.get("media")),
            "minimo": _arredonda(p.get("minimo")),
            "maximo": _arredonda(p.get("maximo")),
            "p10": _arredonda(p.get("p10")),
            "p90": _arredonda(p.get("p90")),
            "horas": p.get("horas") or [],
        })
    lista.sort(key=lambda x: (x["media"] or 0), reverse=True)
    return {
        "disponivel": True,
        "fonte": d.get("fonte"),
        "ano_referencia": d.get("ano_referencia"),
        "atualizado_em": d.get("atualizado_em"),
        "vinculos_validos": d.get("vinculos_validos"),
        "total_profissoes": len(lista),
        "observacao": d.get("observacao"),
        "aviso": AVISO,
        "profissoes": lista,
    }
