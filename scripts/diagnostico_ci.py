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


def main():
    token = "YggdBLfdninEJX9"
    base = "https://arquivos.receitafederal.gov.br/public.php/webdav/2026-09/"
    amostra_webdav("estabelecimentos0", base + "Estabelecimentos0.zip", (token, ""), mb=8, procurar=True)
    amostra_webdav("estabelecimentos5", base + "Estabelecimentos5.zip", (token, ""), mb=8, procurar=True)
    amostra_webdav("empresas0", base + "Empresas0.zip", (token, ""), mb=1)
    amostra_webdav("municipios", base + "Municipios.zip", (token, ""), mb=1)
    amostra_webdav("cnaes", base + "Cnaes.zip", (token, ""), mb=1)
    # velocidade de download de um arquivo inteiro (Empresas9 costuma ser o menor)
    t = time.monotonic()
    try:
        with cli.stream("GET", base + "Empresas9.zip", auth=(token, "")) as r:
            tam = sum(len(b) for b in r.iter_bytes(1 << 20))
        print(f"\nEmpresas9.zip inteiro: {tam / 1e6:.0f} MB em {time.monotonic() - t:.0f}s", flush=True)
    except Exception as e:
        print("download inteiro: ERRO", e, flush=True)


if __name__ == "__main__":
    main()
