"""Diagnóstico das fontes de meio ambiente (INPE: PRODES/DETER no TerraBrasilis e queimadas). Roda no GitHub Actions (diag-ambiente.yml)."""
import re

import httpx

cli = httpx.Client(timeout=180, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0", "Accept": "*/*"})
WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"


def get(u, params=None):
    try:
        r = cli.get(u, params=params)
        print(f"\n=== {r.url}: HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes", flush=True)
        return r
    except Exception as e:
        print(f"\n=== {u}: ERRO {type(e).__name__} {e}", flush=True)


r = get(WFS, {"service": "WFS", "request": "GetCapabilities"})
nomes = re.findall(r"<(?:wfs:)?Name>([^<]+)</(?:wfs:)?Name>", r.text) if r is not None else []
print(len(nomes), "camadas", flush=True)
interesse = [n for n in nomes if re.search(r"yearly|state|estado|uf|rate|taxa|accum|prodes|deter", n, re.I)]
for n in interesse[:120]:
    print("  ", n, flush=True)
for n in [x for x in interesse if re.search(r"yearly|state|rate", x, re.I)][:6]:
    g = get(WFS, {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": n, "outputFormat": "application/json", "count": 3})
    if g is not None and g.status_code == 200:
        print(g.text[:900], flush=True)
for u in ("https://dataserver-coids.inpe.br/queimadas/queimadas/", "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/",
          "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/", "https://dataserver-coids.inpe.br/queimadas/queimadas/estatisticas/"):
    g = get(u)
    if g is not None and g.status_code == 200:
        print("  ", re.findall(r'href="([^"?]+)"', g.text)[:30], flush=True)
print("fim", flush=True)
