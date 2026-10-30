"""Diagnóstico das fontes de meio ambiente (INPE queimadas e desmatamento, IBAMA). Roda no GitHub Actions (diag-ambiente.yml)."""
import io
import re
import zipfile

import httpx

cli = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0", "Accept": "*/*"})


def ver(u, n=600, texto=True):
    try:
        r = cli.get(u)
        print(f"\n=== {u}: HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes", flush=True)
        if texto and r.status_code == 200:
            print(r.text[:n], flush=True)
        return r
    except Exception as e:
        print(f"\n=== {u}: ERRO {type(e).__name__} {e}", flush=True)


for u in ("https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/focos_mensal_br_202609.csv",
          "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/focos_mensal_br_202509.csv"):
    r = ver(u, 700)
for u in ("https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_todos_sats/",
          "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/"):
    r = ver(u, 200, False)
    if r is not None and r.status_code == 200:
        nomes = re.findall(r'href="([^"]+\.(?:csv|zip))"', r.text)
        print("  arquivos:", len(nomes), nomes[:3], nomes[-6:], flush=True)
for u in ("https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/", "https://terrabrasilis.dpi.inpe.br/downloads/",
          "https://terrabrasilis.dpi.inpe.br/api/v1/", "http://terrabrasilis.dpi.inpe.br/app/map/deforestation?hl=pt-br",
          "https://terrabrasilis.dpi.inpe.br/geonetwork/srv/api/records/", "https://www.gov.br/inpe/pt-br/acesso-a-informacao/dados-abertos",
          "https://dadosabertos.ibama.gov.br/", "https://dadosabertos.ibama.gov.br/dados/SICAFI/", "https://servicos.ibama.gov.br/ctf/publico/areasembargadas/ConsultaPublicaAreasEmbargadas.php"):
    r = ver(u, 300, False)
    if r is not None and r.status_code == 200:
        hrefs = list(dict.fromkeys(re.findall(r"""href=["']([^"']+)["']""", r.text)))
        arq = [h for h in hrefs if re.search(r"\.(zip|csv|xlsx?|json|geojson|shp)\b|prodes|deter|desmat|queimad|infrac|autos|embarg", h, re.I)]
        print(f"  {len(hrefs)} links, {len(arq)} de interesse", flush=True)
        for h in arq[:40]:
            print("   ", h, flush=True)
print("fim", flush=True)
