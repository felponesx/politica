"""Diagnóstico das fontes de meio ambiente (INPE queimadas e desmatamento). Roda no GitHub Actions (diag-ambiente.yml)."""
import re

import httpx

cli = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0", "Accept": "*/*"})


def ver(u, n=300, texto=True):
    try:
        r = cli.get(u)
        print(f"\n=== {u}: HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes", flush=True)
        if texto and r.status_code == 200:
            print(r.text[:n], flush=True)
        return r
    except Exception as e:
        print(f"\n=== {u}: ERRO {type(e).__name__} {e}", flush=True)


def achar(r, extra=r"api|json|csv|estatist|dados|prodes|taxa"):
    if r is None or r.status_code != 200:
        return
    t = r.text
    urls = sorted(set(re.findall(r"""["'(]((?:https?:)?//[^"'()\s<>]+|/[A-Za-z0-9_\-./?=&%]+\.(?:json|csv|js)[^"'()\s<>]*)""", t)))
    chave = [u for u in urls if re.search(extra, u, re.I)]
    print(f"  {len(urls)} urls no texto, {len(chave)} de interesse", flush=True)
    for u in chave[:60]:
        print("   ", u, flush=True)


for u in ("https://data.inpe.br/queimadas/estatisticas/", "https://data.inpe.br/queimadas/estatisticas/?tipo=estados",
          "https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/", "https://terrabrasilis.dpi.inpe.br/dashboard/",
          "https://terrabrasilis.dpi.inpe.br/", "http://terrabrasilis.dpi.inpe.br/app/map/deforestation?hl=pt-br"):
    achar(ver(u, 200, False))
for u in ("https://terrabrasilis.dpi.inpe.br/dashboard/api/v1/redis-cli/prodes-amazon-nb/yearly_deforestation_state?",
          "https://terrabrasilis.dpi.inpe.br/dashboard/api/v1/redis-cli/prodes-amazon-nb/yearly_deforestation?",
          "https://terrabrasilis.dpi.inpe.br/dashboard/api/v1/redis-cli/deter-amazon/",
          "https://terrabrasilis.dpi.inpe.br/geoserver/ows?service=WFS&request=GetCapabilities",
          "https://data.inpe.br/queimadas/estatisticas/api/estados", "https://data.inpe.br/queimadas/estatisticas/dados"):
    ver(u, 500)
print("fim", flush=True)
