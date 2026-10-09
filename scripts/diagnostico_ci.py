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


def zip_remoto(nome, url, mostrar=(), linhas=6):
    """Lista um zip remoto sem baixar tudo (pedidos Range no diretório central) e mostra o começo de alguns arquivos."""
    import struct
    import zlib
    try:
        h = cli.head(url)
        tam = int(h.headers.get("content-length") or 0)
        print(f"\n=== {nome}: HTTP {h.status_code} | {tam} bytes | {h.headers.get('last-modified')}", flush=True)
        if h.status_code != 200 or not tam:
            return
        fim = cli.get(url, headers={"Range": f"bytes={max(0, tam - 262144)}-{tam - 1}"}).content
        k = fim.rfind(b"PK\x05\x06")
        n_ent, cd_tam, cd_ini = struct.unpack("<HII", fim[k + 10:k + 20])
        cd = cli.get(url, headers={"Range": f"bytes={cd_ini}-{cd_ini + cd_tam - 1}"}).content
        pos, entradas = 0, []
        while pos < len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
            comp, desc = struct.unpack("<II", cd[pos + 20:pos + 28])
            nl, el, cl = struct.unpack("<HHH", cd[pos + 28:pos + 34])
            off = struct.unpack("<I", cd[pos + 42:pos + 46])[0]
            nm = cd[pos + 46:pos + 46 + nl].decode("latin-1")
            entradas.append((nm, comp, desc, off))
            pos += 46 + nl + el + cl
        for nm, comp, desc, off in entradas[:80]:
            print(f"  {nm}  {comp} -> {desc}", flush=True)
        for nm, comp, desc, off in entradas:
            if not any(m in nm for m in mostrar):
                continue
            loc = cli.get(url, headers={"Range": f"bytes={off}-{off + 300000}"}).content
            nl, el = struct.unpack("<HH", loc[26:30])
            txt = zlib.decompressobj(-15).decompress(loc[30 + nl + el:], 200000).decode("latin-1")
            print(f"  --- {nm}:", flush=True)
            for l in txt.splitlines()[:linhas]:
                print("   ", l[:700], flush=True)
    except Exception as e:
        print(f"  ERRO {type(e).__name__}: {e}", flush=True)


def dav(nome, url, auth=None, n=4000):
    """PROPFIND num compartilhamento Nextcloud (é onde a Receita publica o CNPJ)."""
    try:
        r = cli.request("PROPFIND", url, auth=auth, headers={"Depth": "1"})
        import re
        itens = re.findall(r"<d:href>([^<]+)</d:href>", r.text)
        print(f"\n=== {nome}: HTTP {r.status_code} | {len(itens)} itens", flush=True)
        print("\n".join(itens[:60]) if itens else r.text[:n], flush=True)
        return itens
    except Exception as e:
        print(f"\n=== {nome}: ERRO {type(e).__name__}: {e}", flush=True)
        return []


def amostra_webdav(nome, url, auth, mb=6, procurar=None):
    """Começo de um zip grande do WebDAV: primeiras linhas e, se pedido, linhas que contêm `procurar`."""
    import struct
    import zlib
    t = time.monotonic()
    try:
        r = cli.get(url, auth=auth, headers={"Range": f"bytes=0-{mb * 1024 * 1024}"})
        buf = r.content
        print(f"\n=== {nome}: HTTP {r.status_code} | {len(buf)} bytes em {time.monotonic() - t:.1f}s "
              f"({len(buf) / 1e6 / max(time.monotonic() - t, 0.01):.1f} MB/s)", flush=True)
        nl, el = struct.unpack("<HH", buf[26:30])
        print("  arquivo:", buf[30:30 + nl].decode("latin-1"), flush=True)
        txt = zlib.decompressobj(-15).decompress(buf[30 + nl + el:]).decode("latin-1")
        linhas = txt.splitlines()[:-1]
        print(f"  {len(linhas)} linhas descomprimidas", flush=True)
        for l in linhas[:3]:
            print("   ", l[:400], flush=True)
        if procurar:
            achou = [l for l in linhas if not l.endswith(';"";""')]
            print(f"  linhas com situação especial: {len(achou)}", flush=True)
            for l in achou[:12]:
                print("   ", l[:400], flush=True)
    except Exception as e:
        print(f"  ERRO {type(e).__name__}: {e}", flush=True)


def links(nome, url, padrao=r'href="([^"]+\.(?:csv|xlsx?|zip|json|ods)[^"]*)"', n=60, headers=None):
    """Página HTML: mostra os links para arquivos de dados."""
    import re
    r = ver(nome, url, n=300, headers=headers)
    if r is not None and r.status_code == 200:
        achados = list(dict.fromkeys(re.findall(padrao, r.text, re.I)))
        print(f"  {len(achados)} links", flush=True)
        for a in achados[:n]:
            print("   ", a, flush=True)
    return r


def ckan(nome, base, consulta):
    """Busca num CKAN (dados.mj.gov.br etc.) e lista os recursos de cada conjunto."""
    r = ver(nome, f"{base}/api/3/action/package_search", {"q": consulta, "rows": 8}, n=200)
    try:
        for p in r.json()["result"]["results"]:
            print(f"  ## {p['name']} | {p.get('title')} | {p.get('metadata_modified')}", flush=True)
            for rec in p.get("resources", [])[:25]:
                print(f"     - {rec.get('name')} | {rec.get('format')} | {rec.get('url')}", flush=True)
    except Exception as e:
        print("  json?", e, flush=True)


def planilha(nome, url, linhas=6, abas=80, headers=None):
    """Baixa uma planilha xlsx e mostra cada aba: nome, tamanho e as primeiras linhas."""
    import openpyxl
    t = time.monotonic()
    try:
        r = cli.get(url, headers=headers or {})
        print(f"\n=== {nome}: HTTP {r.status_code} | {len(r.content)} bytes | {time.monotonic() - t:.1f}s", flush=True)
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
        for ws in wb.worksheets[:abas]:
            print(f"  --- aba {ws.title!r} ({ws.max_row}x{ws.max_column})", flush=True)
            for k, row in enumerate(ws.iter_rows(values_only=True)):
                if k >= linhas:
                    break
                vals = [str(v)[:40] for v in row if v not in (None, "")]
                if vals:
                    print("     ", " | ".join(vals)[:400], flush=True)
    except Exception as e:
        print(f"  ERRO {type(e).__name__}: {e}", flush=True)


def inicio_csv(nome, url, kb=400, headers=None):
    t = time.monotonic()
    try:
        with cli.stream("GET", url, headers=headers or {}) as r:
            buf = b""
            for b in r.iter_bytes():
                buf += b
                if len(buf) > kb * 1024:
                    break
        print(f"\n=== {nome}: HTTP {r.status_code} | {r.headers.get('content-length')} bytes | {time.monotonic() - t:.1f}s", flush=True)
        txt = buf.decode("utf-8", "replace") if buf[:3] == b"\xef\xbb\xbf" else buf.decode("latin-1")
        linhas = txt.splitlines()
        cab = linhas[0].split(";")
        print(f"  {len(cab)} colunas", flush=True)
        for k, c in enumerate(cab):
            print(f"   [{k}] {c[:150]}", flush=True)
        for l in linhas[1:3]:
            print("  linha:", l[:3000], flush=True)
    except Exception as e:
        print(f"  ERRO {type(e).__name__}: {e}", flush=True)


def colunas_xlsx(nome, url, procurar, linhas_cab=6, max_abas=40, headers=None, mostrar_linhas=0):
    """Planilha grande: para cada aba, as colunas cujo cabeçalho casa com `procurar` (regex) e uma amostra."""
    import re
    import openpyxl
    t = time.monotonic()
    try:
        r = cli.get(url, headers=headers or {})
        print(f"\n=== {nome}: HTTP {r.status_code} | {len(r.content)} bytes | {time.monotonic() - t:.1f}s", flush=True)
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
        for ws in wb.worksheets[:max_abas]:
            cab = {}
            amostra = []
            for k, row in enumerate(ws.iter_rows(values_only=True)):
                if k < linhas_cab:
                    for c, v in enumerate(row):
                        if v not in (None, ""):
                            cab[c] = (cab.get(c, "") + " | " + str(v)).strip(" |")
                elif len(amostra) < 2:
                    amostra.append(row)
                if k < mostrar_linhas:
                    vals = [str(v)[:30] for v in row if v not in (None, "")]
                    if vals:
                        print("      ", " | ".join(vals)[:300], flush=True)
                if k >= max(linhas_cab + 2, mostrar_linhas):
                    break
            achou = [(c, h) for c, h in cab.items() if re.search(procurar, h, re.I)]
            print(f"  --- aba {ws.title!r} ({ws.max_row}x{ws.max_column}): {len(cab)} colunas, {len(achou)} casam", flush=True)
            for c, h in achou[:60]:
                ex = [str(a[c])[:20] if c < len(a) else "" for a in amostra]
                print(f"     [{c}] {h[:160]}  ex: {ex}", flush=True)
    except Exception as e:
        print(f"  ERRO {type(e).__name__}: {e}", flush=True)


def main():
    nav = {"User-Agent": UA_NAV}
    import openpyxl
    import re
    from collections import Counter

    def wb_de(url):
        r = cli.get(url, headers=nav)
        print(f"\n=== {url.rsplit('/', 3)[-3:]}: HTTP {r.status_code} | {len(r.content)} bytes", flush=True)
        return openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)

    # Sinesp (BancoVDE 2026): estrutura e eventos
    try:
        wb = wb_de("https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/estatistica/download/"
                   "dnsp-base-de-dados/bancovde-2026.xlsx/@@download/file")
        for ws in wb.worksheets:
            print(f"  --- aba {ws.title!r} ({ws.max_row}x{ws.max_column})", flush=True)
            cab, eventos, ufs, meses, n = None, Counter(), Counter(), Counter(), 0
            for k, row in enumerate(ws.iter_rows(values_only=True)):
                if k < 4:
                    print("     ", row, flush=True)
                if cab is None and row and any(isinstance(v, str) and re.search(r"evento|uf", v, re.I) for v in row if v):
                    cab = [str(v) for v in row]
                    continue
                if cab:
                    d = dict(zip(cab, row))
                    ev = next((d[c] for c in cab if re.search(r"evento", c, re.I)), None)
                    eventos[ev] += 1
                    uf = next((d[c] for c in cab if c.lower() in ("uf", "sigla_uf")), None)
                    ufs[uf] += 1
                    m = next((d[c] for c in cab if re.search(r"data|mes|m.s", c, re.I)), None)
                    meses[str(m)[:7]] += 1
                    n += 1
            print("  cabeçalho:", cab, "| linhas:", n, flush=True)
            print("  eventos:", eventos.most_common(60), flush=True)
            print("  ufs:", len(ufs), "| meses:", sorted(meses)[:3], sorted(meses)[-3:], flush=True)
    except Exception as e:
        print("  vde erro", type(e).__name__, e, flush=True)

    # ESTADIC 2023: dicionário da Segurança Pública (efetivos) e valores
    try:
        wb = wb_de("https://ftp.ibge.gov.br/Perfil_Estados/2023/Base_Estadic_2023.xlsx")
        dic = wb["Dicionário"]
        for row in dic.iter_rows(values_only=True):
            t = " | ".join(str(v) for v in row if v not in (None, ""))
            if re.search(r"ESEG", t) and re.search(r"efetiv|quantidade|n.mero|total", t, re.I):
                print("   dic:", t[:260], flush=True)
        ws = wb["Segurança Pública"]
        linhas = list(ws.iter_rows(values_only=True))
        print("  cab0:", [str(v)[:12] for v in linhas[0][:40]], flush=True)
        for l in linhas[1:4]:
            print("  lin:", [str(v)[:12] for v in l[:60]], flush=True)
    except Exception as e:
        print("  estadic erro", type(e).__name__, e, flush=True)

    # MUNIC 2024 e 2023: guarda municipal
    for url in ("https://ftp.ibge.gov.br/Perfil_Municipios/2024/Base_de_Dados/Base_MUNIC_2024_20251107.xlsx",
                "https://ftp.ibge.gov.br/Perfil_Municipios/2023/Base_de_Dados/Base_MUNIC_2023.xlsx"):
        try:
            wb = wb_de(url)
            print("  abas:", [w.title for w in wb.worksheets], flush=True)
            for ws in wb.worksheets:
                if re.search(r"dicion", ws.title, re.I):
                    for row in ws.iter_rows(values_only=True):
                        t = " | ".join(str(v) for v in row if v not in (None, ""))
                        if re.search(r"guarda|seguran.a p", t, re.I):
                            print("   dic:", t[:240], flush=True)
        except Exception as e:
            print("  munic erro", type(e).__name__, e, flush=True)

    for u in ("https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/estatistica/pesquisaperfil/"
              "pesquisa-perfil-das-instituicoes-de-seguranca-publica",
              "https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/estatistica/pesquisaperfil/"
              "outras-pesquisas-perfis-das-instituicoes-de-seguranca-publica"):
        links("mj perfil " + u.rsplit("/", 1)[-1][:30], u, headers=nav,
              padrao=r'href="([^"]*(?:\.xlsx|\.xls|\.csv|\.zip|\.ods|\.pdf|@@download)[^"]*)"', n=60)


if __name__ == "__main__":
    main()
