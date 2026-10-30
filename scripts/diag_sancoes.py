"""Diagnóstico das bases de sanções (CEIS, CNEP, lista suja do trabalho escravo, TCU). Roda no GitHub Actions (diag-sancoes.yml)."""
import csv
import io
import re
import zipfile
from datetime import date, timedelta

import httpx

cli = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0", "Accept": "*/*"})


def ver(u, n=500):
    try:
        r = cli.get(u)
        print(f"\n=== {u}: HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes", flush=True)
        return r
    except Exception as e:
        print(f"\n=== {u}: ERRO {type(e).__name__} {e}", flush=True)


def csv_do_zip(r, linhas=4):
    z = zipfile.ZipFile(io.BytesIO(r.content))
    print("  zip:", [(i.filename, i.file_size) for i in z.infolist()], flush=True)
    for nome in z.namelist()[:2]:
        txt = z.read(nome)[:200_000].decode("latin-1")
        leitor = csv.reader(io.StringIO(txt), delimiter=";")
        for i, l in enumerate(leitor):
            if i > linhas:
                break
            print("   ", [c[:40] for c in l], flush=True)
        n = z.read(nome).count(b"\n")
        print(f"  {nome}: ~{n} linhas", flush=True)


for base in ("ceis", "cnep", "acordos-leniencia"):
    for d in range(0, 12):
        dia = date.today() - timedelta(days=d)
        u = f"https://portaldatransparencia.gov.br/download-de-dados/{base}/{dia:%Y%m%d}"
        r = ver(u)
        if r is not None and r.status_code == 200 and r.content[:2] == b"PK":
            csv_do_zip(r)
            break

for u in ("https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/combate-ao-trabalho-escravo-e-condicoes-analogas-a-de-escravo/cadastro-de-empregadores",
          "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/combate-ao-trabalho-escravo-e-condicoes-analogas-a-de-escravo/lista-suja",
          "https://sites.tcu.gov.br/dados-abertos/", "https://portal.tcu.gov.br/dados-abertos/", "https://contas.tcu.gov.br/ords/f?p=INABILITADOS:INICIAL",
          "https://dados-abertos.apps.tcu.gov.br/", "https://portal.tcu.gov.br/responsabilizacao-publica/"):
    r = ver(u)
    if r is not None and r.status_code == 200:
        hrefs = list(dict.fromkeys(re.findall(r"""href=["']([^"']+)["']""", r.text)))
        arq = [h for h in hrefs if re.search(r"\.(xlsx?|csv|zip|ods|json)\b|dados|inabilit|irregular|cadastro|lista", h, re.I)]
        print(f"  {len(hrefs)} links, {len(arq)} de interesse", flush=True)
        for h in arq[:50]:
            print("   ", h, flush=True)
print("fim", flush=True)
