"""Malha viária das capitais a partir do extrato do OpenStreetMap da Geofabrik (OSM PBF) — o caminho preferido para a coleta nacional recorrente.

Por quê: o Overpass público é uma fila compartilhada (30–45 s numa consulta mínima, 504 em horário cheio, espelhos com base velha); o extrato do Brasil é um arquivo (2,1 GB) que a
Geofabrik atualiza todo dia, baixa-se uma vez, confere-se com o .md5 e processa-se sem depender de ninguém. Para não carregar o país inteiro, usa-se o extrato da REGIÃO da capital
(norte, nordeste, centro-oeste, sudeste, sul) quando a Geofabrik o oferece; senão o nacional.

Como: download em streaming com retomada (`app/downloads.py`) + conferência do MD5; leitura em um só passe com pyosmium (`FileProcessor`, só ways com `highway`, localização dos nós em memória);
o limite do município vem da malha oficial do IBGE (maior qualidade) ou, se o IBGE não responde (aconteceu no robô em 31/10/2026), da relação do município no OSM, e fica guardado no banco; cada via é atribuída ao município que contém o PONTO DO MEIO dela (o Overpass usa outro critério na divisa, por isso
os dois métodos podem diferir pouco; o registro diz qual foi usado). Comprimento = distância de haversine entre os nós, via inteira. Carimbo da base = `osmosis_replication_timestamp` do cabeçalho."""
import logging
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from app import http
from app.collectors.base import registrar_coleta
from app.collectors.osm_malha import juntar_partes, resumir_parte
from app.collectors.transito import CAPITAIS, EXCLUIDAS, MINIMO_KM, MINIMO_KM_PADRAO, _lista_ufs
from app.downloads import baixar, md5
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.osm_pbf")
GEOFABRIK = "https://download.geofabrik.de/south-america"
IBGE_MALHA = "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/{ibge}"
REGIAO = {**{u: "norte" for u in ("AC", "AP", "AM", "PA", "RO", "RR", "TO")}, **{u: "nordeste" for u in ("AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE")},
          **{u: "centro-oeste" for u in ("DF", "GO", "MT", "MS")}, **{u: "sudeste" for u in ("ES", "MG", "RJ", "SP")}, **{u: "sul" for u in ("PR", "RS", "SC")}}
NACIONAL = f"{GEOFABRIK}/brazil-latest.osm.pbf"
VALIDADE_DIAS = 25
_EXCL = set(EXCLUIDAS.split("|"))
AVISO = ("Quilômetros de via por capital a partir do OpenStreetMap (extrato da Geofabrik): base colaborativa, não oficial. Cada via é atribuída ao município que contém o ponto do meio dela; "
         "a via inteira é contada. Não mede trânsito nem estado de conservação.")


def pasta_destino() -> Path:
    p = Path(os.environ.get("OSM_DIR") or Path(tempfile.gettempdir()) / "brasilplus_osm")
    p.mkdir(parents=True, exist_ok=True)
    return p


def url_extrato(regiao: str) -> str:
    return f"{GEOFABRIK}/brazil/{regiao}-latest.osm.pbf"


def escolher_extrato(regiao: str) -> str:
    """O extrato regional se a Geofabrik o publica (HEAD 200); senão o nacional. Falha de rede não é "não existe": repete."""
    for _ in range(3):
        try:
            r = http._cliente.head(url_extrato(regiao), headers={"Accept": "*/*"}, timeout=60)
            if r.status_code == 200:
                return url_extrato(regiao)
            if r.status_code == 404:
                break
        except httpx.HTTPError:
            pass
    return NACIONAL


def md5_oficial(url: str) -> str | None:
    try:
        m = re.match(r"([0-9a-f]{32})", http.get(url + ".md5", headers={"Accept": "*/*"}, timeout=60).text.strip())
        return m.group(1) if m else None
    except Exception as e:  # noqa: BLE001
        log.warning("não li o .md5 de %s: %s", url, type(e).__name__)
        return None


def limite_ibge(ibge: str):
    """Polígono oficial do município (malha do IBGE, maior qualidade). Tempo curto e poucas tentativas: o servidor do IBGE ficou inalcançável a partir do robô (31/10/2026, ConnectTimeout em todas as chamadas)."""
    from shapely.geometry import shape
    js = None
    for _ in range(2):
        try:
            js = httpx.get(IBGE_MALHA.format(ibge=ibge), params={"formato": "application/vnd.geo+json", "qualidade": "maxima"}, headers={"Accept": "*/*"}, timeout=httpx.Timeout(15.0, read=90.0)).json()
            break
        except (httpx.HTTPError, ValueError):
            continue
    if js is None:
        raise RuntimeError("IBGE não respondeu")
    feat = (js.get("features") or [js])[0]
    g = shape(feat.get("geometry") or feat)
    if g.is_empty:
        raise RuntimeError(f"IBGE devolveu limite vazio para {ibge}")
    return g


def poligono_da_relacao(rel: dict):
    """Polígono de uma relação de limite do OSM (`out geom`): junta os caminhos 'outer' e tira os 'inner'. Falha se os caminhos não fecham."""
    from shapely.geometry import LineString
    from shapely.ops import linemerge, polygonize, unary_union
    def faces(papel):
        linhas = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]]) for m in rel.get("members", []) if m.get("type") == "way" and m.get("role") == papel and len(m.get("geometry") or []) >= 2]
        return unary_union(list(polygonize(linemerge(linhas)))) if linhas else None
    fora, dentro = faces("outer"), faces("inner")
    if fora is None or fora.is_empty:
        raise RuntimeError("limite do OSM não fecha (caminhos externos incompletos)")
    return fora.difference(dentro) if dentro is not None and not dentro.is_empty else fora


def limite_osm(db, uf: str, ibge: str):
    """Reserva: o limite do município pela relação do OSM (Overpass, uma consulta pequena). O OSM do Brasil usa a malha do IBGE como base, mas pode diferir na divisa."""
    from app.collectors.osm_malha import Overpass, achar_relacao
    cli = Overpass()
    rel_id = achar_relacao(db, cli, uf, ibge)
    d, _esp = cli.consultar(f"[out:json][timeout:120];rel({rel_id});out geom;", 120)
    rels = [e for e in d.get("elements", []) if e.get("type") == "relation"]
    if not rels:
        raise RuntimeError(f"relação {rel_id} sem geometria")
    return poligono_da_relacao(rels[0])


def limite_municipio(db, uf: str, ibge: str):
    """(geometria, preparada, fonte). Guardado no banco (`limite_municipio`): o contorno quase não muda. Ordem: guardado → IBGE → OSM; se nenhum responde, o erro lista os dois motivos."""
    from shapely import wkt
    from shapely.prepared import prep
    reg = db.query(Registro).filter_by(fonte="osm", tipo="limite_municipio", chave=uf).first()
    if reg and (reg.dados or {}).get("ibge") == ibge and reg.dados.get("wkt"):
        g = wkt.loads(reg.dados["wkt"])
        return g, prep(g), reg.dados["fonte"] + " (guardado)"
    erros = []
    for fonte, obter in (("IBGE malha municipal (qualidade máxima)", lambda: limite_ibge(ibge)), ("OpenStreetMap (relação do município)", lambda: limite_osm(db, uf, ibge))):
        try:
            g = obter()
            if g.is_empty or not g.is_valid:
                g = g.buffer(0)
            if g.is_empty:
                raise RuntimeError("limite vazio")
            upsert(db, Registro, {"fonte": "osm", "tipo": "limite_municipio", "chave": uf}, {"uf": uf, "titulo": f"Limite de {CAPITAIS[uf][0]}", "dados": {"ibge": ibge, "fonte": fonte, "wkt": g.wkt, "area_graus2": g.area}})
            db.commit()
            return g, prep(g), fonte
        except Exception as e:  # noqa: BLE001
            db.rollback()
            erros.append(f"{fonte}: {type(e).__name__} {str(e)[:70]}")
    raise RuntimeError("sem limite do município. " + "; ".join(erros))


def cabecalho_pbf(caminho: Path) -> dict:
    import osmium
    with osmium.io.Reader(str(caminho), osmium.osm.osm_entity_bits.NOTHING) as r:
        h = r.header()
        return {"osm_base": h.get("osmosis_replication_timestamp") or None, "gerador": h.get("generator") or None}


def processar_pbf(caminho: Path, alvos: dict) -> dict:
    """Um passe pelo arquivo. `alvos` = {uf: (geometria, preparada)}. Devolve {uf: {"elements": [...]}, "_estatisticas": {...}} no formato que `resumir_parte` entende."""
    import osmium
    caixas = {uf: g.bounds for uf, (g, _p) in alvos.items()}
    from shapely.geometry import Point
    saida: dict = {uf: [] for uf in alvos}
    est = {"vias_highway_lidas": 0, "vias_nos_alvos": 0, "sem_localizacao": 0}
    proc = osmium.FileProcessor(str(caminho), osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(osmium.filter.KeyFilter("highway"))
    for w in proc:
        if not w.is_way():   # nós com `highway` (faixa de pedestres, semáforo) passam pelo filtro: só as vias interessam
            continue
        est["vias_highway_lidas"] += 1
        tipo = w.tags.get("highway")
        if not tipo or tipo in _EXCL or w.tags.get("area") == "yes" or len(w.nodes) < 2:
            continue
        try:
            meio = w.nodes[len(w.nodes) // 2].location
            lon, lat = meio.lon, meio.lat
        except osmium.InvalidLocationError:
            est["sem_localizacao"] += 1
            continue
        for uf, (x0, y0, x1, y1) in caixas.items():
            if not (x0 <= lon <= x1 and y0 <= lat <= y1) or not alvos[uf][1].contains(Point(lon, lat)):
                continue
            try:
                geo = [{"lat": n.lat, "lon": n.lon} for n in w.nodes]
            except osmium.InvalidLocationError:
                est["sem_localizacao"] += 1
                break
            saida[uf].append({"type": "way", "id": w.id, "tags": {"highway": tipo, "name": w.tags.get("name", "")}, "geometry": geo})
            est["vias_nos_alvos"] += 1
            break
    return {"vias": saida, "estatisticas": est}


def montar_capital(uf: str, elementos: list[dict], meta: dict) -> dict:
    nome, ibge = CAPITAIS[uf]
    p = resumir_parte(elementos)
    d = juntar_partes({"pbf": p})
    minimo = MINIMO_KM.get(uf, MINIMO_KM_PADRAO)
    if d["km_total"] < minimo:
        raise RuntimeError(f"{nome}: só {d['km_total']} km (esperado ≥ {minimo}); limite do município ou extrato errado; nada foi gravado")
    d.update({"capital": nome, "uf": uf, "ibge": ibge, "medido_em": datetime.now().isoformat(timespec="seconds"), "fonte": "OpenStreetMap (extrato da Geofabrik), colaborativo", "metodo": "pbf",
              "ids_duplicados": p["ids_duplicados"], **meta})
    return d


def coletar_malha_pbf(ufs: str = "", refazer: bool = False, manter: bool = False):
    """Baixa o extrato da região de cada capital pedida, confere o MD5, lê em um passe e grava a malha de cada capital. As capitais que já têm leitura de até 25 dias pelo mesmo extrato não são
    refeitas (`refazer=true` força). O arquivo baixado é apagado ao fim (`manter=true` guarda)."""
    refazer, manter = (str(v).lower() in ("true", "1", "sim") for v in (refazer, manter))
    with registrar_coleta("osm", "malha_pbf", ufs=ufs or "todas", refazer=refazer) as (db, n):
        alvo = _lista_ufs(ufs) or list(CAPITAIS)
        por_regiao: dict[str, list[str]] = {}
        for uf in alvo:
            por_regiao.setdefault(REGIAO[uf], []).append(uf)
        for regiao, lista in por_regiao.items():
            faltam = [u for u in lista if refazer or not _recente(db, u)]
            if not faltam:
                continue
            etapa = "extrato"
            try:
                url = escolher_extrato(regiao)
                etapa = "limite do município (IBGE)"
                limites = {uf: limite_municipio(db, uf, CAPITAIS[uf][1]) for uf in faltam}   # antes do download de GBs: se nenhuma fonte de limite responde, para logo
                alvos = {uf: (g, pr) for uf, (g, pr, _f) in limites.items()}
                etapa = "download do extrato"
                destino = pasta_destino() / url.rsplit("/", 1)[-1]
                oficial = md5_oficial(url)
                transf = baixar(url, destino)
                etapa = "conferência do MD5"
                real = md5(destino)
                if oficial and real != oficial:
                    destino.unlink(missing_ok=True)
                    raise RuntimeError(f"MD5 do extrato não confere ({real[:8]}… ≠ {oficial[:8]}…); arquivo descartado")
                cab = cabecalho_pbf(destino)
                etapa = "leitura do extrato"
                res = processar_pbf(destino, alvos)
                etapa = "gravação"
                meta = {"extrato": url.rsplit("/", 1)[-1], "extrato_url": url, "md5": real, "md5_confere": bool(oficial) and real == oficial, "osm_base": cab["osm_base"], "baixado_em": datetime.now().isoformat(timespec="seconds"),
                        "tamanho_extrato": transf["tamanho"], "download_retomado": transf["retomado"], "limites": {uf: f for uf, (_g, _p, f) in limites.items()}, "estatisticas_do_passe": res["estatisticas"], "aviso": AVISO}
                for uf in faltam:
                    try:
                        d = montar_capital(uf, res["vias"][uf], meta)
                        upsert(db, Registro, {"fonte": "osm", "tipo": "malha_capital", "chave": uf}, {"uf": uf, "titulo": f"Malha viária de {CAPITAIS[uf][0]}", "valor": d["km_total"], "dados": d})
                        db.commit()
                        n += 1
                    except Exception as e:  # noqa: BLE001
                        db.rollback()
                        n.avisos.append(f"{uf}: {type(e).__name__}: {str(e)[:150]}")
                if not manter:
                    destino.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001 - uma região que falha não derruba as outras
                db.rollback()
                n.avisos.append(f"região {regiao} ({etapa}): {type(e).__name__}: {str(e)[:150]}")
        if not n.itens and n.avisos:
            raise RuntimeError("; ".join(n.avisos))
    return n.itens


def _recente(db, uf: str) -> bool:
    r = db.query(Registro).filter_by(fonte="osm", tipo="malha_capital", chave=uf).first()
    try:
        return bool(r) and (r.dados or {}).get("metodo") == "pbf" and date.fromisoformat(str(r.dados["medido_em"])[:10]) >= date.today() - timedelta(days=VALIDADE_DIAS)
    except (KeyError, ValueError):
        return False



