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
    # Banco Central: cada série, 1 ano (na 3ª coleta só 3 das 12 vieram)
    from datetime import date, timedelta
    fim = date.today()
    ini = fim - timedelta(days=365)
    for nome, cod in (("selic", 432), ("ipca_mes", 433), ("ipca_12m", 13522), ("dolar", 1), ("desemprego", 24369),
                      ("divida_bruta_pib", 13762), ("divida_liquida_pib", 4513), ("juros_nominais_pib", 5727),
                      ("pib_12m", 4382), ("endividamento_familias", 29037), ("inadimplencia_pf", 21084),
                      ("inadimplencia_pj", 21083)):
        ver(f"bcb {nome} ({cod})", f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados",
            {"formato": "json", "dataInicial": f"{ini:%d/%m/%Y}", "dataFinal": f"{fim:%d/%m/%Y}"}, n=160)
    ver("bcb selic 9 anos", "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados",
        {"formato": "json", "dataInicial": f"{fim - timedelta(days=365 * 9):%d/%m/%Y}", "dataFinal": f"{fim:%d/%m/%Y}"}, n=120)

    # CNPJ em sequência (na coleta, só 3 de ~30 vieram em 20 min)
    docs = ['17872922000191', '41391511000169', '13873535000119', '37257843000188', '00360305000104', '26756984000129',
            '26921551000181', '02155735000110', '03021021000181', '20999087000160', '43805419000123', '29974747000122']
    for d in docs:
        ver(f"brasilapi {d}", f"https://brasilapi.com.br/api/cnpj/v1/{d}", n=120)
        ver(f"minhareceita {d}", f"https://minhareceita.org/{d}", n=120)
        time.sleep(1.5)


if __name__ == "__main__":
    main()
