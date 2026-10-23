"""Portão único das chamadas pagas à IA (Perplexity): limites compartilhados entre processos, orçamento do dia, concorrência,
cache compartilhado e registro de uso (sem pergunta nem resposta).

Ordem em `executar`: cache compartilhado (de graça) → limites (por IP por minuto e por dia, global por minuto, total do dia da
rota, orçamento estimado do dia) → vaga de concorrência → chamada ao provedor. Se o banco dos contadores falhar, a chamada é
BLOQUEADA (503): sem contador não há como garantir o teto de custo.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from app import limites
from app.config import settings

_VAGAS = threading.BoundedSemaphore(max(1, settings.ia_concorrencia))


class Bloqueio(Exception):
    def __init__(self, status: int, mensagem: str, espera: int = 30):
        super().__init__(mensagem)
        self.status, self.mensagem, self.espera = status, mensagem, espera


def _micro(usd: float) -> int:
    return max(0, round(usd * 1_000_000))


def _gastar(chave: str, limite: int, janela_s: int, custo: int, msg: str) -> None:
    if limite <= 0:  # 0 = sem limite nesta regra
        return
    r = limites.consumir(chave, limite, janela_s, custo)
    if not r.ok:
        raise Bloqueio(429, msg, r.reinicia_em)


def autorizar(rota: str, cliente: str, custo_usd: float, limite_dia_rota: int) -> None:
    try:
        _gastar(f"ia:ip:{cliente}:min", settings.limite_ia_ip_minuto, 60, 1, "Muitas perguntas seguidas. Espere um minuto e tente de novo.")
        _gastar(f"ia:ip:{cliente}:dia", settings.limite_ia_ip_dia, 86400, 1, "Você atingiu o limite de pesquisas na internet de hoje.")
        _gastar("ia:global:min", settings.limite_ia_global_minuto, 60, 1, "A pesquisa na internet está muito usada agora. Tente em instantes.")
        _gastar(f"ia:{rota}:dia", limite_dia_rota, 86400, 1, "Limite diário de pesquisas na internet atingido. Tente amanhã.")
        _gastar("ia:orcamento:dia", _micro(settings.ia_orcamento_dia_usd), 86400, _micro(custo_usd),
                "Orçamento diário da pesquisa na internet atingido. Tente amanhã.")
    except limites.LimiteIndisponivel:
        raise Bloqueio(503, "Controle de uso indisponível; a pesquisa na internet está pausada por segurança.", 60)


def executar(rota: str, cliente: str, chave_cache: str, custo_usd: float, limite_dia_rota: int, chamar: Callable[[], dict]) -> dict:
    """Devolve a resposta (do cache ou do provedor) ou levanta `Bloqueio`. Erros do provedor sobem como vieram (o custo já foi contado)."""
    ch = limites.hash_cliente(cliente)
    ck = f"{rota}:{chave_cache}"
    ja = limites.cache_get(ck)
    if ja is not None:
        return ja
    try:
        autorizar(rota, ch, custo_usd, limite_dia_rota)
    except Bloqueio as b:
        limites.registrar_uso(rota, ch, "limite" if b.status == 429 else "bloqueado")
        raise
    if not _VAGAS.acquire(blocking=False):
        limites.registrar_uso(rota, ch, "bloqueado")
        raise Bloqueio(503, "Muitas pesquisas ao mesmo tempo. Tente de novo em instantes.", 5)
    t0 = time.monotonic()
    try:
        out = chamar()
    except BaseException:
        limites.registrar_uso(rota, ch, "erro", _micro(custo_usd), int((time.monotonic() - t0) * 1000))
        raise
    finally:
        _VAGAS.release()
    limites.registrar_uso(rota, ch, "ok", _micro(custo_usd), int((time.monotonic() - t0) * 1000))
    limites.cache_set(ck, out, settings.ia_cache_segundos)
    limites.limpar_de_vez_em_quando()
    return out
