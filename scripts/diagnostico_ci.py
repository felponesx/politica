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


def entrada_zip(url, nome_parte):
    """Baixa só um arquivo de dentro de um zip remoto (pedidos Range) e devolve o texto."""
    import struct
    import zlib
    tam = int(cli.head(url).headers.get("content-length") or 0)
    fim = cli.get(url, headers={"Range": f"bytes={max(0, tam - 262144)}-{tam - 1}"}).content
    k = fim.rfind(b"PK\x05\x06")
    n_ent, cd_tam, cd_ini = struct.unpack("<HII", fim[k + 10:k + 20])
    cd = cli.get(url, headers={"Range": f"bytes={cd_ini}-{cd_ini + cd_tam - 1}"}).content
    pos = 0
    while pos < len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
        metodo = struct.unpack("<H", cd[pos + 10:pos + 12])[0]
        comp, desc = struct.unpack("<II", cd[pos + 20:pos + 28])
        nl, el, cl = struct.unpack("<HHH", cd[pos + 28:pos + 34])
        off = struct.unpack("<I", cd[pos + 42:pos + 46])[0]
        nm = cd[pos + 46:pos + 46 + nl].decode("latin-1")
        pos += 46 + nl + el + cl
        if nome_parte in nm:
            loc = cli.get(url, headers={"Range": f"bytes={off}-{off + 30 + 1024 + comp}"}).content
            nl2, el2 = struct.unpack("<HH", loc[26:30])
            dado = loc[30 + nl2 + el2:30 + nl2 + el2 + comp]
            bruto = zlib.decompress(dado, -15) if metodo == 8 else dado
            print(f"  {nm}: {comp} -> {desc} bytes", flush=True)
            return bruto.decode("latin-1")
    return None


def main():
    nav = {"User-Agent": UA_NAV}
    import json
    import re

    # 1) Notícias de política (RSS)
    for nome, url in [("g1 politica", "https://g1.globo.com/rss/g1/politica/"),
                      ("cnn politica", "https://www.cnnbrasil.com.br/politica/feed/"),
                      ("oglobo politica", "https://oglobo.globo.com/rss/politica/"),
                      ("oglobo rss geral", "https://oglobo.globo.com/rss.xml"),
                      ("camara noticias", "https://www.camara.leg.br/noticias/rss/ultimas-noticias"),
                      ("camara politica", "https://www.camara.leg.br/noticias/rss/dinamico/POLITICA"),
                      ("senado noticias", "https://www12.senado.leg.br/noticias/rss"),
                      ("agencia brasil politica", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
                      ("folha poder", "https://feeds.folha.uol.com.br/poder/rss091.xml"),
                      ("uol politica", "https://rss.uol.com.br/feed/noticias.xml")]:
        r = ver("rss " + nome, url, headers=nav, n=200)
        if r is not None and r.status_code == 200:
            itens = re.findall(r"<item>(.*?)</item>", r.text, re.S)
            print("  itens:", len(itens), flush=True)
            for it in itens[:2]:
                print("   ", re.sub(r"\s+", " ", it)[:500], flush=True)

    # 2) Logos e brasões na Wikipédia (pageimages) + efetivo na caixa de informações
    titulos = ["Partido dos Trabalhadores", "Partido Liberal (2006)", "União Brasil", "Progressistas",
               "Movimento Democrático Brasileiro (1980)", "Partido Social Democrático (2011)", "Republicanos (partido político)",
               "Partido da Social Democracia Brasileira", "Partido Democrático Trabalhista", "Partido Socialista Brasileiro",
               "Partido Socialismo e Liberdade", "Podemos (Brasil)", "Avante (partido político)", "Partido Comunista do Brasil",
               "Partido Verde (Brasil)", "Cidadania (partido político)", "Partido Novo", "Solidariedade (partido político)",
               "Partido Renovação Democrática", "Rede Sustentabilidade", "Agir (partido político)", "Mobiliza",
               "Democracia Cristã (Brasil)", "Partido da Mulher Brasileira", "Partido Socialista dos Trabalhadores Unificado",
               "Partido da Causa Operária", "Unidade Popular", "Partido Comunista Brasileiro", "Missão (partido político)",
               "Partido Renovador Trabalhista Brasileiro", "Partido da Mobilização Nacional", "Partido Social Liberal",
               "Democratas (Brasil)", "Partido Trabalhista Brasileiro", "Partido Social Cristão",
               "Partido Republicano da Ordem Social", "Patriota (partido político)", "Partido Trabalhista Cristão",
               "Partido Humanista da Solidariedade", "Partido Pátria Livre", "Partido Republicano Progressista",
               "Partido da República", "Partido Popular Socialista",
               "Polícia Militar do Estado de São Paulo", "Polícia Militar do Estado do Rio de Janeiro",
               "Polícia Militar de Minas Gerais", "Polícia Militar do Ceará", "Brigada Militar",
               "Polícia Civil do Estado de São Paulo", "Polícia Federal do Brasil", "Polícia Rodoviária Federal",
               "Força Nacional de Segurança Pública", "Polícia Penal Federal", "Guarda Civil Metropolitana de São Paulo",
               "Rondas Ostensivas Tobias de Aguiar", "Batalhão de Operações Policiais Especiais",
               "Comando de Operações Táticas", "Grupo de Ações Táticas Especiais",
               "Comando de Operações Especiais (PMESP)", "Coordenadoria de Recursos Especiais",
               "Grupo de Operações Especiais (PCESP)", "Batalhão de Polícia de Choque (PMERJ)",
               "Rondas Ostensivas Táticas Metropolitanas", "Sistema Penitenciário Federal", "Receita Federal do Brasil"]
    api = "https://pt.wikipedia.org/w/api.php"
    for k in range(0, len(titulos), 20):
        try:
            r = cli.get(api, params={"action": "query", "format": "json", "redirects": 1, "prop": "pageimages|revisions",
                                     "piprop": "thumbnail|name", "pithumbsize": 160, "rvprop": "content", "rvslots": "main",
                                     "rvsection": 0, "titles": "|".join(titulos[k:k + 20])},
                        headers={"User-Agent": "BRASIL+ (dados publicos; contato via GitHub felponesx/politica)"})
            print(f"\n=== wikipedia lote {k}: HTTP {r.status_code}", flush=True)
            d = r.json()
            for red in d.get("query", {}).get("redirects", []):
                print("   redir:", red.get("from"), "->", red.get("to"), flush=True)
            for pg in d.get("query", {}).get("pages", {}).values():
                txt = ((pg.get("revisions") or [{}])[0].get("slots", {}).get("main", {}).get("*") or "")
                ef = re.findall(r"\|\s*(efetivo|membros|filiados|fundação|criação|concurso)[^=\n]*=\s*([^\n|]{0,80})", txt, re.I)
                print(f"   {pg.get('title')!r} | missing={'missing' in pg} | img={pg.get('pageimage')} | "
                      f"thumb={(pg.get('thumbnail') or {}).get('source')} | {ef[:4]}", flush=True)
        except Exception as e:
            print("  wiki erro", type(e).__name__, e, flush=True)
    for u in ("https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Logo_do_PT.svg/160px-Logo_do_PT.svg.png",):
        ver("upload.wikimedia", u, headers={"User-Agent": "BRASIL+ (dados publicos)"}, n=40)

    # 3) Fotos: TSE (zip por UF), Câmara e Senado
    for ano in (2026, 2024, 2022):
        for u in (f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/fotos/foto_cand{ano}_SP_div.zip",
                  f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/fotos/foto_cand{ano}_BR_div.zip"):
            ver(f"tse fotos {ano}", u, metodo="HEAD")
    zip_remoto("tse fotos 2026 AC", "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/fotos/foto_cand2026_AC_div.zip")
    ver("camara foto", "https://www.camara.leg.br/internet/deputado/bandep/204554.jpg", metodo="HEAD")
    ver("senado foto", "https://www.senado.leg.br/senadores/img/fotos-oficiais/senador5672.jpg", metodo="HEAD")

    # 4) Despesa federal por órgão sem chave (downloads do Portal da Transparência)
    for u in ("https://portaldatransparencia.gov.br/download-de-dados/despesas-execucao/202608",
              "https://portaldatransparencia.gov.br/download-de-dados/despesas-execucao/2025",
              "https://portaldatransparencia.gov.br/download-de-dados/orcamento-despesa/2026",
              "https://portaldatransparencia.gov.br/download-de-dados/orcamento-despesa/2025"):
        r = ver("portal download " + u.rsplit("/", 2)[-2] + "/" + u.rsplit("/", 1)[-1], u, headers=nav, metodo="HEAD")
    zip_remoto("orcamento-despesa 2026", "https://portaldatransparencia.gov.br/download-de-dados/orcamento-despesa/2026",
               mostrar=(".csv",), linhas=3)
    zip_remoto("despesas-execucao 202608", "https://portaldatransparencia.gov.br/download-de-dados/despesas-execucao/202608",
               mostrar=(".csv",), linhas=3)

    # 5) Anos anteriores: TSE 2018/2020 e Sinesp/Sisdepen/Raio-X
    for ano in (2018, 2020):
        ver(f"tse munzona {ano}", f"https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip", metodo="HEAD")
        ver(f"tse cand {ano}", f"https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip", metodo="HEAD")
    for ano in (2015, 2018, 2020, 2022, 2024):
        ver(f"sinesp {ano}", "https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/estatistica/download/"
            f"dnsp-base-de-dados/bancovde-{ano}.xlsx/@@download/file", headers=nav, metodo="HEAD")
    links("sisdepen bases", "https://www.gov.br/senappen/pt-br/servicos/sisdepen/bases-de-dados", headers=nav,
          padrao=r'href="([^"]*bases-de-dados/\d{4}/[^"]*\.csv/@@download/file)"', n=40)
    for a in (2024, 2025):
        links(f"raio-x {a}", f"https://forumseguranca.org.br/publicacoes/raio-x-das-forcas-de-seguranca-publica-do-brasil-{a}/",
              headers=nav, padrao=r'href="([^"]+\.xlsx)"', n=5)
    links("anuarios", "https://forumseguranca.org.br/publicacoes/anuario-brasileiro-de-seguranca-publica/", headers=nav,
          padrao=r'href="([^"]+anuario[^"]*\.xlsx)"', n=20)


if __name__ == "__main__":
    main()
