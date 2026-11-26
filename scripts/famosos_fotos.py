"""Fotos dos artistas e famosos (app/dados/famosos.json), com licença e crédito do Wikimedia Commons.

Uso:
    python -m scripts.famosos_fotos [--limite N] [--so-escolha]

De onde vem: a imagem principal que o Wikidata guarda para a pessoa (P18) → arquivo no Wikimedia Commons. O Commons só aceita arquivos com
licença livre (CC0, domínio público, CC BY, CC BY-SA...); para cada foto gravamos o AUTOR, a LICENÇA (com o link do texto) e o link da página
do arquivo no Commons, que a tela mostra junto da foto. Foto sem licença legível nos metadados NÃO entra (a pessoa fica com as iniciais).
A foto é quadrada, 96 px, WebP, cortada do alto (rosto) quando é retrato em pé. Só entra quem tem foto no Wikidata; quem não tem fica sem foto,
nunca com imagem de outra pessoa ("Pessoa homônima" não existe aqui: a ligação é pelo identificador Q do Wikidata, não pelo nome).

Quem ganha foto (limite de tamanho do site publicado): músicos com fãs no Deezer ou mais conhecidos, atores, dubladores, arquitetos,
engenheiros, famosos de redes e as pessoas mais conhecidas de cada outra profissão (`LIMITES`).

Saída:
    app/dados/famosos_fotos/<Q>.webp
    app/dados/famosos_fotos.json   {Q: [autor, licenca, url_licenca, url_pagina_commons]}
"""
from __future__ import annotations

import html
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts import famosos as fm

DADOS = Path(__file__).resolve().parent.parent / "app" / "dados"
PASTA = DADOS / "famosos_fotos"
INDICE = DADOS / "famosos_fotos.json"
UA = fm.UA
LADO = 96
COMMONS = "https://commons.wikimedia.org/w/api.php"
# quantas pessoas de cada grupo recebem foto (as mais conhecidas primeiro; músicos com fãs no Deezer sempre entram)
LIMITES = {"musico": 900, "ator": 700, "dublador": 400, "arquiteto": 250, "engenheiro": 250, "rede": 700}
LIMITE_PROF = 100
LIC_OK = re.compile(r"^(CC0|CC[ -]BY|Public domain|PD|Copyrighted free use|Attribution|Domínio público)", re.I)


def q_imagem(ids):
    return f'SELECT ?p ?img WHERE {{ VALUES ?p {{ {fm.V(ids)} }} ?p wdt:P18 ?img }}'


def nome_arquivo(url: str) -> str:
    return urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("_", " ")


def get_json(url, tentativas=5):
    for t in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            time.sleep(int(e.headers.get("Retry-After") or 10 * (t + 1)) if e.code == 429 else 4 * (t + 1))
        except Exception:
            time.sleep(4 * (t + 1))
    return None


def baixa(url, tentativas=5):
    for t in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(int(e.headers.get("Retry-After") or 8 * (t + 1)) if e.code == 429 else 4 * (t + 1))
        except Exception:
            time.sleep(4 * (t + 1))
    return None


def limpa(txt: str, tam=90) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", txt or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= tam else t[: tam - 1].rstrip() + "…"


def metadados(nomes):
    """Commons: {nome: {thumb, pagina, autor, licenca, url_licenca}} para até 50 arquivos por chamada."""
    saida = {}
    for i in range(0, len(nomes), 50):
        lote = nomes[i:i + 50]
        url = COMMONS + "?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 120,
            "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Credit", "titles": "|".join("File:" + n for n in lote)})
        d = get_json(url)
        time.sleep(6.0)  # o Commons limita por IP (429 com espera de ~40 s): ritmo lento
        if not d:
            continue
        mapa = {}
        for n in d.get("query", {}).get("normalized", []):
            mapa[n["to"]] = n["from"]
        for pg in d.get("query", {}).get("pages", {}).values():
            ii = (pg.get("imageinfo") or [None])[0]
            if not ii:
                continue
            t = pg["title"][5:]
            em = ii.get("extmetadata", {})
            saida[t] = {"thumb": ii.get("thumburl"), "pagina": ii.get("descriptionurl"),
                        "autor": limpa((em.get("Artist") or {}).get("value", "")) or limpa((em.get("Credit") or {}).get("value", "")),
                        "licenca": limpa((em.get("LicenseShortName") or {}).get("value", ""), 40),
                        "url_licenca": (em.get("LicenseUrl") or {}).get("value", "")}
    return saida


def quadrado(dados: bytes) -> bytes | None:
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(dados))
        im.load()
    except Exception:
        return None
    if im.mode in ("RGBA", "LA", "P"):
        fundo = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        fundo.paste(im, mask=im.split()[-1])
        im = fundo
    else:
        im = im.convert("RGB")
    w, h = im.size
    if w < 40 or h < 40:
        return None
    lado = min(w, h)
    esq = (w - lado) // 2
    topo = int((h - lado) * 0.12) if h > w else (h - lado) // 2  # retrato em pé: corta do alto, onde fica o rosto
    im = im.crop((esq, topo, esq + lado, topo + lado)).resize((LADO, LADO), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "WEBP", quality=55, method=6)
    return b.getvalue()


def escolher(pessoas, tem_foto):
    """Quem ganha foto: por grupo, os mais conhecidos que têm imagem no Wikidata."""
    escolhidos, usados = [], set()

    def pega(grupo, lim, chave):
        c = [p for p in pessoas if grupo in p["g"] and p["q"] in tem_foto and p["q"] not in usados]
        c.sort(key=chave)
        for p in c[:lim]:
            usados.add(p["q"])
            escolhidos.append(p["q"])

    pega("musico", LIMITES["musico"], lambda p: (0 if "dz" in p else 1, -(p["dz"][0] if "dz" in p else 0), -p["s"]))
    pega("rede", LIMITES["rede"], lambda p: -p["s"])
    for g in ("ator", "dublador", "arquiteto", "engenheiro"):
        pega(g, LIMITES[g], lambda p: -p["s"])
    for g in sorted({x for p in pessoas for x in p["g"] if x.startswith("prof:")}):
        pega(g, LIMITE_PROF, lambda p: -p["s"])
    return escolhidos


def main(limite=None, so_escolha=False):
    doc = json.loads(fm.SAIDA.read_text(encoding="utf-8"))
    pessoas = doc["p"]
    ids = [p["q"] for p in pessoas]
    fm.log("imagens P18 de", len(ids), "pessoas")
    img = {}
    for r in fm.em_lotes(q_imagem, ids, 150):
        img.setdefault(fm.qid(r["p"]), nome_arquivo(r["img"]))
    fm.log("com imagem no Wikidata:", len(img))
    esc = escolher(pessoas, img)
    if limite:
        esc = esc[:limite]
    fm.log("escolhidas:", len(esc))
    if so_escolha:
        return
    PASTA.mkdir(parents=True, exist_ok=True)
    cred = json.loads(INDICE.read_text(encoding="utf-8")) if INDICE.exists() else {}
    falta = [q for q in esc if not ((PASTA / f"{q}.webp").exists() and q in cred)]
    fm.log("a baixar:", len(falta))
    nomes = sorted({img[q] for q in falta})
    meta = metadados(nomes)
    ok = sem_lic = falhas = 0
    for k, q in enumerate(falta):
        m = meta.get(img[q])
        if not m or not m["thumb"]:
            falhas += 1
            continue
        if not m["licenca"] or not LIC_OK.match(m["licenca"]):
            sem_lic += 1
            continue
        dados = baixa(m["thumb"])
        w = quadrado(dados) if dados else None
        if not w:
            falhas += 1
            continue
        (PASTA / f"{q}.webp").write_bytes(w)
        cred[q] = [m["autor"], m["licenca"], m["url_licenca"], m["pagina"]]
        ok += 1
        time.sleep(0.4)
        if k % 100 == 0:
            INDICE.write_text(json.dumps(cred, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            fm.log("  fotos", k, "/", len(falta), "| ok", ok, "| licença não aceita", sem_lic, "| falhas", falhas)
    INDICE.write_text(json.dumps(cred, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    fm.log("fim | ok", ok, "| licença não aceita", sem_lic, "| falhas", falhas, "| total com foto", len(cred))


if __name__ == "__main__":
    lim = None
    if "--limite" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limite") + 1])
    main(limite=lim, so_escolha="--so-escolha" in sys.argv)
