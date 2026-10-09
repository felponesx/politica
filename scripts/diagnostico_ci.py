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


def inicio_zip(nome, url, mb=4):
    """Baixa só o começo de um zip grande e mostra os nomes dos arquivos e as primeiras linhas."""
    t = time.monotonic()
    try:
        with cli.stream("GET", url) as r:
            print(f"\n=== {nome}: HTTP {r.status_code} | {r.headers.get('content-length')} bytes | "
                  f"{r.headers.get('last-modified')} | {r.url}", flush=True)
            if r.status_code != 200:
                return
            buf = b""
            for parte in r.iter_bytes():
                buf += parte
                if len(buf) > mb * 1024 * 1024:
                    break
        print(f"  {len(buf)} bytes em {time.monotonic() - t:.1f}s", flush=True)
        # zip local header: nome do primeiro arquivo e começo descomprimido
        import zlib
        if buf[:4] == b"PK\x03\x04":
            nlen = int.from_bytes(buf[26:28], "little")
            elen = int.from_bytes(buf[28:30], "little")
            print("  primeiro arquivo:", buf[30:30 + nlen].decode("latin-1"), flush=True)
            dados = zlib.decompressobj(-15).decompress(buf[30 + nlen + elen:], 3000)
            print(dados.decode("latin-1")[:1500], flush=True)
    except Exception as e:
        print(f"\n=== {nome}: ERRO {type(e).__name__}: {e} ({time.monotonic() - t:.1f}s)", flush=True)


def main():
    # TSE 2026: arquivos de dados abertos e o serviço de divulgação de resultados
    for nome in ("consulta_cand/consulta_cand_2026.zip", "votacao_candidato_munzona/votacao_candidato_munzona_2026.zip",
                 "votacao_partido_munzona/votacao_partido_munzona_2026.zip",
                 "detalhe_votacao_munzona/detalhe_votacao_munzona_2026.zip"):
        ver(f"tse {nome}", f"https://cdn.tse.jus.br/estatistica/sead/odsele/{nome}", metodo="HEAD")
    r = ver("tse resultados config", "https://resultados.tse.jus.br/oficial/comum/config/ele-c.json", n=4000)
    if r is not None and r.status_code == 200:
        try:
            j = r.json()
            for c in j.get("c", []):
                for e in c.get("e", []):
                    print("  eleicao:", c.get("ele"), c.get("cd"), e.get("cd"), e.get("nm"), e.get("t"), e.get("dt"))
        except Exception as e:
            print("  json?", e)
    for cod in ("544", "546", "619", "620", "621"):
        ver(f"tse ele2022 presidente {cod}", f"https://resultados.tse.jus.br/oficial/ele2022/{cod}/dados-simplificados/br/"
            f"br-c0001-e000{cod}-r.json", n=300)
    ver("tse ele2026 lista", "https://resultados.tse.jus.br/oficial/ele2026/", n=600)
    ver("tse dados abertos 2026", "https://dadosabertos.tse.jus.br/dataset/?q=2026", n=600)

    # Receita: base aberta do CNPJ (situação especial = recuperação judicial)
    for url in ("https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/",
                "https://dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/",
                "https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9",
                "https://dados.gov.br/api/publico/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj"):
        r = ver(f"receita cnpj {url}", url, n=2500)
    r = cli.get("https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/")
    if r.status_code == 200:
        import re
        meses = sorted(set(re.findall(r'href="(\d{4}-\d{2})/"', r.text)))
        print("meses:", meses[-5:], flush=True)
        if meses:
            base = f"https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/{meses[-1]}/"
            ver("receita cnpj mes", base, n=3000)
            inicio_zip("receita estabelecimentos0", base + "Estabelecimentos0.zip")
            inicio_zip("receita empresas0", base + "Empresas0.zip", mb=2)


if __name__ == "__main__":
    main()
