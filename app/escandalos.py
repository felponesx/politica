"""Escândalos de corrupção: casos curados à mão em app/dados/escandalos/<slug>.json, um arquivo por caso.

Cada afirmação sobre uma pessoa (situação na Justiça, prisão, valores) precisa de link da fonte; o que chega sem fonte
é descartado ao carregar. A situação jurídica usa termos exatos (investigado, denunciado, réu, condenado, condenação
anulada, absolvido...) e vale na data indicada (`data_situacao`), não necessariamente hoje.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "dados" / "escandalos"
AVISO = ("Todos são presumidos inocentes até a condenação definitiva (sem recurso possível). Ser investigado, "
         "denunciado ou réu não é condenação. A situação de cada pessoa é a da data indicada e pode ter mudado; "
         "confira a fonte. Encontrou um erro? Avise para corrigirmos.")
SITUACOES = {"investigado", "indiciado", "denunciado", "réu", "condenado", "condenado (recorre)", "condenação anulada",
             "absolvido", "processo arquivado", "prescrito", "pena cumprida", "indultado", "cassado", "renunciou",
             "exonerado", "morreu"}
LIBERDADE = {"preso", "prisão domiciliar", "em liberdade", "foragido"}


def _url(u) -> bool:
    return isinstance(u, str) and u.startswith(("http://", "https://"))


def _valor(v):
    """Valor só fica com fonte; sem fonte vira None."""
    if not isinstance(v, dict) or not _url(v.get("fonte")):
        return None
    n = v.get("valor")
    return {"valor": n if isinstance(n, (int, float)) else None, "texto": v.get("texto") or "", "fonte": v["fonte"]}


def _pessoa(p) -> dict | None:
    if not isinstance(p, dict) or not p.get("nome") or not _url(p.get("fonte")):
        return None
    situacao = (p.get("situacao") or "").strip().lower()
    liberdade = (p.get("liberdade") or "").strip().lower() or None
    return {"nome": p["nome"].strip(), "cargo_na_epoca": p.get("cargo_na_epoca"), "partido_na_epoca": p.get("partido_na_epoca"),
            "tipo": p.get("tipo"), "situacao": situacao if situacao in SITUACOES else None, "detalhe": p.get("detalhe") or "",
            "liberdade": liberdade if liberdade in LIBERDADE else None, "valor_recebido": _valor(p.get("valor_recebido")),
            "devolveu": _valor(p.get("devolveu")), "data_situacao": p.get("data_situacao"), "fonte": p["fonte"]}


def _caso(d: dict) -> dict:
    v = d.get("valores") or {}
    pessoas = [x for x in map(_pessoa, d.get("pessoas") or []) if x]
    andamento = sorted([a for a in d.get("andamento") or [] if isinstance(a, dict) and a.get("fato") and _url(a.get("fonte"))],
                       key=lambda a: str(a.get("data") or ""))
    atual = d.get("situacao_atual") if isinstance(d.get("situacao_atual"), dict) and _url((d.get("situacao_atual") or {}).get("fonte")) else None
    return {"slug": d["slug"], "nome": d["nome"], "outros_nomes": d.get("outros_nomes") or [], "periodo": d.get("periodo") or {},
            "ano_revelado": d.get("ano_revelado"), "resumo": d.get("resumo") or "",
            "valores": {"desviado": _valor(v.get("desviado")), "recuperado": _valor(v.get("recuperado")), "observacao": v.get("observacao") or ""},
            "orgaos": [o for o in d.get("orgaos") or [] if isinstance(o, dict) and o.get("nome")], "andamento": andamento,
            "situacao_atual": atual, "pessoas": pessoas, "fontes": [u for u in d.get("fontes") or [] if _url(u)],
            "verificado_em": d.get("verificado_em"), "aviso": AVISO}


@lru_cache(maxsize=1)
def casos() -> dict[str, dict]:
    out = {}
    for arq in sorted(PASTA.glob("*.json")):
        d = json.loads(arq.read_text(encoding="utf-8"))
        if d.get("slug") and d.get("nome"):
            out[d["slug"]] = _caso(d)
    return out


def resumo(c: dict) -> dict:
    p = c["pessoas"]
    return {k: c[k] for k in ("slug", "nome", "outros_nomes", "periodo", "ano_revelado", "resumo", "valores", "orgaos", "situacao_atual",
                              "verificado_em")} | {
        "pessoas": len(p),
        "condenados": sum(1 for x in p if (x["situacao"] or "").startswith("condenado") or x["situacao"] in ("pena cumprida", "indultado")),
        "presos": sum(1 for x in p if x["liberdade"] in ("preso", "prisão domiciliar")),
        "foragidos": sum(1 for x in p if x["liberdade"] == "foragido"),
        "partidos": sorted({x["partido_na_epoca"] for x in p if x["partido_na_epoca"]}),
    }


def listar() -> dict:
    itens = sorted((resumo(c) for c in casos().values()), key=lambda c: -(c["ano_revelado"] or 0))
    return {"total": len(itens), "itens": itens, "aviso": AVISO,
            "fonte": "Curadoria do BRASIL+ com base em decisões e notícias públicas (link em cada informação)."}
