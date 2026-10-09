"""Indicadores por estado — API de agregados do IBGE (SIDRA).
Docs: https://servicodados.ibge.gov.br/api/docs/agregados?versao=3
"""
from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UF_POR_CODIGO_IBGE, para_float, upsert

BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"

# nome: (agregado, variável, descrição). Adicione novos indicadores aqui.
INDICADORES = {
    "populacao": (6579, 9324, "População residente estimada"),
    "pib": (5938, 37, "PIB a preços correntes (mil R$)"),
    "pib_per_capita": (5938, 497, "PIB per capita (R$)"),
}


def coletar_indicadores(periodos: str = "-3"):
    """periodos: '-3' = últimos 3 períodos disponíveis; ou '2021|2022'."""
    with registrar_coleta("ibge", "indicadores", periodos=periodos) as (db, n):
        for nome, (agregado, variavel, descricao) in INDICADORES.items():
            resp = http.get_json(f"{BASE}/{agregado}/periodos/{periodos}/variaveis/{variavel}",
                                 params={"localidades": "N3[all]"}) or []
            for var in resp:
                for res in var.get("resultados", []):
                    for serie in res.get("series", []):
                        uf = UF_POR_CODIGO_IBGE.get(int(serie["localidade"]["id"]))
                        for periodo, valor in (serie.get("serie") or {}).items():
                            upsert(db, Registro,
                                   {"fonte": "ibge", "tipo": f"indicador:{nome}", "chave": f"{uf}-{periodo}"},
                                   {"uf": uf, "ano": int(str(periodo)[:4]), "titulo": descricao,
                                    "valor": para_float(valor),
                                    "dados": {"unidade": var.get("unidade"), "agregado": agregado,
                                              "variavel": variavel, "periodo": periodo}})
                            n += 1
    return n.itens
