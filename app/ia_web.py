"""Pesquisa na internet para a IA do BRASIL+, pelo Perplexity (Agent API, preset "low").

Só roda no servidor: a chave fica em PERPLEXITY_API_KEY (.env) e nunca vai para o site. A IA do site chama
POST /ia/web quando os dados oficiais do BRASIL+ não têm a resposta (fatos recentes, contexto, perguntas gerais).

Proteções de custo: limite de perguntas por dia (perplexity_limite_dia), pergunta com no máximo 600 caracteres e
a mesma pergunta respondida da memória por 1 hora.
"""
from __future__ import annotations

import time
from datetime import date

import httpx

from app.config import settings

URL = "https://api.perplexity.ai/v1/responses"
INSTRUCOES = ("Responda em português do Brasil, de forma simples, curta e neutra (apartidária), sobre política, "
              "governo e dados públicos do Brasil. Diga a data dos fatos. Não afirme como fato o que é acusação ou "
              "investigação. Cite as fontes.")
AVISO = ("Resposta da internet (Perplexity), não dos dados oficiais do BRASIL+. Confira sempre as fontes; "
         "aparecer numa notícia não indica irregularidade.")
_CACHE: dict[str, tuple[float, dict]] = {}
_USO = {"dia": None, "n": 0}


class SemChave(RuntimeError):
    pass


class LimiteDiario(RuntimeError):
    pass


def _texto(resp: dict) -> str:
    if isinstance(resp.get("output_text"), str) and resp["output_text"].strip():
        return resp["output_text"].strip()
    partes = []
    for item in resp.get("output") or []:
        for c in (item.get("content") or []) if isinstance(item, dict) else []:
            if isinstance(c, dict) and c.get("type") in ("output_text", "text") and c.get("text"):
                partes.append(c["text"])
    return "\n\n".join(partes).strip()


def _fontes(resp) -> list[dict]:
    """Junta os links citados (anotações, resultados de busca, lista "citations"), sem repetir."""
    vistos, out = set(), []

    def add(url, titulo=None):
        if isinstance(url, str) and url.startswith("http") and url not in vistos:
            vistos.add(url)
            out.append({"titulo": (titulo or "").strip() or url, "url": url})

    def andar(x):
        if isinstance(x, dict):
            if "url" in x:
                add(x.get("url"), x.get("title") or x.get("titulo") or x.get("name"))
            for k, v in x.items():
                if k == "citations" and isinstance(v, list):
                    for u in v:
                        add(u) if isinstance(u, str) else andar(u)
                elif isinstance(v, (dict, list)):
                    andar(v)
        elif isinstance(x, list):
            for v in x:
                andar(v)

    andar(resp)
    return out[:10]


def pesquisar(pergunta: str) -> dict:
    pergunta = " ".join(str(pergunta or "").split())[:600]
    if not pergunta:
        raise ValueError("Pergunta vazia.")
    if not settings.perplexity_api_key:
        raise SemChave("Pesquisa na internet desligada: defina PERPLEXITY_API_KEY no .env do servidor.")
    chave = pergunta.lower()
    agora = time.time()
    if chave in _CACHE and agora - _CACHE[chave][0] < 3600:
        return _CACHE[chave][1]
    hoje = date.today()
    if _USO["dia"] != hoje:
        _USO.update(dia=hoje, n=0)
    if settings.perplexity_limite_dia and _USO["n"] >= settings.perplexity_limite_dia:
        raise LimiteDiario("Limite diário de pesquisas na internet atingido. Tente amanhã.")
    _USO["n"] += 1
    r = httpx.post(URL, timeout=settings.http_timeout,
                   headers={"Authorization": f"Bearer {settings.perplexity_api_key}", "Content-Type": "application/json"},
                   json={"preset": settings.perplexity_preset, "input": pergunta, "instructions": INSTRUCOES})
    r.raise_for_status()
    dados = r.json()
    texto = _texto(dados)
    if not texto:
        raise RuntimeError("O Perplexity não devolveu resposta.")
    out = {"pergunta": pergunta, "resposta": texto, "fontes": _fontes(dados), "modelo": dados.get("model"),
           "fonte": "Perplexity (pesquisa na internet)", "aviso": AVISO}
    _CACHE[chave] = (agora, out)
    return out
