"""MapBiomas Alerta: contagem pública de ALERTAS de desmatamento validados, por bioma e mês.

API GraphQL aberta (`https://plataforma.alerta.mapbiomas.org/api/v2/graphql`), conferida pelo robô em 31/10/2026: `alertStatusByBiomes` e `lastAlertPublication` respondem sem login;
as consultas com área e detalhe (`alerts`) exigem token ("Token de acesso inválido") e NÃO são usadas aqui.
ATENÇÃO: alerta MapBiomas NÃO é a taxa oficial de desmatamento do PRODES/INPE. Metodologias, períodos e unidades são outros (aqui, quantidade de alertas por mês de
detecção/validação, não área nem km²). Os dois nunca são somados nem comparados no mesmo gráfico sem aviso."""
import logging
import time
from datetime import datetime

import httpx

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.mapbiomas")
URL = "https://plataforma.alerta.mapbiomas.org/api/v2/graphql"
UA = {"User-Agent": "BRASIL+ coletor de dados publicos (github.com/felponesx/politica)", "Content-Type": "application/json"}
BIOMAS = {"Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"}
CONSULTA = "{ alertStatusByBiomes { biome total totalProcessed totalNotprocessed yearMonth } lastAlertPublication { publishedAt total publicationRange } }"


def consultar(tentativas: int = 4) -> dict:
    for i in range(tentativas):
        try:
            r = httpx.post(URL, json={"query": CONSULTA}, headers=UA, timeout=60)
            if r.status_code in (429, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            js = r.json()
            if js.get("errors"):
                raise RuntimeError("MapBiomas Alerta: " + str(js["errors"][0].get("message"))[:150])
            return js["data"]
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if i == tentativas - 1:
                raise
            time.sleep(5 * (i + 1))
    raise RuntimeError("inalcançável")


def resumir(dados: dict) -> dict:
    por_bioma: dict[str, dict] = {}
    for x in dados.get("alertStatusByBiomes") or []:
        if x.get("biome") in BIOMAS and x.get("yearMonth"):
            por_bioma.setdefault(x["biome"], {})[x["yearMonth"]] = {"total": x["total"], "processados": x["totalProcessed"], "nao_processados": x["totalNotprocessed"]}
    meses = sorted({m for v in por_bioma.values() for m in v})
    por_ano: dict[str, dict] = {}
    for b, v in por_bioma.items():
        for m, x in v.items():
            por_ano.setdefault(b, {}).setdefault(m[:4], 0)
            por_ano[b][m[:4]] += x["total"]
    pub = dados.get("lastAlertPublication") or {}
    return {"por_bioma_mes": por_bioma, "por_bioma_ano": por_ano, "primeiro_mes": meses[0] if meses else None, "ultimo_mes": meses[-1] if meses else None,
            "ultima_publicacao": {"publicado_em": pub.get("publishedAt"), "alertas": pub.get("total"), "periodo": pub.get("publicationRange")}}


def coletar_mapbiomas_alertas():
    with registrar_coleta("mapbiomas", "alertas_bioma") as (db, n):
        d = resumir(consultar())
        if len(d["por_bioma_mes"]) < 6 or not d["ultimo_mes"]:
            raise RuntimeError(f"MapBiomas Alerta: vieram {len(d['por_bioma_mes'])} biomas (esperado 6); nada foi gravado")
        d["coletado_em"] = datetime.now().isoformat(timespec="seconds")
        upsert(db, Registro, {"fonte": "mapbiomas", "tipo": "alertas_bioma", "chave": "ultimo"}, {"titulo": "Alertas de desmatamento por bioma (MapBiomas Alerta)", "dados": d})
        db.commit()
        n += sum(len(v) for v in d["por_bioma_mes"].values())
    return n.itens
