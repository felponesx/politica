"""MapBiomas Alerta: contagem pública de ALERTAS de desmatamento validados, por bioma e mês.

API GraphQL aberta (`https://plataforma.alerta.mapbiomas.org/api/v2/graphql`), conferida pelo robô em 31/10/2026: `alertStatusByBiomes` e `lastAlertPublication` respondem sem login;
as consultas com área e detalhe (`alerts`) exigem token ("Token de acesso inválido"). Esse token vem do login da conta do Felipe (`signIn`, variáveis MAPBIOMAS_EMAIL e MAPBIOMAS_SENHA); `coletar_mapbiomas_territorio`
usa-o só para os rankings agregados por estado, bioma e município (hectares por ano), nunca para dados de propriedades rurais ou de pessoas.
ATENÇÃO: alerta MapBiomas NÃO é a taxa oficial de desmatamento do PRODES/INPE. Metodologias, períodos e unidades são outros (aqui, quantidade de alertas por mês de
detecção/validação, não área nem km²). Os dois nunca são somados nem comparados no mesmo gráfico sem aviso."""
import logging
import time
from datetime import date, datetime

import httpx

from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Registro
from app.utils import NOME_PARA_UF, sem_acento, upsert

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


ANOS = range(2018, date.today().year + 1)
CAMPOS_ANOS = " ".join(f"area{a}" for a in ANOS)
TERRITORIO = ("{ alerts(limit:1,page:1){ metadata{ totalCount } summary{ total area } "
              f"rankingByState{{ state alertsTotal areaTotal {CAMPOS_ANOS} }} rankingByBiome{{ biome alertsTotal areaTotal {CAMPOS_ANOS} }} rankingByCity{{ city alertsTotal areaTotal {CAMPOS_ANOS} }} }} }}")
MAX_MUNICIPIOS = 400
AVISO_TERRITORIO = ("Alertas validados pelo MapBiomas Alerta somados por estado, bioma e município, em HECTARES por ano de detecção. NÃO é a taxa oficial do PRODES/INPE (metodologia, período e unidade diferentes): nunca somar nem misturar com o PRODES. "
                    "O ranking de municípios traz só o nome (sem o estado): nomes iguais em estados diferentes podem aparecer como um só. Dados agregados: nenhuma propriedade rural nem pessoa é coletada.")


def _post(corpo: dict, token: str | None = None, tentativas: int = 4) -> dict:
    cab = {**UA, **({"Authorization": f"Bearer {token}"} if token else {})}
    for i in range(tentativas):
        try:
            r = httpx.post(URL, json=corpo, headers=cab, timeout=httpx.Timeout(30.0, read=300.0))
            if r.status_code in (429, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if i == tentativas - 1:
                raise RuntimeError(f"MapBiomas Alerta fora do ar: {type(e).__name__}") from None   # sem `from e`: a mensagem do httpx poderia trazer o corpo do pedido
            time.sleep(5 * (i + 1))
    raise RuntimeError("inalcançável")


def entrar() -> str:
    """Login (`signIn`) com a conta das variáveis de ambiente; devolve o token. Cada login invalida o token anterior. Nunca registra e-mail, senha nem token."""
    if not settings.mapbiomas_email or not settings.mapbiomas_senha:
        raise RuntimeError("sem MAPBIOMAS_EMAIL/MAPBIOMAS_SENHA: crie a conta em plataforma.alerta.mapbiomas.org e configure as variáveis (nada foi simulado)")
    js = _post({"query": "mutation($e:String!,$p:String!){ signIn(email:$e,password:$p){ token } }", "variables": {"e": settings.mapbiomas_email, "p": settings.mapbiomas_senha}})
    tok = ((js.get("data") or {}).get("signIn") or {}).get("token")
    if not tok:
        raise RuntimeError("MapBiomas Alerta recusou o login (conta não confirmada ou senha trocada): " + str((js.get("errors") or [{}])[0].get("message"))[:100])
    return tok


def _linhas(lista: list[dict], chave: str) -> dict:
    out = {}
    for x in lista or []:
        por_ano = {str(a): round(float(x.get(f"area{a}") or 0), 1) for a in ANOS if float(x.get(f"area{a}") or 0) > 0}
        out[x[chave]] = {"alertas": int(x.get("alertasTotal", x.get("alertsTotal")) or 0), "area_ha_total": round(float(x.get("areaTotal") or 0), 1), "area_ha_por_ano": por_ano}
    return out


def resumir_territorio(d: dict) -> dict:
    a = d["alerts"]
    estados = _linhas(a["rankingByState"], "state")
    por_uf = {}
    for nome, v in estados.items():
        uf = NOME_PARA_UF.get(sem_acento(nome))
        if uf:
            por_uf[uf] = {"estado": nome, **v}
    municipios = sorted(_linhas(a["rankingByCity"], "city").items(), key=lambda kv: -kv[1]["area_ha_total"])
    anos = sorted({k for v in por_uf.values() for k in v["area_ha_por_ano"]})
    return {"total_alertas": int(a["summary"]["total"]), "area_total_ha": round(float(a["summary"]["area"]), 1), "unidade": "hectares", "anos": anos, "ano_parcial": str(date.today().year),
            "por_uf": por_uf, "por_bioma": _linhas(a["rankingByBiome"], "biome"), "n_municipios": len(municipios),
            "municipios": [{"municipio": nome, **v} for nome, v in municipios[:MAX_MUNICIPIOS]]}


def coletar_mapbiomas_territorio():
    """Alertas do MapBiomas por estado, bioma e município (hectares por ano). Exige a conta MapBiomas (login). Só grava se o retorno estiver inteiro (27 estados, 6 biomas, > 1.000 municípios);
    cada coleta fica guardada também como `snap:AAAA-MM-DD` (histórico), além de `ultimo`."""
    with registrar_coleta("mapbiomas", "alertas_territorio") as (db, n):
        js = _post({"query": TERRITORIO}, entrar())
        if js.get("errors") or not (js.get("data") or {}).get("alerts"):
            raise RuntimeError("MapBiomas Alerta: " + str((js.get("errors") or [{}])[0].get("message"))[:150])
        d = resumir_territorio(js["data"])
        if len(d["por_uf"]) < 27 or len(d["por_bioma"]) < 6 or d["n_municipios"] < 1000 or not d["total_alertas"]:
            raise RuntimeError(f"retorno incompleto ({len(d['por_uf'])} estados, {len(d['por_bioma'])} biomas, {d['n_municipios']} municípios); nada foi gravado")
        d["coletado_em"] = datetime.now().isoformat(timespec="seconds")
        for chave in ("ultimo", f"snap:{date.today().isoformat()}"):
            upsert(db, Registro, {"fonte": "mapbiomas", "tipo": "alertas_territorio", "chave": chave}, {"titulo": "Alertas de desmatamento por território (MapBiomas Alerta)", "dados": d})
        db.commit()
        n += len(d["por_uf"]) + len(d["por_bioma"]) + len(d["municipios"])
    return n.itens
