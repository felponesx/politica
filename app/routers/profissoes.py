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


NOMES_ARQUIVO = Path(__file__).resolve().parents[1] / "dados" / "cbo_nomes.json"


@lru_cache(maxsize=1)
def _cbo() -> dict:
    try:
        return json.loads(NOMES_ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _nomes() -> dict:
    return _cbo().get("nomes", {})


def _familias() -> dict:
    return _cbo().get("familias", {})


@lru_cache(maxsize=1)
def _carregar() -> dict | None:
    try:
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def _historico() -> dict:
    """{ano: {cbo: {"media":…, "vinculos":…}}} dos anos anteriores coletados (profissoes_rais_<ano>.json)."""
    out = {}
    for arq in sorted(ARQUIVO.parent.glob("profissoes_rais_*.json")):
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
            out[int(d["ano_referencia"])] = {c: {"media": p.get("media"), "vinculos": p.get("vinculos")} for c, p in d["profissoes"].items()}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


AVISO_HISTORICO = ("Comparação entre anos em valores nominais (sem correção pela inflação). A lista de profissões e a forma de "
                   "declarar podem mudar de um ano para outro. Variação acima de 50% para mais ou para menos aparece como \"a conferir\" "
                   "(provável mudança na forma de declarar) e fica fora das listas de maior aumento e maior queda.")


def _arredonda(v, casas=2):
    return None if v is None else round(float(v), casas)


@router.get("/profissoes", summary="Salários por profissão (RAIS)")
def profissoes():
    d = _carregar()
    if not d or not d.get("profissoes"):
        return {"disponivel": False, "aviso": AVISO, "profissoes": []}
    lista = []
    nomes, familias = _nomes(), _familias()
    atual = int(d.get("ano_referencia") or 0)
    hist = {a: v for a, v in _historico().items() if a != atual}
    for cbo, p in d["profissoes"].items():
        lista.append({
            "cbo": cbo,
            "nome": nomes.get(cbo),
            # código sem título na lista oficial (ocupação criada depois): ao menos a família oficial dele
            "familia": None if nomes.get(cbo) else familias.get(cbo[:4]),
            "vinculos": p.get("vinculos"),
            "media": _arredonda(p.get("media")),
            "minimo": _arredonda(p.get("minimo")),
            "maximo": _arredonda(p.get("maximo")),
            "p10": _arredonda(p.get("p10")),
            "p90": _arredonda(p.get("p90")),
            "horas": p.get("horas") or [],
            "historico": {str(a): _arredonda(v[cbo]["media"]) for a, v in sorted(hist.items()) if cbo in v} | {str(atual): _arredonda(p.get("media"))} if hist else {},
        })
    lista.sort(key=lambda x: (x["media"] or 0), reverse=True)
    return {
        "disponivel": True,
        "nomes_fonte": "CBO 2002, lista oficial do Ministério do Trabalho e Emprego (gov.br) e listas derivadas dela",
        "com_nome": sum(1 for x in lista if x["nome"]),
        "fonte": d.get("fonte"),
        "ano_referencia": d.get("ano_referencia"),
        "atualizado_em": d.get("atualizado_em"),
        "vinculos_validos": d.get("vinculos_validos"),
        "total_profissoes": len(lista),
        "observacao": d.get("observacao"),
        "aviso": AVISO,
        "anos": sorted([*hist, atual]),
        "aviso_historico": AVISO_HISTORICO if hist else None,
        "profissoes": lista,
    }
