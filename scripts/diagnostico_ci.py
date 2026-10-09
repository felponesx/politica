"""Mostra amostras das respostas brutas das fontes (roda no GitHub Actions: .github/workflows/diagnostico.yml).

Serve para conferir formato, tempo de resposta e bloqueios quando um coletor falha, antes de corrigir o código.
"""
import io
import time
import zipfile

import httpx

UA_NAV = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0 Safari/537.36")
cli = httpx.Client(timeout=90, follow_redirects=True, headers={"User-Agent": "BRASIL+ coletor (transparencia)"})


def ver(nome, url, params=None, headers=None, n=1200, metodo="GET"):
    t = time.monotonic()
    try:
        r = cli.request(metodo, url, params=params, headers=headers or {})
        print(f"\n=== {nome}: HTTP {r.status_code} | {r.headers.get('content-type')} | {len(r.content)} bytes | "
              f"{time.monotonic() - t:.1f}s | {r.url}", flush=True)
        if metodo == "GET":
            print(r.text[:n], flush=True)
        else:
            print({k: v for k, v in r.headers.items() if k.lower() in ("content-length", "last-modified")})
        return r
    except Exception as e:
        print(f"\n=== {nome}: ERRO {type(e).__name__}: {e} ({time.monotonic() - t:.1f}s)", flush=True)
        return None


def main():
    cam = "https://dadosabertos.camara.leg.br/api/v2"
    r = ver("camara deputados", f"{cam}/deputados", {"itens": 2}, n=400)
    dep = r.json()["dados"][0]["id"] if r is not None and r.status_code == 200 else 204554
    for ano in (2026, 2025):
        ver(f"camara despesas {ano}", f"{cam}/deputados/{dep}/despesas", {"ano": ano, "itens": 3}, n=900)
    ver("camara despesas sem ano", f"{cam}/deputados/{dep}/despesas", {"itens": 3}, n=900)
    ver("camara votos 404", f"{cam}/votacoes/2024320-94/votos", n=300)

    rec = "https://www.gov.br/receitafederal/dados/arrecadacao-estado.csv"
    ver("receita csv (UA coletor)", rec, n=300)
    ver("receita csv (UA navegador)", rec, headers={"User-Agent": UA_NAV}, n=600)
    pag = ver("receita pagina dados abertos",
              "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/receitadata/arrecadacao",
              headers={"User-Agent": UA_NAV}, n=0)
    if pag is not None:
        import re
        links = sorted(set(re.findall(r'href="([^"]+)"', pag.text)))
        print("\n".join(l for l in links if any(p in l.lower() for p in ("arrecad", ".csv", ".zip", "estado"))))

    ck = ver("capag ckan", "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show",
             {"id": "capag-municipios"}, n=0)
    if ck is not None and ck.status_code == 200:
        res = ck.json()["result"]["resources"]
        for x in res:
            print(x.get("format"), x.get("last_modified") or x.get("created"), x.get("name"), x.get("url"))
        bons = [x for x in res if str(x.get("format", "")).upper() in ("CSV", "XLSX")]
        bons.sort(key=lambda x: x.get("last_modified") or x.get("created") or "")
        if bons:
            u = bons[-1]["url"]
            a = cli.get(u)
            print(f"\n--- capag arquivo {u}: HTTP {a.status_code}, {len(a.content)} bytes")
            if u.lower().endswith(".xlsx"):
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(a.content), read_only=True, data_only=True)
                for i, l in enumerate(wb.worksheets[0].iter_rows(values_only=True)):
                    print(l[:14])
                    if i > 12:
                        break
            else:
                txt = a.content.decode("utf-8-sig", errors="replace")
                print("\n".join(txt.splitlines()[:14]))

    ver("lexml sru", "https://www.lexml.gov.br/busca/SRU",
        {"operation": "searchRetrieve", "version": "1.1", "query": 'urn any "br;sao.paulo:estadual" and date any "2026"',
         "startRecord": 1, "maximumRecords": 3}, headers={"Accept": "application/xml"}, n=1500)
    ver("lexml sru (simples)", "https://www.lexml.gov.br/busca/SRU",
        {"operation": "searchRetrieve", "version": "1.1", "query": "localidade=\"sao.paulo\"", "maximumRecords": 2}, n=1500)

    pn = "https://pncp.gov.br/api/consulta/v1/contratos"
    r = ver("pncp 1 dia (500)", pn, {"dataInicial": "20261001", "dataFinal": "20261001", "pagina": 1, "tamanhoPagina": 500}, n=0)
    if r is not None and r.status_code == 200:
        j = r.json()
        print({k: j.get(k) for k in ("totalRegistros", "totalPaginas", "numeroPagina", "paginasRestantes", "empty")})
    r = ver("pncp 7 dias (500)", pn, {"dataInicial": "20261001", "dataFinal": "20261007", "pagina": 1, "tamanhoPagina": 500}, n=0)
    if r is not None and r.status_code == 200:
        j = r.json()
        print({k: j.get(k) for k in ("totalRegistros", "totalPaginas")})

    ver("brasilapi cnpj (UA coletor)", "https://brasilapi.com.br/api/cnpj/v1/00000000000191", n=300)
    ver("brasilapi cnpj (UA navegador)", "https://brasilapi.com.br/api/cnpj/v1/00000000000191", headers={"User-Agent": UA_NAV}, n=300)
    ver("receitaws cnpj", "https://receitaws.com.br/v1/cnpj/00000000000191", n=300)
    ver("minhareceita cnpj", "https://minhareceita.org/00000000000191", n=300)

    ver("almg deputados", "https://dadosabertos.almg.gov.br/ws/deputados/em_exercicio", {"formato": "json"}, n=900)

    for ano in (2022, 2024):
        ver(f"tse candidatos {ano}", f"https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip", metodo="HEAD")
        ver(f"tse votacao munzona {ano}",
            f"https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip", metodo="HEAD")
    z = cli.get("https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip")
    if z.status_code == 200:
        with zipfile.ZipFile(io.BytesIO(z.content)) as arq:
            nomes = arq.namelist()
            print("arquivos no zip de candidatos 2022:", nomes[:40])


if __name__ == "__main__":
    main()
