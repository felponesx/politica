"""Busca na internet pela Perplexity Search API (POST https://api.perplexity.ai/search).

Devolve resultados crus e ordenados (título, link, trecho e datas), sem resposta escrita por IA: quem escreve a
resposta é a IA do site (Claude), com a ferramenta buscar_na_web. Para resposta pronta com fontes no modo simples,
veja app/ia_web.py (Agent API).

A chave fica só no servidor (PERPLEXITY_API_KEY). Proteções de custo (US$ 5 por mil buscas): limite por dia
(perplexity_busca_limite_dia), até 5 consultas por chamada (é cobrada uma só) e a mesma busca guardada 1 hora.
Parâmetros e campos copiados da referência: https://docs.perplexity.ai/api-reference/search-post
"""
from __future__ import annotations

import json
import logging
import random
import time
import httpx

from app import ia_controle
from app.config import settings

log = logging.getLogger("brasilplus.busca_web")

URL = "https://api.perplexity.ai/search"
RECENCIAS = ("hour", "day", "week", "month", "year")
AVISO = ("Resultados da internet (Perplexity Search), não dos dados oficiais do BRASIL+. Confira cada fonte; "
         "aparecer num resultado não indica irregularidade.")

class SemChave(RuntimeError):
    pass


class LimiteDiario(RuntimeError):
    """Pedido barrado pelos limites (429) ou pelo controle indisponível (503): args = (mensagem, status, espera em segundos)."""

    @property
    def status(self) -> int:
        return self.args[1] if len(self.args) > 1 else 429

    @property
    def espera(self) -> int:
        return self.args[2] if len(self.args) > 2 else 30


def _consultas(query) -> str | list[str]:
    lista = [query] if isinstance(query, str) else list(query or [])
    lista = [" ".join(str(q).split())[:400] for q in lista if str(q).strip()]
    if not lista:
        raise ValueError("Consulta vazia.")
    if len(lista) > 5:
        raise ValueError("No máximo 5 consultas por busca.")
    return lista[0] if len(lista) == 1 else lista


def _paginas(resultados) -> list[dict]:
    """Achata a lista (na busca com várias consultas cada uma tem a sua) e tira links repetidos, mantendo a ordem."""
    vistos, out = set(), []
    pilha = list(resultados or [])
    while pilha:
        r = pilha.pop(0)
        if isinstance(r, list):
            pilha[0:0] = r
            continue
        url = r.get("url") if isinstance(r, dict) else None
        if not url or url in vistos:
            continue
        vistos.add(url)
        out.append({"titulo": r.get("title") or url, "url": url, "trecho": r.get("snippet") or "",
                    "data": r.get("date"), "atualizado": r.get("last_updated")})
    return out


def _post(corpo: dict) -> dict:
    """POST com até 3 tentativas para 429/5xx; respeita Retry-After e senão espera exponencial com variação."""
    espera = 1.0
    for tentativa in range(1, 4):
        r = httpx.post(URL, json=corpo, timeout=settings.http_timeout, follow_redirects=False,
                       headers={"Authorization": f"Bearer {settings.perplexity_api_key}",
                                "Content-Type": "application/json"})
        if r.status_code in (429, 500, 502, 503, 504) and tentativa < 3:
            depois = r.headers.get("Retry-After", "")
            pausa = min(float(depois), 30.0) if depois.replace(".", "", 1).isdigit() else espera + random.random()
            log.warning("Perplexity Search respondeu %s; tentando de novo em %.1fs", r.status_code, pausa)
            time.sleep(pausa)
            espera *= 2
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("inalcançável")


def buscar(query: str | list[str], max_resultados: int = 10, pais: str | None = "BR", idiomas: list[str] | None = None,
           dominios: list[str] | None = None, recencia: str | None = None, depois_de: str | None = None,
           antes_de: str | None = None, max_tokens_por_pagina: int | None = None, cliente: str = "?") -> dict:
    """Busca na internet. `query`: texto ou até 5 textos (cobrados como uma busca).

    dominios: só estes sites ("gov.br") ou, com "-" na frente, todos menos estes (não misture os dois);
    recencia: hour, day, week, month ou year; depois_de/antes_de: data de publicação em MM/DD/AAAA."""
    if not settings.perplexity_api_key:
        raise SemChave("Busca na internet desligada: defina PERPLEXITY_API_KEY no .env do servidor.")
    consultas = _consultas(query)
    corpo: dict = {"query": consultas, "max_results": max(1, min(20, int(max_resultados)))}
    if pais:
        corpo["country"] = pais.upper()[:2]
    if idiomas:
        corpo["search_language_filter"] = [i.lower()[:2] for i in idiomas][:20]
    if dominios:
        dominios = [d.strip() for d in dominios if d and d.strip()][:20]
        if len({d.startswith("-") for d in dominios}) > 1:
            raise ValueError("Use só domínios permitidos ou só bloqueados (com '-'), não os dois juntos.")
        corpo["search_domain_filter"] = dominios
    if recencia:
        if recencia not in RECENCIAS:
            raise ValueError(f"recencia deve ser uma de: {', '.join(RECENCIAS)}.")
        corpo["search_recency_filter"] = recencia
    if depois_de:
        corpo["search_after_date_filter"] = depois_de
    if antes_de:
        corpo["search_before_date_filter"] = antes_de
    if max_tokens_por_pagina:
        corpo["max_tokens_per_page"] = max(256, min(4096, int(max_tokens_por_pagina)))

    chave = json.dumps(corpo, sort_keys=True, ensure_ascii=False)

    def chamar() -> dict:
        dados = _post(corpo)
        if not isinstance(dados, dict):
            raise RuntimeError("Resposta inválida do Perplexity.")
        return {"consultas": [consultas] if isinstance(consultas, str) else consultas,
                "resultados": _paginas(dados.get("results")), "id": dados.get("id"),
                "fonte": "Perplexity Search API", "aviso": AVISO}

    try:
        return ia_controle.executar("busca_web", cliente, chave, settings.ia_custo_busca_usd,
                                    settings.perplexity_busca_limite_dia, chamar)
    except ia_controle.Bloqueio as b:
        raise LimiteDiario(b.mensagem, b.status, b.espera) from b
