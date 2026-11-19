"""População por estado (Censo 2022): cor ou raça e sexo em porcentagem. Dados de scripts/populacao_censo.py."""
from __future__ import annotations

import json
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "dados" / "populacao_censo.json"
# código do IBGE → sigla (o site e o painel de saúde usam a sigla)
SIGLA = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE",
         "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
         "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}


def _pct(parte, total):
    return round(parte / total * 100, 2) if parte is not None and total else None


def _linha(nome: str, d: dict) -> dict:
    t = d.get("total")
    return {"nome": nome, "total": t, "homens": d.get("homens"), "mulheres": d.get("mulheres"),
            "indigena": d.get("indigena"), "indigena_pct": _pct(d.get("indigena"), t),
            "branca_pct": _pct(d.get("branca"), t), "preta_pct": _pct(d.get("preta"), t),
            "parda_pct": _pct(d.get("parda"), t), "amarela_pct": _pct(d.get("amarela"), t),
            "pardos_pretos_pct": _pct((d.get("parda") or 0) + (d.get("preta") or 0), t) if t else None,
            "mulheres_pct": _pct(d.get("mulheres"), t)}


def censo() -> dict | None:
    """Por estado e Brasil, com porcentagens prontas. None se o arquivo ainda não foi gerado."""
    if not ARQUIVO.exists():
        return None
    d = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    return {
        "fonte": d["fonte"], "link": d["link"], "metodo": d["metodo"], "gerado_em": d.get("gerado_em"), "ano": d["ano"],
        "aviso": ("Cor ou raça é autodeclarada. O número de indígenas desta tabela (cor ou raça) é menor que o divulgado pelo IBGE "
                  "pelo critério de pertencimento étnico: esta tela mostra só o que a tabela de cor ou raça traz."),
        "brasil": _linha("Brasil", d["brasil"]),
        "estados": {SIGLA.get(uf, uf): _linha(e["nome"], e) for uf, e in d["estados"].items()},
    }
