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
    # cota parlamentar da Câmara: arquivos anuais (a API /deputados/{id}/despesas responde vazio)
    for u in ("https://www.camara.leg.br/cotas/Ano-2026.csv.zip", "http://www.camara.leg.br/cotas/Ano-2026.csv.zip",
              "https://www.camara.leg.br/cotas/Ano-2026.json.zip"):
        ver(f"ceap {u}", u, metodo="HEAD")
    z = cli.get("https://www.camara.leg.br/cotas/Ano-2026.csv.zip")
    print("ceap zip:", z.status_code, len(z.content))
    if z.status_code == 200:
        with zipfile.ZipFile(io.BytesIO(z.content)) as arq:
            print(arq.namelist())
            nome = arq.namelist()[0]
            with arq.open(nome) as f:
                bruto = f.read(4000)
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    print(enc, "\n" + bruto.decode(enc)[:2500])
                    break
                except UnicodeDecodeError:
                    pass
    ver("tse votacao munzona 2018", "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/"
        "votacao_candidato_munzona_2018.zip", metodo="HEAD")


if __name__ == "__main__":
    main()
