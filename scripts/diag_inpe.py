"""Diagnóstico do INPE/TerraBrasilis e do MapBiomas Alerta: onde estão os arquivos de PRODES (Cerrado, Caatinga, Mata Atlântica) e se o MapBiomas responde sem login. Saída curta."""
import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
cli = httpx.Client(timeout=60, follow_redirects=True, headers=UA)


def get(url, **kw):
    try:
        r = cli.get(url, **kw)
        print("GET", url[:110], r.status_code, len(r.content), r.headers.get("content-type"), flush=True)
        return r
    except Exception as e:
        print("GET", url[:110], "ERRO", type(e).__name__, str(e)[:80], flush=True)


app = get("https://terrabrasilis.dpi.inpe.br/downloads/")
achados = set()
if app is not None and app.status_code == 200:
    js = re.findall(r'(?:src|href)="([^"]+\.js)"', app.text)
    print("scripts:", js[:8], flush=True)
    for s in js[:6]:
        u = s if s.startswith("http") else "https://terrabrasilis.dpi.inpe.br/downloads/" + s.lstrip("./")
        r = get(u)
        if r is not None and r.status_code == 200:
            achados |= set(re.findall(r'[\w./:-]*(?:download/dataset|api/v\d|prodes)[\w./:?=&%-]*', r.text))
    print("padrões nos scripts:", sorted(achados)[:40], flush=True)
for caminho in ("assets/config.json", "assets/config/config.json", "config.json", "api/datasets", "api/v1/datasets"):
    get("https://terrabrasilis.dpi.inpe.br/downloads/" + caminho)
for ds in ("cerrado-prodes", "caatinga-prodes", "mata-atlantica-prodes", "pampa-prodes", "pantanal-prodes", "amz-prodes"):
    for f in ("vector/yearly_deforestation_biome.zip", "vector/yearly_deforestation.zip", "vector/yearly_deforestation_biome_shp.zip", "raster/", "vector/", ""):
        r = get(f"https://terrabrasilis.dpi.inpe.br/download/dataset/{ds}/{f}", headers={"Range": "bytes=0-300"})
        if r is not None and r.status_code in (200, 206) and "html" in (r.headers.get("content-type") or ""):
            print("   html:", re.sub(r"\s+", " ", r.text[:200]), flush=True)
# MapBiomas Alerta
get("https://plataforma.alerta.mapbiomas.org/api/docs/index.html")
try:
    r = cli.post("https://plataforma.alerta.mapbiomas.org/api/v2/graphql", json={"query": "{ __typename }"})
    print("MAPBIOMAS graphql", r.status_code, r.text[:200], flush=True)
except Exception as e:
    print("MAPBIOMAS graphql ERRO", type(e).__name__, str(e)[:100], flush=True)
print("fim", flush=True)
