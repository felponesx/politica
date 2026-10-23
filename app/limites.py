"""Limites e contadores compartilhados entre todos os processos (workers), guardados no banco (tabela `uso_limites`).

Cada contador é uma linha (chave, janela). O gasto é um único comando SQL atômico (INSERT … ON CONFLICT DO UPDATE … WHERE
n + custo <= limite): com vários processos e pedidos simultâneos o limite nunca é ultrapassado, e reiniciar o servidor não
zera nada (está no banco). Funciona igual em PostgreSQL e SQLite (≥ 3.35).

Se o banco dos contadores falhar, `consumir` levanta `LimiteIndisponivel`; quem chama decide: a IA (que custa dinheiro)
bloqueia; o limite geral de requisições cai para um balde em memória de cada processo (continua limitado, só menos preciso).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import engine

log = logging.getLogger("brasilplus.limites")

_GASTAR = text("""
INSERT INTO uso_limites (chave, janela, n, atualizado) VALUES (:chave, :janela, :custo, :agora)
ON CONFLICT (chave, janela) DO UPDATE SET n = uso_limites.n + :custo, atualizado = :agora
WHERE uso_limites.n + :custo <= :limite
RETURNING n
""")
_LER = text("SELECT n FROM uso_limites WHERE chave = :chave AND janela = :janela")


class LimiteIndisponivel(RuntimeError):
    """O banco dos contadores não respondeu."""


@dataclass
class Resultado:
    ok: bool
    usado: int
    limite: int
    reinicia_em: int  # segundos até a janela virar

    @property
    def restante(self) -> int:
        return max(0, self.limite - self.usado)


def consumir(chave: str, limite: int, janela_s: int, custo: int = 1, agora: float | None = None) -> Resultado:
    """Gasta `custo` do contador `chave` na janela atual. ok=False quando passaria do limite (nada é gasto)."""
    t = int(time.time() if agora is None else agora)
    janela = t // janela_s
    reinicia = (janela + 1) * janela_s - t
    if custo > limite:
        return Resultado(False, 0, limite, reinicia)
    p = {"chave": chave[:160], "janela": janela, "custo": int(custo), "agora": t, "limite": int(limite)}
    try:
        with engine.begin() as c:
            linha = c.execute(_GASTAR, p).first()
            if linha is not None:
                return Resultado(True, int(linha[0]), limite, reinicia)
            atual = c.execute(_LER, p).first()
    except SQLAlchemyError as e:
        log.warning("contador de limite indisponível: %s", type(e).__name__)
        raise LimiteIndisponivel(str(type(e).__name__)) from e
    return Resultado(False, int(atual[0]) if atual else limite, limite, reinicia)


def lido(chave: str, janela_s: int) -> int:
    t = int(time.time())
    try:
        with engine.connect() as c:
            linha = c.execute(_LER, {"chave": chave[:160], "janela": t // janela_s}).first()
    except SQLAlchemyError as e:
        raise LimiteIndisponivel(str(type(e).__name__)) from e
    return int(linha[0]) if linha else 0


def limpar(antes_de_s: int = 2 * 86400) -> int:
    """Apaga contadores antigos (de uma janela que já passou há mais de `antes_de_s` segundos)."""
    try:
        with engine.begin() as c:
            return c.execute(text("DELETE FROM uso_limites WHERE atualizado < :t"), {"t": int(time.time()) - antes_de_s}).rowcount
    except SQLAlchemyError:
        return 0


def limpar_de_vez_em_quando(prob: float = 0.002) -> None:
    if random.random() < prob:
        limpar()
        cache_limpar()
        log_limpar()


def hash_cliente(ip: str) -> str:
    """Identificador curto e estável do IP, sem guardar o IP (HMAC com o token do servidor)."""
    return hmac.new(settings.admin_token.encode(), (ip or "?").encode(), hashlib.sha256).hexdigest()[:16]


# ---------- registro de uso da IA (sem pergunta nem resposta) ----------
def registrar_uso(rota: str, cliente: str, resultado: str, custo_micro_usd: int = 0, ms: int | None = None) -> None:
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO uso_ia (quando, rota, cliente, resultado, custo_micro_usd, ms) "
                           "VALUES (:q, :r, :c, :s, :u, :m)"),
                      {"q": int(time.time()), "r": rota, "c": cliente, "s": resultado, "u": int(custo_micro_usd), "m": ms})
    except SQLAlchemyError as e:  # registrar nunca pode derrubar a resposta
        log.warning("não gravou o uso da IA: %s", type(e).__name__)


def log_limpar() -> None:
    try:
        with engine.begin() as c:
            c.execute(text("DELETE FROM uso_ia WHERE quando < :t"), {"t": int(time.time()) - settings.ia_log_dias * 86400})
    except SQLAlchemyError:
        pass


def resumo_uso(dias: int = 30) -> dict:
    """Números agregados do uso da IA (para o relatório): por dia, chamadas, erros e custo estimado. Sem identificar ninguém."""
    t0 = int(time.time()) - dias * 86400
    q = text("SELECT quando, rota, resultado, custo_micro_usd FROM uso_ia WHERE quando >= :t")
    try:
        with engine.connect() as c:
            linhas = c.execute(q, {"t": t0}).all()
    except SQLAlchemyError:
        return {"disponivel": False}
    por_dia: dict[str, dict] = {}
    for quando, rota, resultado, micro in linhas:
        dia = time.strftime("%Y-%m-%d", time.gmtime(quando))
        d = por_dia.setdefault(dia, {"dia": dia, "chamadas": 0, "ok": 0, "erros": 0, "bloqueadas": 0, "custo_usd": 0.0})
        d["chamadas"] += resultado in ("ok", "erro")
        d["ok"] += resultado == "ok"
        d["erros"] += resultado == "erro"
        d["bloqueadas"] += resultado in ("limite", "bloqueado")
        d["custo_usd"] = round(d["custo_usd"] + (micro or 0) / 1e6, 4)
    dias_l = sorted(por_dia.values(), key=lambda x: x["dia"], reverse=True)
    hoje = time.strftime("%Y-%m-%d", time.gmtime())
    gasto_hoje = next((d["custo_usd"] for d in dias_l if d["dia"] == hoje), 0.0)
    return {"disponivel": True, "dias": dias_l, "gasto_hoje_usd": gasto_hoje,
            "orcamento_dia_usd": settings.ia_orcamento_dia_usd,
            "limites": {"por_ip_minuto": settings.limite_ia_ip_minuto, "por_ip_dia": settings.limite_ia_ip_dia,
                        "global_minuto": settings.limite_ia_global_minuto, "perguntas_dia": settings.perplexity_limite_dia,
                        "buscas_dia": settings.perplexity_busca_limite_dia},
            "aviso": "Custo estimado por chamada (não é a fatura do provedor); o teto real deve ser configurado também no painel do provedor."}


# ---------- cache compartilhado ----------
def _chave_cache(chave: str) -> str:
    return hashlib.sha256(chave.encode()).hexdigest()


def cache_get(chave: str):
    try:
        with engine.connect() as c:
            linha = c.execute(text("SELECT valor FROM cache_ia WHERE chave = :k AND expira > :t"),
                              {"k": _chave_cache(chave), "t": int(time.time())}).first()
    except SQLAlchemyError:
        return None
    try:
        return json.loads(linha[0]) if linha else None
    except ValueError:
        return None


def cache_set(chave: str, valor, segundos: int) -> None:
    if segundos <= 0:
        return
    p = {"k": _chave_cache(chave), "v": json.dumps(valor, ensure_ascii=False), "e": int(time.time()) + segundos}
    try:
        with engine.begin() as c:
            c.execute(text("INSERT INTO cache_ia (chave, valor, expira) VALUES (:k, :v, :e) "
                           "ON CONFLICT (chave) DO UPDATE SET valor = :v, expira = :e"), p)
    except SQLAlchemyError as e:
        log.warning("não gravou o cache da IA: %s", type(e).__name__)


def cache_limpar() -> None:
    try:
        with engine.begin() as c:
            c.execute(text("DELETE FROM cache_ia WHERE expira < :t"), {"t": int(time.time())})
    except SQLAlchemyError:
        pass
