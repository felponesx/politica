"""Pesquisa na internet para a IA do BRASIL+, pelo Perplexity (Agent API, preset "low").

Só roda no servidor: a chave fica em PERPLEXITY_API_KEY (.env) e nunca vai para o site. A IA do site chama
POST /ia/web quando os dados oficiais do BRASIL+ não têm a resposta (fatos recentes, contexto, perguntas gerais).

Proteções de custo (app/ia_controle.py): limites por IP, globais e do dia guardados no banco (valem entre processos e
sobrevivem a reinício), orçamento diário estimado, teto de tokens da resposta, pergunta com no máximo 600 caracteres
e a mesma pergunta respondida do cache compartilhado.
"""
from __future__ import annotations

import httpx

from app import ia_controle
from app.config import settings

URL = "https://api.perplexity.ai/v1/responses"
INSTRUCOES = ("Responda em português do Brasil, de forma simples, curta e neutra (apartidária), sobre política, "
              "governo e dados públicos do Brasil. Diga a data dos fatos. Não afirme como fato o que é acusação ou "
              "investigação. Cite as fontes.")
AVISO = ("Resposta da internet (Perplexity), não dos dados oficiais do BRASIL+. Confira sempre as fontes; "
         "aparecer numa notícia não indica irregularidade.")

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


def _chamar(pergunta: str) -> dict:
    corpo = {"preset": settings.perplexity_preset, "input": pergunta, "instructions": INSTRUCOES}
    if settings.ia_max_saida_tokens > 0:
        corpo["max_output_tokens"] = settings.ia_max_saida_tokens  # teto de custo da resposta
    r = httpx.post(URL, timeout=settings.http_timeout, follow_redirects=False,
                   headers={"Authorization": f"Bearer {settings.perplexity_api_key}", "Content-Type": "application/json"},
                   json=corpo)
    r.raise_for_status()
    dados = r.json()
    if not isinstance(dados, dict):
        raise RuntimeError("Resposta inválida do Perplexity.")
    texto = _texto(dados)
    if not texto:
        raise RuntimeError("O Perplexity não devolveu resposta.")
    return {"pergunta": pergunta, "resposta": texto, "fontes": _fontes(dados), "modelo": dados.get("model"),
            "fonte": "Perplexity (pesquisa na internet)", "aviso": AVISO}


def pesquisar(pergunta: str, cliente: str = "?") -> dict:
    pergunta = " ".join(str(pergunta or "").split())[:600]
    if not pergunta:
        raise ValueError("Pergunta vazia.")
    if not settings.perplexity_api_key:
        raise SemChave("Pesquisa na internet desligada: defina PERPLEXITY_API_KEY no .env do servidor.")
    try:
        return ia_controle.executar("ia_web", cliente, pergunta.lower(), settings.ia_custo_chamada_usd,
                                    settings.perplexity_limite_dia, lambda: _chamar(pergunta))
    except ia_controle.Bloqueio as b:
        raise LimiteDiario(b.mensagem, b.status, b.espera) from b
