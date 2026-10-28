"""Escândalos de corrupção: casos curados à mão em app/dados/escandalos/<slug>.json, um arquivo por caso.

Cada afirmação sobre uma pessoa (situação na Justiça, prisão, valores) precisa de link da fonte; o que chega sem fonte
é descartado ao carregar. A situação jurídica usa termos exatos (investigado, denunciado, réu, condenado, condenação
anulada, absolvido...) e vale na data indicada (`data_situacao`), não necessariamente hoje.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.utils import sem_acento

PASTA = Path(__file__).resolve().parent / "dados" / "escandalos"
AVISO = ("Todos são presumidos inocentes até a condenação definitiva (sem recurso possível). Ser investigado, "
         "denunciado ou réu não é condenação. A situação de cada pessoa é a da data indicada e pode ter mudado; "
         "confira a fonte. Encontrou um erro? Avise para corrigirmos.")
SITUACOES = {"investigado", "indiciado", "denunciado", "réu", "condenado", "condenado (recorre)", "condenação anulada",
             "absolvido", "processo arquivado", "prescrito", "pena cumprida", "indultado", "cassado", "renunciou",
             "exonerado", "morreu"}
LIBERDADE = {"preso", "prisão domiciliar", "em liberdade", "foragido", "morreu"}


def _url(u) -> bool:
    return isinstance(u, str) and u.startswith(("http://", "https://"))


def _valor(v):
    """Valor só fica com fonte; sem fonte vira None."""
    if not isinstance(v, dict) or not _url(v.get("fonte")):
        return None
    n = v.get("valor")
    return {"valor": n if isinstance(n, (int, float)) else None, "texto": v.get("texto") or "", "fonte": v["fonte"]}


def _lib(p: dict, liberdade) -> dict:
    """Data, fonte e frase da situação de prisão; sem fonte própria, vale a fonte geral da pessoa (quando há situação)."""
    if liberdade not in LIBERDADE:
        return {"liberdade_data": None, "liberdade_fonte": None, "liberdade_detalhe": ""}
    fonte = p.get("liberdade_fonte") if _url(p.get("liberdade_fonte")) else p.get("fonte")
    return {"liberdade_data": p.get("liberdade_data") or (p.get("data_situacao") if fonte == p.get("fonte") else None),
            "liberdade_fonte": fonte, "liberdade_detalhe": (p.get("liberdade_detalhe") or "")[:200],
            "liberdade_outro_processo": bool(p.get("liberdade_outro_processo"))}


def _pessoa(p) -> dict | None:
    if not isinstance(p, dict) or not p.get("nome") or not _url(p.get("fonte")):
        return None
    situacao = (p.get("situacao") or "").strip().lower()
    liberdade = (p.get("liberdade") or "").strip().lower() or None
    return {"nome": p["nome"].strip(), "cargo_na_epoca": p.get("cargo_na_epoca"), "partido_na_epoca": p.get("partido_na_epoca"),
            "tipo": p.get("tipo"), "situacao": situacao if situacao in SITUACOES else None, "detalhe": p.get("detalhe") or "",
            "liberdade": liberdade if liberdade in LIBERDADE else None, **_lib(p, liberdade), "valor_recebido": _valor(p.get("valor_recebido")),
            "devolveu": _valor(p.get("devolveu")), "data_situacao": p.get("data_situacao"), "fonte": p["fonte"]}


def _caso(d: dict) -> dict:
    v = d.get("valores") or {}
    pessoas = [x for x in map(_pessoa, d.get("pessoas") or []) if x]
    andamento = sorted([a for a in d.get("andamento") or [] if isinstance(a, dict) and a.get("fato") and _url(a.get("fonte"))],
                       key=lambda a: str(a.get("data") or ""))
    atual = d.get("situacao_atual") if isinstance(d.get("situacao_atual"), dict) and _url((d.get("situacao_atual") or {}).get("fonte")) else None
    org = _organograma(d["slug"], pessoas)
    return {"slug": d["slug"], "nome": d["nome"], "outros_nomes": d.get("outros_nomes") or [], "periodo": d.get("periodo") or {},
            "ano_revelado": d.get("ano_revelado"), "resumo": d.get("resumo") or "",
            "valores": {"desviado": _valor(v.get("desviado")), "recuperado": _valor(v.get("recuperado")), "observacao": v.get("observacao") or ""},
            "orgaos": [o for o in d.get("orgaos") or [] if isinstance(o, dict) and o.get("nome")], "andamento": andamento,
            "situacao_atual": atual, "pessoas": pessoas, "fontes": [u for u in d.get("fontes") or [] if _url(u)],
            "verificado_em": d.get("verificado_em"), "organograma": org, "aviso": AVISO}


def _organograma(slug: str, pessoas: list[dict]) -> dict | None:
    """Papéis segundo a acusação/investigação (app/dados/escandalos/papeis/<slug>.json): nível 1 = apontado como líder,
    2 = operador/intermediário, 3 = executor/beneficiário. Só entra quem está na lista de pessoas e tem fonte."""
    arq = PASTA / "papeis" / f"{slug}.json"
    if not arq.exists():
        return None
    d = json.loads(arq.read_text(encoding="utf-8"))
    nomes = {p["nome"] for p in pessoas}
    papeis = []
    for x in d.get("papeis") or []:
        if not isinstance(x, dict) or x.get("nome") not in nomes or not _url(x.get("fonte")) or x.get("nivel") not in (1, 2, 3):
            continue
        papeis.append({"nome": x["nome"], "nivel": x["nivel"], "nucleo": x.get("nucleo"), "papel": x.get("papel") or "",
                       "citacao": x.get("citacao") or "", "fonte": x["fonte"],
                       "acima": x.get("acima") if x.get("acima") in nomes and x.get("acima") != x["nome"] else None})
    if not papeis:
        return None
    return {"explicacao": d.get("explicacao") or "", "explicacao_fonte": d.get("explicacao_fonte") if _url(d.get("explicacao_fonte")) else None,
            "nucleos": [n for n in d.get("nucleos") or [] if isinstance(n, dict) and n.get("nome")], "papeis": papeis}


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
        "presos": sum(1 for x in p if x["liberdade"] in ("preso", "prisão domiciliar") and not x["liberdade_outro_processo"]),
        "foragidos": sum(1 for x in p if x["liberdade"] == "foragido"),
        "partidos": sorted({x["partido_na_epoca"] for x in p if x["partido_na_epoca"]}),
    }


def listar() -> dict:
    itens = sorted((resumo(c) for c in casos().values()), key=lambda c: -(c["ano_revelado"] or 0))
    return {"total": len(itens), "itens": itens, "aviso": AVISO,
            "fonte": "Curadoria do BRASIL+ com base em decisões e notícias públicas (link em cada informação)."}


CONDENADOS = ("condenado", "condenado (recorre)", "indultado", "pena cumprida")


def crimes() -> dict:
    """Agentes públicos (ex-deputados, ministros, governadores...) condenados nos casos curados. Só entra quem tem condenação
    registrada com fonte; "condenado (recorre)" ainda cabe recurso. Quem foi apenas investigado, réu ou absolvido não entra."""
    itens = []
    for c in casos().values():
        for p in c["pessoas"]:
            if p["tipo"] == "agente público" and p["situacao"] in CONDENADOS:
                itens.append({"nome": p["nome"], "cargo": p["cargo_na_epoca"], "partido": p["partido_na_epoca"], "situacao": p["situacao"],
                              "detalhe": p["detalhe"], "liberdade": p["liberdade"], "liberdade_data": p["liberdade_data"],
                              "data_situacao": p["data_situacao"], "caso": c["nome"], "slug": c["slug"], "ano_revelado": c["ano_revelado"],
                              "valor_recebido": p["valor_recebido"], "fonte": p["fonte"]})
    itens.sort(key=lambda x: (str(x["data_situacao"] or ""), x["nome"]), reverse=True)
    por_caso: dict[str, int] = {}
    for i in itens:
        por_caso[i["caso"]] = por_caso.get(i["caso"], 0) + 1
    return {"total": len(itens), "itens": itens, "por_caso": por_caso, "aviso": AVISO + " \"Condenado (recorre)\": ainda cabe recurso.",
            "fonte": "Curadoria do BRASIL+ com base em decisões e notícias públicas (link em cada informação)."}


@lru_cache(maxsize=1)
def _padroes() -> dict[str, re.Pattern]:
    """Um padrão por caso, com o nome e os outros nomes (sem acento e sem o "Caso"/"Operação" do começo), por palavra inteira."""
    out = {}
    for slug, c in casos().items():
        termos = []
        for t in [c["nome"], re.sub(r"\s*\(.*?\)", "", c["nome"]), *c["outros_nomes"]]:  # "Mensalão (Ação Penal 470)" também vale só "Mensalão"
            t = re.sub(r"^(operacao|caso|escandalo d[oa]s?|fraude n[oa]s?)\s+", "", sem_acento(t).lower())
            if len(t) > 3:
                termos.append(re.escape(t))
        if termos:
            out[slug] = re.compile(r"\b(?:" + "|".join(termos) + r")\b")
    return out


def casos_da_materia(titulo: str, resumo: str = "") -> list[str]:
    """Casos (slug) citados numa notícia. Só indica que o assunto aparece no texto; não diz nada sobre ninguém."""
    texto = sem_acento(f"{titulo} {resumo}").lower()
    achados = {slug: [m.span() for m in p.finditer(texto)] for slug, p in _padroes().items()}
    achados = {s: v for s, v in achados.items() if v}
    # "Mensalão mineiro" não conta como "Mensalão": o caso cujo trecho está dentro do trecho de outro caso sai
    return [s for s, v in achados.items()
            if not all(any(o != s and a2 <= a and b <= b2 and (a2, b2) != (a, b) for o, w in achados.items() for a2, b2 in w) for a, b in v)]
