"""Ajustes pós-robô #112: erros 400 do WFS do TerraBrasilis (camadas e limite de feições) e tabelas de rendimento do SIDRA. Saída curta."""
import re

import httpx

cli = httpx.Client(timeout=180, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0", "Accept": "*/*"})
WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
r = cli.get(WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"})
nomes = sorted(set(re.findall(r"<(?:wfs:)?Name>([^<]+)</(?:wfs:)?Name>", r.text)))
print("CAMADAS prodes/deter:", [n for n in nomes if re.search(r"prodes|deter", n, re.I)], flush=True)
for camada in ("prodes-amazon-nb:yearly_deforestation_biome", "prodes-caatinga-nb:yearly_deforestation", "deter-amz:deter_amz"):
    r = cli.get(WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada, "resultType": "hits"})
    print(camada, "hits:", r.status_code, re.findall(r'numberMatched="(\d+)"', r.text), r.text[:240].replace("\n", " "), flush=True)
    r = cli.get(WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": camada, "outputFormat": "csv", "count": 2})
    print("  csv:", r.status_code, r.text[:500].replace("\n", " | "), flush=True)
for t, v in (("5436", ""), ("6387", ""), ("6381", ""), ("5434", "")):
    r = cli.get(f"https://apisidra.ibge.gov.br/values/t/{t}/n3/11/p/last%201" + (f"/v/{v}" if v else ""))
    print("SIDRA", t, r.status_code, r.text[:700].replace("\n", " "), flush=True)
print("fim", flush=True)
