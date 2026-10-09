"""Transferências constitucionais e legais da União — API do Tesouro Nacional.
Base: https://apiapex.tesouro.gov.br/aria/v1/transferencias_constitucionais/custom
Metadados: dataset "API Transferências Constitucionais" no Tesouro Transparente.

Os parâmetros usam códigos internos do Tesouro (NÃO são códigos IBGE);
por isso buscamos /estados e /transferencias primeiro. Múltiplos valores são separados por ':'.
"""
from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import hash_curto, para_float, para_mes, para_uf, primeiro, upsert

BASE = "https://apiapex.tesouro.gov.br/aria/v1/transferencias_constitucionais/custom"


def _itens(caminho: str, params: dict | None = None):
    """Lida com lista simples, {"registros": [...], "status": "ok"} (formato real) ou ORDS ({items, hasMore})."""
    offset = 0
    while True:
        resp = http.get_json(f"{BASE}/{caminho}", params={**(params or {}), **({"offset": offset} if offset else {})})
        if isinstance(resp, list):
            yield from resp
            return
        itens = (resp or {}).get("registros") or (resp or {}).get("items") or []
        yield from itens
        if not (resp or {}).get("hasMore") or not itens:
            return
        offset += len(itens)


def codigos_estados() -> dict[str, str]:
    """{UF: código Tesouro}"""
    out = {}
    for e in _itens("estados"):
        uf = para_uf(primeiro(e, "sigla", "uf")) or para_uf(primeiro(e, "nome", "descricao"))
        if uf:
            out[uf] = str(primeiro(e, "codigo", "id"))
    return out


def codigos_transferencias() -> dict[str, str]:
    """{código: nome}"""
    return {str(primeiro(t, "codigo", "id")): primeiro(t, "nome", "transferencia", "descricao")
            for t in _itens("transferencias")}


def coletar_transferencias(ano: int):
    """Repasses mensais por UF: aos governos estaduais (por tipo) e à soma dos municípios de cada UF."""
    with registrar_coleta("tesouro", "transferencias", ano=ano) as (db, n):
        estados = codigos_estados()
        transf = codigos_transferencias()
        base = {"p_ano": ano, "p_estado": ":".join(estados.values()), "p_transferencia": ":".join(transf)}

        for item in _itens("por_estados", base):
            uf = para_uf(primeiro(item, "uf", "sigla_uf", "estado"))
            mes = para_mes(primeiro(item, "mes", "mes_referencia") or 0)
            nome = primeiro(item, "transferencia", "nome_transferencia") or "?"
            upsert(db, Registro, {"fonte": "tesouro", "tipo": "transf_estado",
                                  "chave": hash_curto(uf, ano, mes, nome)}, {
                "uf": uf, "ano": ano, "titulo": nome, "valor": para_float(item.get("valor")),
                "dados": {**item, "mes": mes},
            })
            n += 1
        db.commit()

        for item in _itens("por_estado_municipio", base):
            uf = para_uf(primeiro(item, "uf", "sigla_uf", "estado"))
            mes = para_mes(primeiro(item, "mes", "mes_referencia") or 0)
            # pode vir uma linha por município: a chave inclui o município para não sobrescrever
            municipio = primeiro(item, "co_ibge", "co_siafi", "municipio")
            upsert(db, Registro, {"fonte": "tesouro", "tipo": "transf_municipios",
                                  "chave": hash_curto(uf, ano, mes, municipio, primeiro(item, "transferencia") or "total")}, {
                "uf": uf, "ano": ano, "titulo": primeiro(item, "municipio") or "Soma dos municípios",
                "valor": para_float(item.get("valor")),
                "dados": {**item, "mes": mes},
            })
            n += 1
    return n.itens
