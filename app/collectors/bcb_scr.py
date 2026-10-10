"""Dívida com bancos e inadimplência por estado — SCR.data (Banco Central).

Arquivo anual https://www.bcb.gov.br/pda/desig/planilha_{ano}.zip com um CSV por mês (~300 MB descompactado cada).
Baixamos só o mês mais recente de dentro do zip (pedidos Range no diretório central), descompactamos em fluxo e
somamos por UF e tipo de cliente (PF/PJ): carteira ativa e carteira inadimplida (atraso acima de 90 dias).
"""
import codecs
import csv
import re
import struct
import zlib
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

URL = "https://www.bcb.gov.br/pda/desig/planilha_{ano}.zip"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Accept": "*/*"}


def _n(v: str) -> float:
    try:
        return float(v.replace(".", "").replace(",", ".")) if v and v.strip() not in ("", "-") else 0.0
    except ValueError:
        return 0.0


def entradas_zip(url: str) -> tuple[int, list]:
    """(tamanho, [(nome, comprimido, metodo, offset)]) lendo só o fim do zip."""
    tam = int(http._cliente.head(url, headers=UA, timeout=60, follow_redirects=True).headers.get("content-length") or 0)
    if not tam:
        raise RuntimeError(f"{url}: sem tamanho")
    fim = http._cliente.get(url, headers={**UA, "Range": f"bytes={max(0, tam - 262144)}-{tam - 1}"}, timeout=120).content
    k = fim.rfind(b"PK\x05\x06")
    _, cd_tam, cd_ini = struct.unpack("<HII", fim[k + 10:k + 20])
    cd = http._cliente.get(url, headers={**UA, "Range": f"bytes={cd_ini}-{cd_ini + cd_tam - 1}"}, timeout=120).content
    pos, out = 0, []
    while pos < len(cd) and cd[pos:pos + 4] == b"PK\x01\x02":
        metodo = struct.unpack("<H", cd[pos + 10:pos + 12])[0]
        comp = struct.unpack("<I", cd[pos + 20:pos + 24])[0]
        nl, el, cl = struct.unpack("<HHH", cd[pos + 28:pos + 34])
        off = struct.unpack("<I", cd[pos + 42:pos + 46])[0]
        out.append((cd[pos + 46:pos + 46 + nl].decode("latin-1"), comp, metodo, off))
        pos += 46 + nl + el + cl
    return tam, out


def linhas_entrada(url: str, comp: int, metodo: int, off: int):
    """Linhas de texto de um arquivo dentro do zip remoto, descompactadas em fluxo."""
    cab = http._cliente.get(url, headers={**UA, "Range": f"bytes={off}-{off + 29}"}, timeout=60).content
    nl, el = struct.unpack("<HH", cab[26:30])
    ini = off + 30 + nl + el
    dec = zlib.decompressobj(-15) if metodo == 8 else None
    txt = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
    resto = ""
    with http._cliente.stream("GET", url, headers={**UA, "Range": f"bytes={ini}-{ini + comp - 1}"}, timeout=None) as r:
        r.raise_for_status()
        for bloco in r.iter_bytes(1 << 20):
            dados = dec.decompress(bloco) if dec else bloco
            parte = resto + txt.decode(dados)
            *completas, resto = parte.split("\n")
            yield from (c.rstrip("\r") for c in completas)
    if dec:
        resto += txt.decode(dec.flush(), final=True)
    if resto.strip():
        yield resto.rstrip("\r")


def agregar_scr(linhas) -> tuple[str | None, dict]:
    """(data_base, {uf: {"pf"|"pj": {carteira, inadimplida}}}) somando as linhas do CSV."""
    leitor = csv.reader(linhas, delimiter=";")
    cab = [c.strip().lower() for c in next(leitor)]
    i = {c: cab.index(c) for c in ("data_base", "uf", "cliente", "carteira_ativa", "carteira_inadimplida_arrastada")}
    out, ref = {}, None
    for l in leitor:
        if len(l) <= max(i.values()):
            continue
        uf, cli = l[i["uf"]].strip().upper(), l[i["cliente"]].strip().upper()
        if len(uf) != 2 or cli not in ("PF", "PJ"):
            continue
        ref = ref or l[i["data_base"]].strip()
        a = out.setdefault(uf, {}).setdefault(cli.lower(), {"carteira": 0.0, "inadimplida": 0.0})
        a["carteira"] += _n(l[i["carteira_ativa"]])
        a["inadimplida"] += _n(l[i["carteira_inadimplida_arrastada"]])
    for por in out.values():
        for a in por.values():
            a["carteira"] = round(a["carteira"], 2)
            a["inadimplida"] = round(a["inadimplida"], 2)
            a["inadimplencia"] = round(100 * a["inadimplida"] / a["carteira"], 2) if a["carteira"] else None
    return ref, out


def coletar_scr_uf(ano: int | None = None):
    """Mês mais recente do SCR.data: dívida das pessoas e das empresas com bancos, por estado."""
    with registrar_coleta("bcb", "scr_uf", ano=ano or "mais recente") as (db, n):
        anos = [int(ano)] if ano else [date.today().year, date.today().year - 1]
        for a in anos:
            url = URL.format(ano=a)
            try:
                _, ents = entradas_zip(url)
            except Exception as e:
                n.avisos.append(f"{a}: {type(e).__name__}")
                continue
            meses = sorted((e for e in ents if re.search(r"planilha_\d{6}\.csv$", e[0])), key=lambda e: e[0])
            if not meses:
                continue
            nome, comp, metodo, off = meses[-1]
            ref, por_uf = agregar_scr(linhas_entrada(url, comp, metodo, off))
            for uf, d in por_uf.items():
                upsert(db, Registro, {"fonte": "bcb", "tipo": "scr_uf", "chave": f"{ref}-{uf}"},
                       {"uf": uf, "ano": int(str(ref)[:4]) if ref else a, "titulo": f"SCR.data {uf} {ref}",
                        "valor": (d.get("pf") or {}).get("carteira"), "dados": {**d, "referencia": ref, "arquivo": nome}})
                n += 1
            break
    return n.itens
