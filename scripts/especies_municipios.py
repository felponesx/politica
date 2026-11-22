"""Espécies ameaçadas com registro em cada município (ocorrências com coordenada do GBIF).

Uso:
    python -m scripts.especies_municipios mapear              # liga o município do GADM ao código do IBGE (rápido)
    python -m scripts.especies_municipios coletar [animais|plantas]   # pergunta ao GBIF, espécie por espécie (retoma de onde parou)
    python -m scripts.especies_municipios coletar-centroides [animais|plantas]   # registros de centroide (a descontar)
    python -m scripts.especies_municipios coletar-caixa [animais|plantas]        # registros na caixa do centroide do Brasil (a descontar)
    python -m scripts.especies_municipios agregar             # soma por município e grava app/dados/especies_municipio.json

Como funciona: para cada espécie da lista oficial do MMA (chave do GBIF em app/dados/*_fotos_chaves.json) pede ao GBIF a contagem de
registros por município (faceta gadmLevel2Gid, com coordenada, sem problema geoespacial, sem exemplar cultivado nem fóssil). Cada
município do GADM é ligado ao município do IBGE pelo ponto interno do seu polígono. A conta final é quantas espécies diferentes têm ao
menos um registro no município.

LIMITE IMPORTANTE: o GBIF reúne observações e coletas de museus e cientistas. Onde há mais gente observando (cidades, parques, estradas)
aparecem mais espécies. Município sem registro NÃO quer dizer município sem a espécie.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "app" / "dados"
UA = {"User-Agent": "BRASILMais/1.0 (site de dados abertos)"}
GADM = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_BRA_2.json.zip"
IBGE_MALHA = "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json&intrarregiao=municipio&qualidade=minima"
IBGE_NOMES = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
GBIF = "https://api.gbif.org/v1/occurrence/search"
BASES = ["HUMAN_OBSERVATION", "OBSERVATION", "MACHINE_OBSERVATION", "PRESERVED_SPECIMEN", "MATERIAL_SAMPLE", "OCCURRENCE"]
MAPA = DADOS / "gadm_ibge.json"
SAIDA = DADOS / "especies_municipio.json"
# cache dos pedidos ao GBIF fica fora do repositório (grande); pode ser trocado por variável de ambiente
import os  # noqa: E402

CACHE = Path(os.environ.get("ESPECIES_GBIF_CACHE", "/tmp/especies_gbif_cache"))


def _arquivo_lista(tipo: str):
    if tipo == "animais":
        d = json.loads((DADOS / "fauna_ameacada.json").read_text(encoding="utf-8"))
        chaves = json.loads((DADOS / "fauna_fotos_chaves.json").read_text(encoding="utf-8"))
        return d, chaves, 2
    d = json.loads((DADOS / "flora_ameacada.json").read_text(encoding="utf-8"))
    chaves = json.loads((DADOS / "flora_fotos_chaves.json").read_text(encoding="utf-8"))
    return d, chaves, 3


def _json(cli: httpx.Client, url: str):
    """GET com tentativas: o IBGE às vezes devolve página vazia ou de erro."""
    ultimo = None
    for t in range(6):
        try:
            r = cli.get(url)
            if r.status_code == 200:
                return r.json()
            ultimo = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            ultimo = str(e)[:100]
        time.sleep(3 * (t + 1))
    raise RuntimeError(f"{url[:80]}: {ultimo}")


# ---------------------------------------------------------------- 1) GADM → IBGE
def mapear() -> None:
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    cli = httpx.Client(headers=UA, timeout=300, follow_redirects=True)
    print("baixando o GADM nível 2...")
    z = zipfile.ZipFile(io.BytesIO(cli.get(GADM).content))
    gj = json.loads(z.read(z.namelist()[0]))
    print("baixando a malha do IBGE...")
    ib = _json(cli, IBGE_MALHA)
    polis, cods = [], []
    for f in ib["features"]:
        cod = str(f["properties"]["codarea"])
        polis.append(shape(f["geometry"]))
        cods.append(cod)
    arvore = STRtree(polis)
    out, sem = {}, []
    for f in gj["features"]:
        gid = f["properties"]["GID_2"]
        ponto = shape(f["geometry"]).representative_point()
        idx = [i for i in arvore.query(ponto) if polis[int(i)].contains(ponto)]
        if idx:
            out[gid] = cods[int(idx[0])]
        else:
            j = int(arvore.nearest(ponto))
            if polis[j].distance(ponto) < 0.05:        # beira do mar ou lagoa: o polígono simplificado não alcança o ponto
                out[gid] = cods[j]
            else:
                sem.append(gid)
    MAPA.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out)} municípios do GADM ligados ao IBGE; {len(sem)} sem par: {sem[:10]}")


# ---------------------------------------------------------------- 2) GBIF
class _Ritmo:
    """Espaça os pedidos de todas as threads (o GBIF devolve 429 se vier muito junto)."""

    def __init__(self, intervalo: float):
        self.i, self.t, self.lock = intervalo, 0.0, threading.Lock()

    def esperar(self):
        with self.lock:
            agora = time.time()
            espera = self.t + self.i - agora
            if espera > 0:
                time.sleep(espera)
            self.t = time.time()


def _consultar(cli: httpx.Client, ritmo: _Ritmo, chave: int, extra: list[tuple[str, str]] | None = None) -> dict[str, int] | None:
    params = [("taxonKey", str(chave)), ("country", "BR"), ("hasCoordinate", "true"), ("hasGeospatialIssue", "false"),
              ("occurrenceStatus", "PRESENT"), ("facet", "gadmLevel2Gid"), ("facetLimit", "7000"), ("limit", "0")]
    params += [("basisOfRecord", b) for b in BASES] + (extra or [])
    for tentativa in range(6):
        ritmo.esperar()
        try:
            r = cli.get(GBIF, params=params)
        except httpx.HTTPError:
            time.sleep(2 ** tentativa)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60, float(r.headers.get("Retry-After", 2 ** (tentativa + 1)))))
            continue
        if r.status_code != 200:
            return None
        fac = (r.json().get("facets") or [])
        return {c["name"]: c["count"] for f in fac for c in f["counts"]} if fac else {}
    return None


# registros cuja coordenada é o CENTROIDE de um país, estado ou município (sem local real). O GBIF calcula a distância ao centroide mais próximo;
# até 5 km o ponto é tratado como "de centroide" e sai da conta. Sem isso, São José do Xingu (MT), onde fica o centroide do Brasil, aparecia com 347 plantas.
CENTROIDE_M = "0,5000"
# O GBIF não marca todos como centroide: um banco de sementes publicou ~21 mil registros no ponto exato do centroide do Brasil (-10,8339; -52,8731),
# que cai em São José do Xingu (MT). Uma caixa de ~20 x 40 km em volta do centroide do país pega esses (e quase tudo que o GBIF tem naquele município).
CAIXA_BRASIL = [("decimalLatitude", "-10.9,-10.7"), ("decimalLongitude", "-53.1,-52.7")]


def _municipios_de_centroide() -> list[str]:
    """Municípios (GADM nível 2) que concentram registros de centroide, de qualquer espécie: no país todo são poucos (o do centroide do Brasil e os de estado)."""
    cli = httpx.Client(headers=UA, timeout=120, follow_redirects=True)
    for t in range(6):
        try:
            r = cli.get(GBIF, params=[("country", "BR"), ("hasCoordinate", "true"), ("limit", "0"), ("facet", "gadmLevel2Gid"), ("facetLimit", "300"),
                                      ("distanceFromCentroidInMeters", CENTROIDE_M)])
            if r.status_code == 200:
                fac = r.json().get("facets") or []
                return sorted({c["name"] for f in fac for c in f["counts"] if c["name"].startswith("BRA.")})
        except httpx.HTTPError:
            pass
        time.sleep(3 * (t + 1))
    raise SystemExit("GBIF não respondeu à lista de centroides")


def coletar(tipo: str, centroide: bool = False, caixa: bool = False) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    centroide = centroide or caixa
    arq = CACHE / (f"{tipo}_caixa.json" if caixa else f"{tipo}_centroide.json" if centroide else f"{tipo}.json")
    feito = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    _, chaves, _ = _arquivo_lista(tipo)
    suspeitos: list[str] = []
    if centroide:
        total = json.loads((CACHE / f"{tipo}.json").read_text(encoding="utf-8"))
        suspeitos = _municipios_de_centroide()
        print(f"municípios com registros de centroide no Brasil: {suspeitos}", flush=True)
        # só as espécies que têm registro em algum desses municípios: nos outros não há o que descontar
        chaves = {n: k for n, k in chaves.items() if any(g in (total.get(n) or {}) for g in suspeitos)}
    falta = [(n, k) for n, k in chaves.items() if n not in feito and k]
    print(f"{tipo}{' (caixa)' if caixa else ' (centroides)' if centroide else ''}: {len(feito)} já feitas, {len(falta)} a fazer", flush=True)
    cli = httpx.Client(headers=UA, timeout=90, follow_redirects=True)
    ritmo = _Ritmo(0.3)
    trava = threading.Lock()
    contador = {"n": 0, "falhas": 0}
    filtro = CAIXA_BRASIL if caixa else [("distanceFromCentroidInMeters", CENTROIDE_M)]
    extra = (filtro + [("gadmLevel2Gid", g) for g in suspeitos]) if centroide else None

    def uma(par):
        nome, chave = par
        res = _consultar(cli, ritmo, int(chave), extra)
        with trava:
            if res is None:
                contador["falhas"] += 1
            else:
                feito[nome] = res
            contador["n"] += 1
            if contador["n"] % 100 == 0:
                arq.write_text(json.dumps(feito, separators=(",", ":")), encoding="utf-8")
                print(f"  {contador['n']}/{len(falta)} (falhas: {contador['falhas']})", flush=True)

    with ThreadPoolExecutor(max_workers=int(os.environ.get("ESPECIES_THREADS", "3"))) as ex:
        list(ex.map(uma, falta))
    arq.write_text(json.dumps(feito, separators=(",", ":")), encoding="utf-8")
    print(f"{tipo}{' (caixa)' if caixa else ' (centroides)' if centroide else ''}: pronto, {len(feito)} espécies no cache, {contador['falhas']} falhas", flush=True)


# ---------------------------------------------------------------- 3) soma por município
def _nomes() -> dict[str, tuple[str, str]]:
    cli = httpx.Client(headers=UA, timeout=120, follow_redirects=True)
    out = {}
    for m in _json(cli, IBGE_NOMES):
        mi = m.get("microrregiao") or {}
        uf = ((mi.get("mesorregiao") or {}).get("UF") or {}).get("sigla") or (((m.get("regiao-imediata") or {}).get("regiao-intermediaria") or {}).get("UF") or {}).get("sigla")
        out[str(m["id"])] = (m["nome"], uf or "")
    return out


def _bloco(tipo: str, mapa: dict[str, str], nomes: dict[str, tuple[str, str]]) -> dict:
    d, chaves, g_idx = _arquivo_lista(tipo)
    arq = CACHE / f"{tipo}.json"
    cache = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    arq_c = CACHE / f"{tipo}_centroide.json"
    centro = json.loads(arq_c.read_text(encoding="utf-8")) if arq_c.exists() else {}
    arq_x = CACHE / f"{tipo}_caixa.json"
    caixa = json.loads(arq_x.read_text(encoding="utf-8")) if arq_x.exists() else {}
    grupos = list(d["totais"]["por_grupo"].keys())
    pos = {g: i for i, g in enumerate(grupos)}
    por_mun: dict[str, list[int]] = {}
    com_registro = 0
    for e in d["especies"]:
        nome, g = e[0], e[g_idx]
        regs = cache.get(nome)
        if not regs or g not in pos:
            continue
        a, b = centro.get(nome) or {}, caixa.get(nome) or {}
        desc = {g: max(a.get(g, 0), b.get(g, 0)) for g in {*a, *b}}      # os dois descontos se sobrepõem: vale o maior, nunca a soma
        # registros de centroide saem; o município só conta se sobrar ao menos um registro com coordenada de verdade
        cods = {mapa[gid] for gid, n in regs.items() if gid in mapa and n - desc.get(gid, 0) > 0}
        if not cods:
            continue
        com_registro += 1
        for c in cods:
            por_mun.setdefault(c, [0] * len(grupos))[pos[g]] += 1
    top = {}
    for rotulo, sel in [("", range(len(grupos)))] + [(g, [i]) for i, g in enumerate(grupos)]:
        lista = sorted(((sum(v[i] for i in sel), c) for c, v in por_mun.items()), reverse=True)[:12]
        top[rotulo] = [[c, nomes.get(c, ("", ""))[0], nomes.get(c, ("", ""))[1], n] for n, c in lista if n > 0]
    return {"grupos": grupos, "especies": len(d["especies"]), "com_registro": com_registro, "municipios": por_mun, "top": top}


def agregar() -> None:
    mapa = json.loads(MAPA.read_text(encoding="utf-8"))
    nomes = _nomes()
    out = {
        "fonte": "GBIF.org (ocorrências com coordenada) + IBGE (municípios) + MMA (lista oficial de espécies ameaçadas, 2026)",
        "metodo": ("Para cada espécie da lista, contamos os municípios onde o GBIF tem ao menos um registro com coordenada (observações e "
                   "coletas; sem exemplar cultivado nem fóssil; sem os registros cuja coordenada é o centroide do país ou de um estado, a menos de 5 km, nem os do ponto padrão do centroide do Brasil). O mapa mostra quantas espécies diferentes têm registro em cada município. "
                   "O GBIF reflete onde há mais gente observando: município com muitos registros pode ter mais espécies só por ser mais estudado, "
                   "e município sem registro não quer dizer que a espécie não vive lá."),
        "gerado_em": date.today().isoformat(),
        "animais": _bloco("animais", mapa, nomes),
        "plantas": _bloco("plantas", mapa, nomes),
    }
    SAIDA.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for k in ("animais", "plantas"):
        b = out[k]
        print(f"{k}: {b['com_registro']} de {b['especies']} espécies com registro; {len(b['municipios'])} municípios → {SAIDA.name}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "mapear":
        mapear()
    elif cmd == "coletar":
        for t in (sys.argv[2:] or ["animais", "plantas"]):
            coletar(t)
    elif cmd == "coletar-caixa":
        for t in (sys.argv[2:] or ["animais", "plantas"]):
            coletar(t, caixa=True)
    elif cmd == "coletar-centroides":
        for t in (sys.argv[2:] or ["animais", "plantas"]):
            coletar(t, centroide=True)
    elif cmd == "agregar":
        agregar()
    else:
        print(__doc__)
