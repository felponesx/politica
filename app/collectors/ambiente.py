"""Desmatamento (INPE PRODES, taxa anual por estado e bioma) e alertas recentes (INPE DETER) pelo serviço WFS do TerraBrasilis.

PRODES: uma camada por bioma (`prodes-<bioma>-nb:yearly_deforestation`), cada feição é um polígono de desmatamento com `state`, `year` e `area_km`; somamos por estado e ano.
Os seis biomas não se sobrepõem (Amazônia pelo bioma, não pela Amazônia Legal), então podem ser somados por estado. DETER: alertas mensais de desmatamento e degradação na Amazônia e no Cerrado.
O WFS não soma por conta própria: lemos as feições em páginas de 100 mil (CSV só com as colunas necessárias)."""
import csv
import io
import logging
import re
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import NOME_PARA_UF, UFS, sem_acento, upsert

log = logging.getLogger("brasilplus.ambiente")
WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
PAGINA = 50_000   # o servidor limita cada resposta a 50 mil feições (pedir mais devolve só 50 mil)
PRIMEIRO_ANO = 2008
BIOMAS = {"amazonia": ("Amazônia", "prodes-amazon-nb:yearly_deforestation_biome"), "cerrado": ("Cerrado", "prodes-cerrado-nb:yearly_deforestation"),
          "caatinga": ("Caatinga", "prodes-caatinga-nb:yearly_deforestation"), "mata_atlantica": ("Mata Atlântica", "prodes-mata-atlantica-nb:yearly_deforestation"),
          "pantanal": ("Pantanal", "prodes-pantanal-nb:yearly_deforestation"), "pampa": ("Pampa", "prodes-pampa-nb:yearly_deforestation")}
DETER = {"amazonia": ("Amazônia", "deter-amz:deter_amz"), "cerrado": ("Cerrado", "deter-cerrado-nb:deter_cerrado")}


def uf_de(txt) -> str | None:
    t = str(txt or "").strip()
    if t.upper() in UFS:
        return t.upper()
    return NOME_PARA_UF.get(sem_acento(t))


def _pedido(params: dict):
    """GET no WFS; em erro 400 a mensagem do servidor (XML de exceção) entra no erro para facilitar o diagnóstico."""
    import httpx
    try:
        return http.get(WFS, params=params, headers={"Accept": "*/*"})
    except httpx.HTTPStatusError as e:
        corpo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", e.response.text or ""))[:220]
        raise RuntimeError(f"HTTP {e.response.status_code} do WFS: {corpo}") from e


def total_feicoes(camada: str, filtro: str | None = None) -> int:
    """Número exato de feições da camada (resultType=hits), para conferir que a leitura paginada veio inteira."""
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada, "resultType": "hits"}
    if filtro:
        params["cql_filter"] = filtro
    m = re.search(r'numberMatched="(\d+)"', _pedido(params).text)
    if not m:
        raise RuntimeError("o WFS não informou numberMatched")
    return int(m.group(1))


def paginas(camada: str, propriedades: str, filtro: str | None = None, ordem: str = "fid"):
    """Gera as linhas (dict) do CSV do WFS, página a página (ordenadas para a paginação não repetir nem pular).
    Se o servidor falhar com 5xx numa página grande (acontece nas camadas de milhões de feições), repete com a metade do tamanho."""
    inicio, tamanho = 0, PAGINA
    while True:
        params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada, "outputFormat": "csv", "propertyName": propriedades,
                  "sortBy": ordem, "count": tamanho, "startIndex": inicio}
        if filtro:
            params["cql_filter"] = filtro
        try:
            texto = _pedido(params).text
        except RuntimeError as e:
            if re.search(r"HTTP 5\d\d", str(e)) and tamanho > 6_000:
                tamanho //= 2
                log.warning("WFS %s: %s; tentando páginas de %s", camada, str(e)[:80], tamanho)
                continue
            raise
        linhas = list(csv.DictReader(io.StringIO(texto)))
        yield from linhas
        if len(linhas) < tamanho:
            return
        inicio += len(linhas)


def somar_prodes(linhas) -> tuple[dict, int]:
    """({UF: {ano: km²}}, nº de feições lidas) só de polígonos de desmatamento a partir de PRIMEIRO_ANO."""
    por_uf: dict[str, dict] = {}
    n = 0
    for l in linhas:
        n += 1
        if str(l.get("main_class", "")).strip().lower() != "desmatamento":
            continue
        uf = uf_de(l.get("state"))
        try:
            ano, km = int(float(l["year"])), float(l["area_km"])
        except (KeyError, ValueError, TypeError):
            continue
        if not uf or ano < PRIMEIRO_ANO:
            continue
        por_uf.setdefault(uf, {})
        por_uf[uf][str(ano)] = por_uf[uf].get(str(ano), 0.0) + km
    return {u: {a: round(v, 2) for a, v in sorted(s.items())} for u, s in por_uf.items()}, n


def somar_deter(linhas) -> dict:
    """{UF: {AAAA-MM: {desmatamento, degradacao}}} em km²; 'DESMATAMENTO*' é desmatamento e o resto (degradação, cicatriz de queimada, mineração...) vai em degradação."""
    out: dict[str, dict] = {}
    for l in linhas:
        uf = uf_de(l.get("uf"))
        mes = str(l.get("view_date", ""))[:7]
        try:
            km = float(l.get("areamunkm") or 0)
        except ValueError:
            continue
        if not uf or len(mes) != 7:
            continue
        e = out.setdefault(uf, {}).setdefault(mes, {"desmatamento": 0.0, "degradacao": 0.0})
        e["desmatamento" if str(l.get("classname", "")).upper().startswith("DESMATAMENTO") else "degradacao"] += km
    return {u: {m: {k: round(v, 2) for k, v in e.items()} for m, e in sorted(s.items())} for u, s in out.items()}


def coletar_desmatamento():
    """PRODES por bioma e estado desde 2008 e alertas DETER dos últimos 24 meses."""
    with registrar_coleta("inpe", "desmatamento") as (db, n):
        for chave, (nome, camada) in BIOMAS.items():
            try:
                esperado = total_feicoes(camada)
                por_uf, feicoes = somar_prodes(paginas(camada, "state,year,area_km,main_class"))
                if feicoes < esperado * 0.99 or not por_uf:
                    raise RuntimeError(f"leu {feicoes:,} de {esperado:,} feições; nada foi gravado")
                anos = sorted({a for s in por_uf.values() for a in s})
                total = {a: round(sum(s.get(a, 0) for s in por_uf.values()), 2) for a in anos}
                upsert(db, Registro, {"fonte": "inpe", "tipo": "prodes_bioma", "chave": chave},
                       {"titulo": f"PRODES {nome}", "dados": {"bioma": nome, "camada": camada, "ultimo_ano": anos[-1], "por_uf": por_uf, "total": total, "feicoes": feicoes}})
                db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001 - um bioma que falha não derruba os outros
                n.avisos.append(f"PRODES {nome}: {type(e).__name__}: {str(e)[:150]}")
                log.warning("PRODES %s: %s", nome, e)
        desde = date.today().replace(day=1)
        desde = date(desde.year - 2, desde.month, 1)
        for chave, (nome, camada) in DETER.items():
            try:
                filtro = f"view_date >= '{desde.isoformat()}'"
                esperado = total_feicoes(camada, filtro)
                linhas = list(paginas(camada, "uf,areamunkm,classname,view_date", filtro))
                if len(linhas) < esperado * 0.99:
                    raise RuntimeError(f"leu {len(linhas):,} de {esperado:,} alertas; nada foi gravado")
                por_uf = somar_deter(linhas)
                if not por_uf:
                    raise RuntimeError("nenhum alerta no período")
                upsert(db, Registro, {"fonte": "inpe", "tipo": "deter_bioma", "chave": chave},
                       {"titulo": f"DETER {nome}", "dados": {"bioma": nome, "camada": camada, "desde": desde.isoformat(), "por_uf": por_uf}})
                db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"DETER {nome}: {type(e).__name__}: {str(e)[:150]}")
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhuma camada foi lida")
    return n.itens
