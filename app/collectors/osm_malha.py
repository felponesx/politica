"""Malha viária das capitais pelo Overpass (OpenStreetMap), feita para os servidores públicos que são lentos e ficam cheios.

O que o diagnóstico do robô mostrou (31/10/2026): overpass-api.de responde, mas leva 30–45 s até numa consulta mínima (fila de vagas); overpass.private.coffee às vezes passa de 90 s e
serve uma base de 28/07/2026 (3 meses velha); maps.mail.ru devolve 504 ("Dispatcher_Client::request_read_and_idx::timeout: o servidor está ocupado") e depois responde. A consulta
antiga pedia a cidade inteira numa só chamada (`map_to_area` + `out geom`, até 700 s de leitura, com um espelho morto no meio): em capital grande ela estoura o tempo ou a memória do servidor.

Por isso aqui: (1) a relação do município é achada uma vez (consulta de poucos bytes) e guardada; (2) a malha de cada capital é pedida em PARTES por tipo de via (disjuntas e completas),
cada parte salva no banco assim que chega (retoma de onde parou, sem refazer o que já veio); (3) uma consulta por vez, com intervalo e espera pela vaga do servidor (/api/status);
(4) espelhos em rodízio (overpass-api.de, overpass.private.coffee, maps.mail.ru), com espera crescente e tempo-limite crescente; (5) resposta com `remark` de erro/tempo esgotado ou
com a base mais velha que `BASE_MAX_DIAS` é recusada (o Overpass devolve 200 com resultado cortado nesses casos); (6) vias repetidas pelo id do OSM contam uma vez; (7) o carimbo
`timestamp_osm_base` de cada parte vai para o resultado. A capital só é gravada quando todas as partes chegaram."""
import logging
import re
import time
import zlib
from datetime import date, datetime, timedelta, timezone

import httpx

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.osm_malha")
ESPELHOS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
UA = {"User-Agent": "BRASIL+ coletor de dados publicos (contato: github.com/felponesx/politica)"}
INTERVALO = 10.0        # segundos entre consultas ao mesmo servidor (nunca em paralelo)
BASE_MAX_DIAS = 7       # espelho com base OSM mais velha que isso é descartado
VALIDADE_PARTE_DIAS = 25
TENTATIVAS = 6          # por parte: duas voltas completas pelos três espelhos
EXCLUIDAS = "footway|path|steps|cycleway|pedestrian|bridleway|corridor|proposed|construction|platform|elevator|raceway|bus_guideway|escape|rest_area|services|track"
_PRINCIPAIS = "motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"
_LOCAIS = "residential|living_street|unclassified"
# Quatro partes que não se sobrepõem (um valor de `highway` cai em exatamente uma) e juntas cobrem tudo o que a consulta antiga cobria.
GRUPOS = {
    "principais": f'["highway"~"^({_PRINCIPAIS})$"]',
    "locais": f'["highway"~"^({_LOCAIS})$"]',
    "servico": '["highway"="service"]',
    "outras": f'["highway"]["highway"!~"^({_PRINCIPAIS}|{_LOCAIS}|service|{EXCLUIDAS})$"]',
}
ERRO_NO_CORPO = re.compile(r"runtime error|timed out|out of memory|too busy|rate_limited", re.I)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _base_recente(ts: str | None) -> bool:
    """A base do espelho (`timestamp_osm_base`) tem de ser de até BASE_MAX_DIAS dias."""
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return False
    return _agora() - t <= timedelta(days=BASE_MAX_DIAS)


class Overpass:
    """Cliente sequencial: um pedido por vez, espera pela vaga do servidor, rodízio de espelhos, tempo-limite e espera crescentes. Cada pedido devolve (json, espelho)."""

    def __init__(self, espelhos=ESPELHOS, intervalo: float = INTERVALO, dormir=time.sleep):
        self.espelhos = list(espelhos)
        self.intervalo = intervalo
        self.dormir = dormir
        self.ultimo = 0.0
        self.falhas: list[str] = []
        self.i = 0

    def _vaga(self, base: str):
        """Pergunta ao /api/status se há vaga; se não, espera o que o servidor diz (no máximo 2 min). Falha do status não impede a consulta."""
        try:
            r = httpx.get(base.replace("interpreter", "status"), headers=UA, timeout=20)
            m = re.search(r"in (\d+) seconds", r.text)
            if m and "0 slots available now" in r.text:
                self.dormir(min(int(m.group(1)) + 1, 120))
        except httpx.HTTPError:
            pass

    def consultar(self, consulta: str, timeout_servidor: int = 180) -> tuple[dict, str]:
        erros = []
        for k in range(TENTATIVAS):
            base = self.espelhos[(self.i + k) % len(self.espelhos)]
            espera = self.intervalo - (time.monotonic() - self.ultimo)
            if espera > 0:
                self.dormir(espera)
            self._vaga(base)
            limite = min(timeout_servidor * (1 + k // len(self.espelhos)), 600)   # na 2ª volta pede mais tempo ao servidor
            q = re.sub(r"\[timeout:\d+\]", f"[timeout:{limite}]", consulta)
            nome = base.split("/")[2]
            try:
                r = httpx.post(base, data={"data": q}, headers=UA, timeout=httpx.Timeout(20.0, read=limite + 30.0))
                self.ultimo = time.monotonic()
                if r.status_code in (429, 502, 503, 504):
                    raise RuntimeError(f"HTTP {r.status_code}")
                r.raise_for_status()
                d = r.json()   # resposta cortada no meio não é JSON válido: cai no except
                osm3s = d.get("osm3s") or {}
                if ERRO_NO_CORPO.search(str(d.get("remark") or "")):
                    raise RuntimeError("servidor avisou: " + str(d["remark"])[:80])
                if not _base_recente(osm3s.get("timestamp_osm_base")):
                    raise RuntimeError(f"base OSM velha ({osm3s.get('timestamp_osm_base')})")
                self.i = (self.i + k) % len(self.espelhos)   # continua no que funcionou
                return d, nome
            except (httpx.HTTPError, ValueError, RuntimeError) as e:
                self.ultimo = time.monotonic()
                erros.append(f"{nome}: {type(e).__name__} {str(e)[:60]}")
                self.falhas.append(erros[-1])
                self.dormir(min(15 * (k + 1), 90))
        raise RuntimeError("Overpass indisponível: " + "; ".join(erros[-4:]))


def seletor_relacao(uf: str, ibge: str) -> str:
    from app.collectors.transito import SELETOR_ESPECIAL
    return SELETOR_ESPECIAL.get(uf) or f'["IBGE:GEOCODIGO"="{ibge}"]'


def achar_relacao(db, cli: Overpass, uf: str, ibge: str, refazer: bool = False) -> int:
    """Id da relação do município no OSM (guardado: não muda). Consulta de poucos bytes."""
    reg = db.query(Registro).filter_by(fonte="osm", tipo="relacao_municipio", chave=uf).first()
    if reg and not refazer and (reg.dados or {}).get("ibge") == ibge:
        return int(reg.dados["relacao"])
    d, esp = cli.consultar(f'[out:json][timeout:60];rel["boundary"="administrative"]{seletor_relacao(uf, ibge)};out ids;', 60)
    ids = [e["id"] for e in d.get("elements", []) if e.get("type") == "relation"]
    if not ids:
        raise RuntimeError(f"{uf}: relação do município (IBGE {ibge}) não encontrada no OSM")
    upsert(db, Registro, {"fonte": "osm", "tipo": "relacao_municipio", "chave": uf}, {"uf": uf, "titulo": f"Relação OSM de {uf}", "dados": {"ibge": ibge, "relacao": ids[0], "candidatas": ids[:5], "espelho": esp}})
    db.commit()
    return ids[0]


def consulta_parte(relacao: int, grupo: str) -> str:
    return f'[out:json][timeout:180];area({3600000000 + relacao})->.a;way(area.a){GRUPOS[grupo]}["area"!="yes"];out geom qt;'


def resumir_parte(elementos: list[dict]) -> dict:
    """Soma da parte (cada id do OSM uma vez) no formato que o resumo final junta."""
    from app.collectors.transito import categoria, metros
    vistos: set[int] = set()
    por_cat: dict[str, dict] = {}
    nomes: set[int] = set()
    candidatas = []
    duplicados = 0
    for e in elementos:
        if e.get("type") != "way":
            continue
        if e.get("id") in vistos:
            duplicados += 1
            continue
        geo, tags = e.get("geometry") or [], e.get("tags") or {}
        if len(geo) < 2 or not tags.get("highway"):
            continue
        vistos.add(e["id"])
        m = metros(geo)
        cat = categoria(tags["highway"])
        c = por_cat.setdefault(cat, {"km": 0.0, "trechos": 0})
        c["km"] += m / 1000
        c["trechos"] += 1
        if tags.get("name"):
            nomes.add(zlib.crc32(tags["name"].strip().lower().encode()))
        if cat in ("Expressas e rodovias", "Arteriais") and m > 400:
            meio = geo[len(geo) // 2]
            candidatas.append((round(m), round(meio["lat"], 5), round(meio["lon"], 5)))
    candidatas.sort(reverse=True)
    return {"por_categoria": {k: {"km": round(v["km"], 4), "trechos": v["trechos"]} for k, v in por_cat.items()}, "nomes_crc32": sorted(nomes), "candidatas": candidatas[:40],
            "vias": len(vistos), "ids_duplicados": duplicados}


def juntar_partes(partes: dict[str, dict]) -> dict:
    """Junta as partes de uma capital: km por categoria, vias com nome (união dos nomes) e até 8 pontos de amostra espalhados nas maiores vias."""
    por_cat: dict[str, dict] = {}
    nomes: set[int] = set()
    cand = []
    for p in partes.values():
        for k, v in p["por_categoria"].items():
            c = por_cat.setdefault(k, {"km": 0.0, "trechos": 0})
            c["km"] += v["km"]
            c["trechos"] += v["trechos"]
        nomes.update(p["nomes_crc32"])
        cand += [tuple(x) for x in p["candidatas"]]
    cand.sort(reverse=True)
    pontos, usados = [], []
    for _m, lat, lon in cand:
        if all(abs(lat - a) + abs(lon - b) > 0.015 for a, b in usados):
            pontos.append({"lat": lat, "lon": lon})
            usados.append((lat, lon))
        if len(pontos) >= 8:
            break
    km = sum(c["km"] for c in por_cat.values())
    return {"km_total": round(km, 1), "trechos": sum(c["trechos"] for c in por_cat.values()), "vias_nomeadas": len(nomes),
            "por_categoria": {k: {"km": round(v["km"], 1), "trechos": v["trechos"]} for k, v in sorted(por_cat.items(), key=lambda x: -x[1]["km"])}, "pontos_amostra": pontos}


def _parte_valida(reg, refazer: bool) -> bool:
    if reg is None or refazer:
        return False
    try:
        return date.fromisoformat(str(reg.dados["medido_em"])[:10]) >= date.today() - timedelta(days=VALIDADE_PARTE_DIAS)
    except (KeyError, ValueError):
        return False


def coletar_capital(db, cli: Overpass, uf: str, refazer: bool = False) -> dict:
    from app.collectors.transito import CAPITAIS, MINIMO_KM, MINIMO_KM_PADRAO
    nome, ibge = CAPITAIS[uf]
    rel = achar_relacao(db, cli, uf, ibge, refazer)
    partes: dict[str, dict] = {}
    usadas = 0
    for grupo in GRUPOS:
        reg = db.query(Registro).filter_by(fonte="osm", tipo="malha_parte", chave=f"{uf}:{grupo}").first()
        if _parte_valida(reg, refazer) and (reg.dados or {}).get("relacao") == rel:
            partes[grupo] = reg.dados
            usadas += 1
            continue
        dados, esp = cli.consultar(consulta_parte(rel, grupo))
        p = resumir_parte(dados.get("elements") or [])
        p.update({"uf": uf, "grupo": grupo, "relacao": rel, "espelho": esp, "osm_base": (dados.get("osm3s") or {}).get("timestamp_osm_base"), "medido_em": datetime.now().isoformat(timespec="seconds")})
        upsert(db, Registro, {"fonte": "osm", "tipo": "malha_parte", "chave": f"{uf}:{grupo}"}, {"uf": uf, "titulo": f"Malha de {nome}: {grupo}", "dados": p})
        db.commit()   # a parte fica salva: se a coleta cair agora, a próxima retoma daqui
        partes[grupo] = p
    d = juntar_partes(partes)
    minimo = MINIMO_KM.get(uf, MINIMO_KM_PADRAO)
    if d["km_total"] < minimo:
        raise RuntimeError(f"{nome}: só {d['km_total']} km (esperado ≥ {minimo}); consulta cortada ou município não achado; nada foi gravado")
    bases = [p["osm_base"] for p in partes.values() if p.get("osm_base")]
    d.update({"capital": nome, "uf": uf, "ibge": ibge, "relacao_osm": rel, "medido_em": datetime.now().isoformat(timespec="seconds"), "fonte": "OpenStreetMap (Overpass), colaborativo",
              "osm_base": min(bases) if bases else None, "espelhos": sorted({p["espelho"] for p in partes.values()}), "partes": {g: {"km": round(sum(c["km"] for c in p["por_categoria"].values()), 1), "vias": p["vias"],
                                                                                                                       "ids_duplicados": p["ids_duplicados"], "osm_base": p.get("osm_base")} for g, p in partes.items()},
              "partes_reaproveitadas": usadas, "metodo": "overpass"})
    atual = db.query(Registro).filter_by(fonte="osm", tipo="malha_capital", chave=uf).first()
    if atual and (atual.dados or {}).get("metodo") == "pbf" and not refazer and str(atual.dados.get("medido_em", ""))[:10] >= (date.today() - timedelta(days=VALIDADE_PARTE_DIAS)).isoformat():
        d["nao_gravada"] = "já existe leitura do extrato da Geofabrik (PBF) com menos de 25 dias; as partes do Overpass ficam guardadas"
        return d   # o extrato é a fonte preferida: o Overpass só preenche quando ele não existe
    upsert(db, Registro, {"fonte": "osm", "tipo": "malha_capital", "chave": uf}, {"uf": uf, "titulo": f"Malha viária de {nome}", "valor": d["km_total"], "dados": d})
    db.commit()
    return d


def coletar_malha_overpass(ufs: str = "", refazer: bool = False):
    from app.collectors.transito import CAPITAIS, _lista_ufs
    refazer = str(refazer).lower() in ("true", "1", "sim")
    with registrar_coleta("osm", "malha_capitais", ufs=ufs or "todas", refazer=refazer) as (db, n):
        cli = Overpass()
        for uf in (_lista_ufs(ufs) or list(CAPITAIS)):
            try:
                coletar_capital(db, cli, uf, refazer)
                n += 1
            except Exception as e:  # noqa: BLE001 - uma capital que falha não derruba as outras; as partes já salvas ficam para a próxima
                db.rollback()
                n.avisos.append(f"{uf}: {type(e).__name__}: {str(e)[:150]}")
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhuma capital foi lida")
    return n.itens

