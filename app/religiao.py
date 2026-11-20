"""Religião por estado (Censo 2022) e organizações religiosas registradas (CNAE 94.91-0). Dados de scripts/religiao.py."""
from __future__ import annotations

import json
from pathlib import Path

from app import populacao

ARQUIVO = Path(__file__).resolve().parent / "dados" / "religiao.json"
CATEGORIAS = ["catolica", "evangelicas", "espirita", "umbanda_candomblé", "tradicoes_indigenas", "outras",
              "sem_religiao", "nao_sabe", "sem_declaracao"]
VARIAS = {
    "medido": False,
    "motivo": "O Censo 2022 pergunta uma religião por pessoa. Não existe base aberta com a porcentagem de quem declara mais de uma religião.",
}


def _pct(parte, total):
    return round(parte / total * 100, 2) if parte is not None and total else None


def _por_100mil(n, pop):
    return round(n / pop * 100_000, 1) if n is not None and pop else None


def _ultimo_ano(igrejas: dict) -> str | None:
    return max(igrejas, default=None)


def _linha(total, categorias, igrejas, pop):
    ano = _ultimo_ano(igrejas)
    n = igrejas.get(ano) if ano else None
    return {
        "total": total,
        "pct": {k: _pct(categorias.get(k), total) for k in CATEGORIAS},
        "pessoas": {k: categorias.get(k) for k in CATEGORIAS},
        "igrejas": {"ano": int(ano) if ano else None, "unidades": n, "por_100mil_hab": _por_100mil(n, pop),
                    "serie": {a: igrejas[a] for a in sorted(igrejas)}},
    }


def religiao() -> dict | None:
    """Religião por estado e Brasil, com porcentagens e organizações religiosas por 100 mil habitantes. None se o arquivo não existe."""
    if not ARQUIVO.exists():
        return None
    d = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    pop = populacao.censo()
    pop_uf = {s: e["total"] for s, e in (pop or {}).get("estados", {}).items()}
    pop_br = (pop or {}).get("brasil", {}).get("total")
    estados = {}
    for sigla, e in d["estados"].items():
        linha = _linha(e["total"], e["categorias"], e["igrejas"], pop_uf.get(sigla))
        estados[sigla] = {"nome": e["nome"], **linha}
    brasil = _linha(d["brasil"]["total"], d["brasil"]["categorias"], d["brasil"]["igrejas"], pop_br)
    return {
        "fonte": d["fonte"], "link": d["link"], "metodo": d["metodo"], "gerado_em": d.get("gerado_em"),
        "censo_ano": d["censo_ano"], "base": d["base"], "varias_religioes": VARIAS,
        "brasil": brasil, "estados": estados,
    }
