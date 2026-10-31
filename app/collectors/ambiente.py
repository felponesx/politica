"""Desmatamento (INPE PRODES, taxa anual por estado e bioma) e alertas recentes (INPE DETER) pelo serviço WFS do TerraBrasilis.

PRODES: uma camada por bioma (`prodes-<bioma>-nb:yearly_deforestation`), cada feição é um polígono de desmatamento com `state`, `year` e `area_km`; somamos por estado e ano.
Os seis biomas não se sobrepõem (Amazônia pelo bioma, não pela Amazônia Legal), então podem ser somados por estado. DETER: alertas mensais de desmatamento e degradação na Amazônia e no Cerrado.
O WFS não soma por conta própria: lemos as feições em páginas de 100 mil (CSV só com as colunas necessárias)."""
import csv
import sys
import io
import logging
import re
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import NOME_PARA_UF, UFS, sem_acento, upsert

csv.field_size_limit(sys.maxsize)   # a coluna de geometria do WFS passa de 131 mil caracteres (o Pantanal falhou por isso)
log = logging.getLogger("brasilplus.ambiente")
WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
PAGINA = 50_000   # o servidor limita cada resposta a 50 mil feições (pedir mais devolve só 50 mil)
PRIMEIRO_ANO = 2008
BIOMAS = {"amazonia": ("Amazônia", "prodes-amazon-nb:yearly_deforestation_biome"), "cerrado": ("Cerrado", "prodes-cerrado-nb:yearly_deforestation"),
          "caatinga": ("Caatinga", "prodes-caatinga-nb:yearly_deforestation"), "mata_atlantica": ("Mata Atlântica", "prodes-mata-atlantica-nb:yearly_deforestation"),
          "pantanal": ("Pantanal", "prodes-pantanal-nb:yearly_deforestation"), "pampa": ("Pampa", "prodes-pampa-nb:yearly_deforestation")}
POR_ARQUIVO = {"mata_atlantica"}   # o WFS recusa as colunas e derruba a camada: vem pelo shapefile (tarefa inpe-prodes-mata-atlantica, app/collectors/prodes_mata.py)
SEM_MAIN_CLASS = {"cerrado", "caatinga"}   # essas camadas só têm state, year e area_km (pedir main_class dá erro 400)
SEM_FILTRO_DE_COLUNAS = {"pantanal"}   # o GeoServer recusa propertyName + sortBy nesta camada (erro 400); ela é pequena
DETER = {"amazonia": ("Amazônia", "deter-amz:deter_amz"), "cerrado": ("Cerrado", "deter-cerrado-nb:deter_cerrado")}


def uf_de(txt) -> str | None:
    t = str(txt or "").strip()
    if t.upper() in UFS:
        return t.upper()
    return NOME_PARA_UF.get(sem_acento(t))


def _endereco(params: dict) -> str:
    """Cerrado, Caatinga e Mata Atlântica respondem melhor pelo endereço do próprio bioma (`/geoserver/<área>/ows`) que pelo geral, que dá 502."""
    camada = str(params.get("typeNames") or params.get("typeName", ""))
    return f"https://terrabrasilis.dpi.inpe.br/geoserver/{camada.split(':')[0]}/ows" if camada.startswith("prodes-") and "amazon" not in camada else WFS


def _pedido(params: dict):
    """GET no WFS; em erro 400 a mensagem do servidor (XML de exceção) entra no erro para facilitar o diagnóstico."""
    import httpx
    try:
        return http.get(_endereco(params), params=params, headers={"Accept": "*/*"}, timeout=600)
    except httpx.HTTPStatusError as e:
        corpo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", e.response.text or ""))[:220]
        raise RuntimeError(f"HTTP {e.response.status_code} do WFS: {corpo}") from e


def total_feicoes(camada: str, filtro: str | None = None) -> int:
    """Número exato de feições da camada (resultType=hits), para conferir que a leitura paginada veio inteira."""
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada, "resultType": "hits"}
    if filtro:
        params["cql_filter"] = filtro
    m = re.search(r'(?:numberMatched|numberOfFeatures)="(\d+)"', _pedido(params).text)
    if not m:
        raise RuntimeError("o WFS não informou numberMatched")
    return int(m.group(1))


def paginas(camada: str, propriedades: str, filtro: str | None = None, ordem: str = "fid"):
    """Gera as linhas (dict) do CSV do WFS, página a página (ordenadas para a paginação não repetir nem pular).
    Se o servidor falhar com 5xx numa página grande (acontece nas camadas de milhões de feições), repete com a metade do tamanho."""
    inicio, tamanho = 0, PAGINA
    v1 = camada.split(":")[0].replace("prodes-", "").replace("-nb", "").replace("-", "_") in SEM_MAIN_CLASS   # Cerrado/Caatinga: só o WFS 1.0.0 pagina sem erro (a ordem é a da chave primária)
    while True:
        params = ({"service": "WFS", "version": "1.0.0", "request": "GetFeature", "typeName": camada, "outputFormat": "csv", "maxFeatures": tamanho, "startIndex": inicio} if v1 else
                  {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada, "outputFormat": "csv", "count": tamanho, "startIndex": inicio})
        if propriedades:
            params["propertyName"] = propriedades
        if ordem and not v1:
            params["sortBy"] = ordem
        if filtro:
            params["cql_filter"] = filtro
        try:
            texto = _pedido(params).text
        except RuntimeError as e:
            if "HTTP 400" in str(e) and ordem:   # o GeoServer recusa propertyName + sortBy em algumas camadas: segue sem ordenar (a contagem exata confere no fim)
                log.warning("WFS %s: %s; tentando sem sortBy", camada, str(e)[:80])
                ordem = None
                continue
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
        classe = str(l.get("main_class", "desmatamento")).strip().lower()   # Cerrado e Caatinga não trazem a coluna: toda feição é desmatamento
        if classe != "desmatamento":
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


def coletar_desmatamento(biomas: str = "", deter: bool = True):
    """PRODES por bioma e estado desde 2008 e alertas DETER dos últimos 24 meses. `biomas` = lista separada por vírgula (vazio = todos); `deter=false` pula os alertas.
    Camadas gigantes (Cerrado, Caatinga) e a Mata Atlântica vão melhor uma por vez; o Pantanal (camada pequena) é lido sem filtro de colunas, que o servidor recusa."""
    quer = {b.strip() for b in str(biomas).split(",") if b.strip()}
    deter = str(deter).lower() not in ("false", "0", "nao", "não")
    with registrar_coleta("inpe", "desmatamento") as (db, n):
        for chave, (nome, camada) in BIOMAS.items():
            if quer and chave not in quer:
                continue
            if chave in POR_ARQUIVO:
                if quer:
                    n.avisos.append(f"PRODES {nome}: use a tarefa inpe-prodes-mata-atlantica (shapefile oficial); o WFS não serve para esta camada")
                continue
            try:
                esperado = total_feicoes(camada)
                por_uf, feicoes = somar_prodes(paginas(camada, None if chave in SEM_FILTRO_DE_COLUNAS else ("state,year,area_km" if chave in SEM_MAIN_CLASS else "state,year,area_km,main_class"), ordem=None if chave in SEM_FILTRO_DE_COLUNAS else "fid"))
                if not esperado * 0.99 <= feicoes <= esperado * 1.01 or not por_uf:
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
        for chave, (nome, camada) in (DETER.items() if deter else ()):
            try:
                filtro = f"view_date >= '{desde.isoformat()}'"
                esperado = total_feicoes(camada, filtro)
                linhas = list(paginas(camada, "uf,areamunkm,classname,view_date", filtro))
                if not esperado * 0.99 <= len(linhas) <= esperado * 1.01:
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
