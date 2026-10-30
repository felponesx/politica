"""Trânsito das capitais, em três partes que NÃO se misturam:

1. Malha viária (OpenStreetMap, consulta Overpass): quilômetros de via por capital e por categoria, trechos, vias nomeadas. É o tamanho da malha, não o trânsito.
2. Congestionamento e velocidade observada (TomTom Traffic API, fluxo e incidentes): amostra pequena de pontos por capital, com a franquia gratuita. A chave
   `TOMTOM_API_KEY` fica só no servidor (variável de ambiente); sem chave o coletor falha com mensagem clara e nada é inventado.
3. O índice anual de congestionamento do TomTom Traffic Index continua em `app/dados/transito.json` (outra fonte, outra medida).

Limitações da malha: o OpenStreetMap é colaborativo; a via de pista dupla conta uma vez por sentido (são dois trechos); vias que cruzam a divisa do município
entram inteiras; ciclovias, calçadas, escadas e vias em projeto/obra ficam de fora; bairros ainda não são separados."""
import logging
import math
import time
from datetime import date, datetime

import httpx

from app import http
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.transito")
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter")
UA = {"User-Agent": "BRASIL+ coletor de dados publicos (contato: github.com/felponesx/politica)"}
CAPITAIS = {
    "AC": ("Rio Branco", "1200401"), "AL": ("Maceió", "2704302"), "AP": ("Macapá", "1600303"), "AM": ("Manaus", "1302603"), "BA": ("Salvador", "2927408"),
    "CE": ("Fortaleza", "2304400"), "DF": ("Brasília", "5300108"), "ES": ("Vitória", "3205309"), "GO": ("Goiânia", "5208707"), "MA": ("São Luís", "2111300"),
    "MT": ("Cuiabá", "5103403"), "MS": ("Campo Grande", "5002704"), "MG": ("Belo Horizonte", "3106200"), "PA": ("Belém", "1501402"), "PB": ("João Pessoa", "2507507"),
    "PR": ("Curitiba", "4106902"), "PE": ("Recife", "2611606"), "PI": ("Teresina", "2211001"), "RJ": ("Rio de Janeiro", "3304557"), "RN": ("Natal", "2408102"),
    "RS": ("Porto Alegre", "4314902"), "RO": ("Porto Velho", "1100205"), "RR": ("Boa Vista", "1400100"), "SC": ("Florianópolis", "4205407"), "SP": ("São Paulo", "3550308"),
    "SE": ("Aracaju", "2800308"), "TO": ("Palmas", "1721000"),
}
CATEGORIAS = {"motorway": "Expressas e rodovias", "trunk": "Expressas e rodovias", "primary": "Arteriais", "secondary": "Coletoras", "tertiary": "Coletoras",
              "residential": "Locais", "living_street": "Locais", "unclassified": "Locais", "service": "Acesso e serviço"}
EXCLUIDAS = "footway|path|steps|cycleway|pedestrian|bridleway|corridor|proposed|construction|platform|elevator|raceway|bus_guideway|escape|rest_area|services|track"
MINIMO_KM = {"SP": 8_000, "RJ": 4_000}   # guarda contra consulta cortada; as outras capitais: 300 km
MINIMO_KM_PADRAO = 300


def _lista_ufs(ufs) -> list[str]:
    """Aceita "TO,DF", ["TO", "DF"] (a linha de comando do robô converte vírgulas em lista) ou vazio; só UFs de capitais conhecidas."""
    itens = ufs if isinstance(ufs, (list, tuple)) else str(ufs or "").split(",")
    return [u for u in (str(i).strip().upper() for i in itens) if u in CAPITAIS]


# Conferido com o Overpass pelo robô (30/10/2026): Palmas acha-se por IBGE:GEOCODIGO; a relação de Brasília não tem esse código, mas o DF é um município só
# (relação do Distrito Federal, ISO3166-2 BR-DF).
SELETOR_ESPECIAL = {"DF": '["admin_level"="4"]["ISO3166-2"="BR-DF"]'}


def consulta(ibge: str, uf: str = "") -> str:
    sel = SELETOR_ESPECIAL.get(uf) or f'["IBGE:GEOCODIGO"="{ibge}"]'
    return (f'[out:json][timeout:600][maxsize:2147483648];rel["boundary"="administrative"]{sel};map_to_area->.a;'
            f'way(area.a)["highway"]["highway"!~"^({EXCLUIDAS})$"]["area"!="yes"];out geom qt;')


def metros(geometria: list[dict]) -> float:
    total = 0.0
    for a, b in zip(geometria, geometria[1:]):
        p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
        dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * 6371008.8 * math.asin(math.sqrt(h))
    return total


def categoria(tipo: str) -> str:
    base = tipo.replace("_link", "")
    return CATEGORIAS.get(base, "Outras")


def resumir_malha(elementos: list[dict]) -> dict:
    """Soma o comprimento real de cada via (cada id uma vez só) por categoria; guarda pontos de amostra nas maiores vias arteriais."""
    vistos: set[int] = set()
    por_cat: dict[str, dict] = {}
    nomes: set[str] = set()
    candidatas = []
    for e in elementos:
        if e.get("type") != "way" or e.get("id") in vistos:
            continue
        geo = e.get("geometry") or []
        tags = e.get("tags") or {}
        if len(geo) < 2 or not tags.get("highway"):
            continue
        vistos.add(e["id"])
        m = metros(geo)
        cat = categoria(tags["highway"])
        c = por_cat.setdefault(cat, {"km": 0.0, "trechos": 0})
        c["km"] += m / 1000
        c["trechos"] += 1
        if tags.get("name"):
            nomes.add(tags["name"].strip().lower())
        if cat in ("Expressas e rodovias", "Arteriais") and m > 400:
            meio = geo[len(geo) // 2]
            candidatas.append((m, round(meio["lat"], 5), round(meio["lon"], 5)))
    candidatas.sort(reverse=True)
    pontos, usados = [], []
    for m, lat, lon in candidatas:   # pontos espalhados: ignora os que ficam a menos de ~1,5 km de um já escolhido
        if all(abs(lat - a) + abs(lon - b) > 0.015 for a, b in usados):
            pontos.append({"lat": lat, "lon": lon})
            usados.append((lat, lon))
        if len(pontos) >= 8:
            break
    km = sum(c["km"] for c in por_cat.values())
    return {"km_total": round(km, 1), "trechos": sum(c["trechos"] for c in por_cat.values()), "vias_nomeadas": len(nomes),
            "por_categoria": {k: {"km": round(v["km"], 1), "trechos": v["trechos"]} for k, v in sorted(por_cat.items(), key=lambda x: -x[1]["km"])}, "pontos_amostra": pontos}


def overpass(q: str, tentativas: int = 6) -> dict:
    """POST no Overpass, alternando espelhos com espera crescente (o servidor público devolve 502/504 e demora minutos em consultas grandes)."""
    erros = []
    for i in range(tentativas):
        url = OVERPASS[i % len(OVERPASS)]
        try:
            r = httpx.post(url, data={"data": q}, headers=UA, timeout=httpx.Timeout(60.0, read=700.0))
            if r.status_code in (429, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
            erros.append(f"{url.split('/')[2]}: {type(e).__name__}")
            time.sleep(min(20 * (i + 1), 120))
    raise RuntimeError("Overpass indisponível: " + "; ".join(erros[-4:]))


def coletar_osm_malha(ufs: str = ""):
    """Quilômetros de via de cada capital (OpenStreetMap). `ufs` = lista separada por vírgula (vazio = as 27)."""
    with registrar_coleta("osm", "malha_capitais", ufs=ufs or "todas") as (db, n):
        alvo = _lista_ufs(ufs) or list(CAPITAIS)
        for uf in alvo:
            nome, ibge = CAPITAIS[uf]
            try:
                dados = overpass(consulta(ibge, uf))
                d = resumir_malha(dados.get("elements") or [])
                minimo = MINIMO_KM.get(uf, MINIMO_KM_PADRAO)
                if d["km_total"] < minimo:
                    raise RuntimeError(f"{nome}: só {d['km_total']} km (esperado ≥ {minimo}); consulta cortada ou município não achado; nada foi gravado")
                d.update({"capital": nome, "uf": uf, "ibge": ibge, "medido_em": datetime.now().isoformat(timespec="seconds"),
                          "fonte": "OpenStreetMap (Overpass), colaborativo", "osm_base": (dados.get("osm3s") or {}).get("timestamp_osm_base")})
                upsert(db, Registro, {"fonte": "osm", "tipo": "malha_capital", "chave": uf}, {"uf": uf, "titulo": f"Malha viária de {nome}", "valor": d["km_total"], "dados": d})
                db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001 - uma capital que falha não derruba as outras
                n.avisos.append(f"{uf}: {type(e).__name__}: {str(e)[:150]}")
            time.sleep(15)   # respeita o servidor público do Overpass
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhuma capital foi lida")
    return n.itens


# ---------------- TomTom ----------------
TOMTOM_FLUXO = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
TOMTOM_INCIDENTES = "https://api.tomtom.com/traffic/services/5/incidentDetails"


def ler_fluxo(js: dict) -> dict | None:
    f = (js or {}).get("flowSegmentData") or {}
    atual, livre = f.get("currentSpeed"), f.get("freeFlowSpeed")
    if not atual and atual != 0 or not livre:
        return None
    return {"velocidade_kmh": float(atual), "fluxo_livre_kmh": float(livre), "congestionamento_pct": round(max(0.0, 1 - float(atual) / float(livre)) * 100, 1),
            "tempo_atual_s": f.get("currentTravelTime"), "tempo_livre_s": f.get("freeFlowTravelTime"), "confianca": f.get("confidence"), "via_fechada": bool(f.get("roadClosure"))}


def ler_incidentes(js: dict) -> dict:
    itens = (js or {}).get("incidents") or []
    por_tipo: dict[str, int] = {}
    atraso = 0
    for i in itens:
        p = i.get("properties") or {}
        k = str(p.get("iconCategory", "?"))
        por_tipo[k] = por_tipo.get(k, 0) + 1
        atraso += int(p.get("delay") or 0)
    return {"incidentes": len(itens), "por_categoria_tomtom": por_tipo, "atraso_total_s": atraso}


def _chave() -> str:
    k = (getattr(settings, "tomtom_api_key", "") or "").strip()
    if not k:
        raise RuntimeError("TOMTOM_API_KEY não configurada (cadastro gratuito em developer.tomtom.com; ponha a chave só no servidor, em variável de ambiente). Nada foi coletado nem simulado.")
    return k


def coletar_tomtom_transito(ufs: str = "", pontos: int = 4):
    """Velocidade, fluxo livre, congestionamento e incidentes em até `pontos` vias por capital (os pontos vêm da malha do OSM já coletada).
    Respeita `tomtom_limite_dia` chamadas por dia (franquia gratuita)."""
    chave = _chave()
    with registrar_coleta("tomtom", "transito", ufs=ufs or "todas", pontos=pontos) as (db, n):
        hoje = date.today().isoformat()
        uso = upsert(db, Registro, {"fonte": "tomtom", "tipo": "uso_dia", "chave": hoje}, {"titulo": f"Chamadas TomTom {hoje}", "dados": {"chamadas": 0}})
        db.flush()
        chamadas = int((uso.dados or {}).get("chamadas", 0))
        limite = int(settings.tomtom_limite_dia)
        alvo = _lista_ufs(ufs) or list(CAPITAIS)
        for uf in alvo:
            malha = db.query(Registro).filter_by(fonte="osm", tipo="malha_capital", chave=uf).first()
            amostra = ((malha.dados or {}).get("pontos_amostra") or [])[: int(pontos)] if malha else []
            if not amostra:
                n.avisos.append(f"{uf}: sem pontos de amostra (rode osm-malha-capitais antes)")
                continue
            if chamadas + len(amostra) + 1 > limite:
                n.avisos.append(f"{uf}: limite diário de {limite} chamadas atingido; parou aqui")
                break
            medidas = []
            for p in amostra:
                try:
                    js = http.get_json(TOMTOM_FLUXO, params={"point": f"{p['lat']},{p['lon']}", "unit": "KMPH", "key": chave}, headers={"Accept": "*/*"})
                    chamadas += 1
                    m = ler_fluxo(js)
                    if m:
                        medidas.append(m)
                except Exception as e:  # noqa: BLE001
                    n.avisos.append(f"{uf}: fluxo {type(e).__name__}")
                time.sleep(0.3)
            if not medidas:
                continue
            lats, lons = [p["lat"] for p in amostra], [p["lon"] for p in amostra]
            bbox = f"{min(lons) - .05},{min(lats) - .05},{max(lons) + .05},{max(lats) + .05}"
            inc = {"incidentes": None}
            try:
                js = http.get_json(TOMTOM_INCIDENTES, params={"bbox": bbox, "fields": "{incidents{type,properties{iconCategory,delay,length}}}", "language": "pt-BR", "key": chave})
                chamadas += 1
                inc = ler_incidentes(js)
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"{uf}: incidentes {type(e).__name__}")
            media = lambda k: round(sum(m[k] for m in medidas) / len(medidas), 1)  # noqa: E731
            agora = datetime.now().isoformat(timespec="seconds")
            d = {"capital": CAPITAIS[uf][0], "uf": uf, "medido_em": agora, "pontos_medidos": len(medidas), "velocidade_media_kmh": media("velocidade_kmh"),
                 "fluxo_livre_medio_kmh": media("fluxo_livre_kmh"), "congestionamento_pct": media("congestionamento_pct"), **inc, "fonte": "TomTom Traffic API (amostra de vias, não a cidade inteira)"}
            upsert(db, Registro, {"fonte": "tomtom", "tipo": "transito_agora", "chave": uf}, {"uf": uf, "titulo": f"Trânsito agora em {d['capital']}", "valor": d["congestionamento_pct"], "dados": d})
            dia = db.query(Registro).filter_by(fonte="tomtom", tipo="transito_dia", chave=f"{uf}|{hoje}").first()
            ant = (dia.dados or {}) if dia else {}
            k = int(ant.get("medicoes", 0))
            mm = lambda campo: round((ant.get(campo, 0) * k + d[campo]) / (k + 1), 1)  # noqa: E731
            upsert(db, Registro, {"fonte": "tomtom", "tipo": "transito_dia", "chave": f"{uf}|{hoje}"},
                   {"uf": uf, "titulo": f"Trânsito em {d['capital']} em {hoje}", "dados": {"data": hoje, "medicoes": k + 1, "velocidade_media_kmh": mm("velocidade_media_kmh"), "congestionamento_pct": mm("congestionamento_pct")}})
            uso.dados = {"chamadas": chamadas}
            db.commit()
            n += 1
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhuma capital foi medida")
    return n.itens
