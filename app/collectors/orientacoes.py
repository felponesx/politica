"""Orientação de bancada nas votações da Câmara (arquivos anuais completos de dados abertos).

`https://dadosabertos.camara.leg.br/arquivos/votacoesOrientacoes/json/votacoesOrientacoes-AAAA.json` (a rota `/votacoes/{id}/orientacoes`
vem vazia nas votações recentes). Uma linha por votação e bancada (partido, bloco, federação, Governo, Maioria, Minoria, Oposição). Orientação vazia
= sem orientação registrada, NÃO é liberação (liberação vem escrita "Liberado"). O ano corrente é sempre refeito; anos fechados só se faltarem."""
import logging
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.orientacoes")
URL = "https://dadosabertos.camara.leg.br/arquivos/votacoesOrientacoes/json/votacoesOrientacoes-{ano}.json"
MINIMO = {True: 50}   # votações mínimas no ano corrente (guarda contra arquivo cortado)


def agrupar(linhas: list[dict]) -> dict[str, dict]:
    """{idVotacao: {orgao, descricao, bancadas: {bancada: orientação ('' = sem orientação registrada)}}}"""
    out: dict[str, dict] = {}
    for l in linhas:
        vid = str(l.get("idVotacao") or "").strip()
        banc = str(l.get("siglaBancada") or "").strip()
        if not vid or not banc:
            continue
        e = out.setdefault(vid, {"orgao": l.get("siglaOrgao"), "descricao": (l.get("descricao") or "")[:400], "bancadas": {}})
        e["bancadas"][banc] = str(l.get("orientacao") or "").strip()
    return out


def coletar_camara_orientacoes(ano_inicial: int = 0, ano_final: int = 0):
    """Orientações por votação do ano corrente (e de `ano_inicial` até `ano_final`, quando pedidos; anos já gravados não voltam a ser baixados)."""
    with registrar_coleta("camara", "orientacoes") as (db, n):
        hoje = date.today().year
        fim = int(ano_final) or hoje
        ini = int(ano_inicial) or hoje
        for ano in range(ini, fim + 1):
            if ano < hoje and db.query(Registro).filter_by(fonte="camara", tipo="orientacao", ano=ano).first():
                continue
            try:
                dados = http.get_json(URL.format(ano=ano))
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"{ano}: {type(e).__name__}: {str(e)[:120]}")
                continue
            linhas = (dados or {}).get("dados") or []
            por_votacao = agrupar(linhas)
            if ano == hoje and len(por_votacao) < MINIMO[True]:
                raise RuntimeError(f"orientações {ano}: só {len(por_votacao)} votações (esperado ≥ {MINIMO[True]}); nada foi gravado")
            if not por_votacao:
                n.avisos.append(f"{ano}: arquivo sem orientações")
                continue
            for vid, e in por_votacao.items():
                upsert(db, Registro, {"fonte": "camara", "tipo": "orientacao", "chave": vid},
                       {"ano": ano, "titulo": f"Orientações da votação {vid}", "dados": e})
                n += 1
            db.commit()
        if not n.itens and not n.avisos:
            log.info("orientações: nada novo")
    return n.itens
