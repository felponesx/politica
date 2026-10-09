"""Contratos públicos (União, estados e municípios) — Portal Nacional de Contratações Públicas.
Docs: https://pncp.gov.br/api/consulta/swagger-ui/index.html
"""
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import cavar, meses, para_float, upsert

BASE = "https://pncp.gov.br/api/consulta/v1"


def coletar_contratos(inicio: date, fim: date, tamanho_pagina: int = 500):
    with registrar_coleta("pncp", "contratos", inicio=inicio, fim=fim) as (db, n):
        for ini, f in meses(inicio, fim):
            pagina = 1
            while True:
                resp = http.get_json(f"{BASE}/contratos", params={
                    "dataInicial": f"{ini:%Y%m%d}", "dataFinal": f"{f:%Y%m%d}",
                    "pagina": pagina, "tamanhoPagina": tamanho_pagina,
                }) or {}
                for c in resp.get("data", []):
                    chave = c.get("numeroControlePNCP") or c.get("numeroControlePncpCompra")
                    if not chave:
                        continue
                    upsert(db, Registro, {"fonte": "pncp", "tipo": "contrato", "chave": chave}, {
                        "uf": cavar(c, "unidadeOrgao", "ufSigla"),
                        "ano": int(c.get("anoContrato") or str(c.get("dataAssinatura") or ini.year)[:4]),
                        "titulo": c.get("objetoContrato"),
                        "valor": para_float(c.get("valorGlobal") or c.get("valorInicial")),
                        "dados": c,
                    })
                    n += 1
                db.commit()
                total = resp.get("totalPaginas") or 0
                if pagina >= total or not resp.get("data"):
                    break
                pagina += 1
    return n.itens
