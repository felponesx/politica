"""Diagnóstico das camadas de desmatamento do TerraBrasilis (PRODES/DETER). Roda no GitHub Actions (diag-ambiente.yml)."""
import re

import httpx

cli = httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0", "Accept": "*/*"})
WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
CAMADAS = ["prodes-legal-amz:yearly_deforestation", "prodes-amazon-nb:yearly_deforestation_biome", "prodes-cerrado-nb:yearly_deforestation",
           "prodes-caatinga-nb:yearly_deforestation", "prodes-mata-atlantica-nb:yearly_deforestation", "prodes-pantanal-nb:yearly_deforestation",
           "prodes-pampa-nb:yearly_deforestation", "deter-amz:deter_amz", "deter-cerrado-nb:deter_cerrado"]


def get(params):
    try:
        r = cli.get(WFS, params=params)
        print(f"\n=== {r.url[:160]}: HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes", flush=True)
        return r
    except Exception as e:
        print(f"\n=== ERRO {type(e).__name__} {e}", flush=True)


for c in CAMADAS:
    d = get({"service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType", "typeNames": c})
    if d is not None and d.status_code == 200:
        print("  campos:", re.findall(r'name="([^"]+)" type="([^"]+)"', d.text)[:30], flush=True)
    h = get({"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": c, "resultType": "hits"})
    if h is not None and h.status_code == 200:
        print("  total:", re.findall(r'numberMatched="(\d+)"', h.text), flush=True)
    g = get({"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": c, "outputFormat": "application/json", "count": 4})
    if g is not None and g.status_code == 200:
        try:
            for f in g.json()["features"]:
                print("   ", {k: v for k, v in f["properties"].items()}, flush=True)
        except Exception as e:
            print("  json:", e, g.text[:200], flush=True)
print("fim", flush=True)
