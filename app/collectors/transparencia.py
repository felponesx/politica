"""Portal da Transparência do Governo Federal (CGU) — exige chave gratuita.
Docs: https://api.portaldatransparencia.gov.br/swagger-ui/index.html
Cadastro da chave: https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email

Limite: ~90 req/min (dia) e ~300 req/min (madrugada). O sleep abaixo respeita isso.
"""
import time
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Registro
from app.utils import hash_curto, meses, para_float, primeiro, upsert

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"


def _headers():
    if not settings.transparencia_api_key:
        raise RuntimeError("Defina TRANSPARENCIA_API_KEY no .env (cadastro gratuito no Portal da Transparência).")
    return {"chave-api-dados": settings.transparencia_api_key}


def paginar(caminho: str, params: dict):
    pagina = 1
    while True:
        lote = http.get_json(f"{BASE}{caminho}", params={**params, "pagina": pagina}, headers=_headers()) or []
        if not lote:
            break
        yield from lote
        pagina += 1
        time.sleep(0.7)


def coletar_orgaos():
    with registrar_coleta("transparencia", "orgaos_siafi") as (db, n):
        for o in paginar("/orgaos-siafi", {}):
            upsert(db, Registro, {"fonte": "transparencia", "tipo": "orgao", "chave": str(o.get("codigo"))},
                   {"titulo": o.get("descricao"), "dados": o})
            n += 1
    return n.itens


def coletar_contratos(codigo_orgao: str, inicio: date, fim: date):
    """Contratos federais de um órgão SIAFI (ex.: 26000 = Ministério da Educação)."""
    with registrar_coleta("transparencia", "contratos", orgao=codigo_orgao, inicio=inicio, fim=fim) as (db, n):
        for ini, f in meses(inicio, fim):
            for c in paginar("/contratos", {"codigoOrgao": codigo_orgao,
                                            "dataInicial": f"{ini:%d/%m/%Y}", "dataFinal": f"{f:%d/%m/%Y}"}):
                upsert(db, Registro, {"fonte": "transparencia", "tipo": "contrato", "chave": str(c.get("id"))}, {
                    "ano": ini.year, "titulo": c.get("objeto"),
                    "valor": para_float(primeiro(c, "valorFinalCompra", "valorInicialCompra")), "dados": c,
                })
                n += 1
            db.commit()
    return n.itens


def coletar_gastos_por_orgao(ano: int, orgao_superior: str):
    """Despesas executadas (empenhado/liquidado/pago) por órgão."""
    with registrar_coleta("transparencia", "gastos_orgao", ano=ano, orgao=orgao_superior) as (db, n):
        for d in paginar("/despesas/por-orgao", {"ano": ano, "orgaoSuperior": orgao_superior}):
            chave = hash_curto(ano, d.get("codigoOrgaoSuperior"), d.get("codigoOrgao"))
            upsert(db, Registro, {"fonte": "transparencia", "tipo": "gasto_orgao", "chave": chave}, {
                "ano": ano, "titulo": primeiro(d, "orgao", "orgaoSuperior"),
                "valor": para_float(d.get("pago")), "dados": d,
            })
            n += 1
    return n.itens


def coletar_gastos_todos_orgaos(ano: int):
    """Despesas de todos os órgãos superiores (ministérios etc.). Coleta a lista de órgãos antes, se faltar."""
    from sqlalchemy import select

    from app.db import SessionLocal
    db = SessionLocal()
    try:
        codigos = [c for (c,) in db.execute(select(Registro.chave).where(
            Registro.fonte == "transparencia", Registro.tipo == "orgao"))]
    finally:
        db.close()
    if not codigos:
        coletar_orgaos()
        return coletar_gastos_todos_orgaos(ano)
    total = 0
    for cod in sorted(c for c in codigos if len(c) == 5 and c.endswith("000")):
        try:
            total += coletar_gastos_por_orgao(ano, cod)
        except Exception as e:  # órgão sem despesa no ano responde erro: segue para o próximo
            import logging
            logging.getLogger("brasilplus.transparencia").warning("Órgão %s sem despesas em %s: %s", cod, ano, e)
    return total
