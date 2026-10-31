"""Diagnóstico do extrato da Geofabrik e do limite municipal do IBGE, etapa por etapa (o robô alcança o que o ambiente do Claude não alcança). Saída curta."""
import time

import httpx

UA = {"User-Agent": "BRASIL+ coletor de dados publicos (contato: github.com/felponesx/politica)"}
G = "https://download.geofabrik.de/south-america"


def passo(nome, f):
    t = time.time()
    try:
        print(f"  {nome}: {f()} [{time.time() - t:.1f}s]", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  {nome}: ERRO {type(e).__name__} {str(e)[:100]} [{time.time() - t:.1f}s]", flush=True)


def head(u):
    r = httpx.head(u, headers=UA, timeout=30, follow_redirects=True)
    return f"HTTP {r.status_code} {r.headers.get('content-length')}B mod={r.headers.get('last-modified')} range={r.headers.get('accept-ranges')}"


print("== Geofabrik: HEAD de cada extrato")
for nome in ("brazil/norte", "brazil/nordeste", "brazil/centro-oeste", "brazil/sudeste", "brazil/sul", "brazil"):
    passo(nome, lambda n=nome: head(f"{G}/{n}-latest.osm.pbf"))
print("== Geofabrik: .md5 e primeiros 20 MB do norte (velocidade)")
passo("md5 norte", lambda: httpx.get(f"{G}/brazil/norte-latest.osm.pbf.md5", headers=UA, timeout=30, follow_redirects=True).text[:60])
passo("20MB norte", lambda: f"{len(httpx.get(f'{G}/brazil/norte-latest.osm.pbf', headers={**UA, 'Range': 'bytes=0-20971519'}, timeout=120, follow_redirects=True).content)} bytes")
print("== IBGE: limite do município (Palmas 1721000)")
base = "https://servicodados.ibge.gov.br/api/v3/malhas/municipios/1721000"
for q in ("?formato=application/vnd.geo%2Bjson&qualidade=maxima", "?formato=application/vnd.geo%2Bjson", "?formato=application/vnd.geo%2Bjson&qualidade=intermediaria"):
    passo("IBGE " + q[:60], lambda q=q: (lambda r: f"HTTP {r.status_code} {len(r.content)}B")(httpx.get(base + q, headers={**UA, "Accept": "*/*"}, timeout=90)))
passo("IBGE estados (usado pelo robô)", lambda: (lambda r: f"HTTP {r.status_code} {len(r.content)}B")(httpx.get("https://servicodados.ibge.gov.br/api/v3/malhas/estados/17?formato=application/vnd.geo+json&qualidade=minima", headers={**UA, "Accept": "*/*"}, timeout=90)))
