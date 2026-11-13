"""Matéria e foto de cada tragédia da aba Catástrofes: resumo do verbete da Wikipédia (CC BY-SA, com link) e uma imagem
do Wikimedia Commons (com autor e licença). Grava app/dados/catastrofes_midia.json e site/midia/catastrofes/<id>.webp.

Uso: python -m scripts.catastrofes_midia [site/midia]
Campo opcional `imagem` no cadastro (app/dados/catastrofes.json): nome de um arquivo do Commons escolhido à mão (sem 'File:'); null = sem foto.
Sem `imagem`, usa a imagem principal do verbete, que só serve se mostrar o acontecimento (revisada à mão). Nunca se usa imagem que não é do acontecimento."""
from __future__ import annotations

import io
import json
import logging
import re
import sys
from pathlib import Path

from PIL import Image

from scripts.midia_site import WIKI, cli

log = logging.getLogger("brasilplus.catastrofes_midia")
CADASTRO = Path("app/dados/catastrofes.json")
SAIDA = Path("app/dados/catastrofes_midia.json")
COMMONS = "https://commons.wikimedia.org/wiki/File:"


def _texto(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def verbetes(titulos: list[str]) -> dict:
    """{título: {texto, pagina, arquivo_pagina}} pela API (resumo de 3 frases e a imagem principal do verbete)."""
    out = {}
    for k in range(0, len(titulos), 10):
        lote = titulos[k:k + 10]
        d = cli.get(WIKI, params={"action": "query", "format": "json", "redirects": 1, "prop": "pageimages|extracts", "piprop": "name",
                                  "exintro": 1, "explaintext": 1, "exsentences": 3, "titles": "|".join(lote)}).json()
        alias = {r["from"]: r["to"] for r in d.get("query", {}).get("redirects", [])}
        pags = {p.get("title"): p for p in d.get("query", {}).get("pages", {}).values()}
        for t in lote:
            p = pags.get(alias.get(t, t))
            if not p or "missing" in p:
                log.warning("verbete não encontrado: %s", t)
                continue
            out[t] = {"texto": _texto(p.get("extract")), "pagina": "https://pt.wikipedia.org/wiki/" + str(p["title"]).replace(" ", "_"),
                      "arquivo_pagina": p.get("pageimage")}
    return out


def arquivo_commons(nome: str) -> dict | None:
    """Autor, licença e URL da página do arquivo no Commons."""
    d = cli.get("https://commons.wikimedia.org/w/api.php", params={"action": "query", "format": "json", "titles": "File:" + nome,
                                                                   "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 800}).json()
    pg = next(iter(d.get("query", {}).get("pages", {}).values()), {})
    ii = (pg.get("imageinfo") or [None])[0]
    if not ii:
        return None
    m = ii.get("extmetadata") or {}
    return {"thumb": ii.get("thumburl"), "url": COMMONS + nome.replace(" ", "_"),
            "autor": _texto((m.get("Artist") or {}).get("value", ""))[:160] or "autor não informado",
            "licenca": (m.get("LicenseShortName") or {}).get("value", "licença não informada")}


def gravar(pasta_midia: Path = Path("site/midia")) -> dict:
    itens = json.loads(CADASTRO.read_text(encoding="utf-8"))
    titulos = [x["wiki"] for x in itens if x.get("wiki")]
    vb = verbetes(titulos)
    pasta = pasta_midia / "catastrofes"
    pasta.mkdir(parents=True, exist_ok=True)
    saida = {}
    for x in itens:
        if not x.get("wiki") or x["wiki"] not in vb:
            continue
        v = vb[x["wiki"]]
        nome = x["imagem"] if "imagem" in x else v.get("arquivo_pagina")  # imagem: null = sem foto adequada
        imagem = credito = None
        if nome:
            info = arquivo_commons(nome)
            if info and info.get("thumb"):
                r = cli.get(info["thumb"])
                if r.status_code == 200:
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                    im.thumbnail((800, 800))
                    arq = pasta / f"{x['id']}.webp"
                    im.save(arq, "WEBP", quality=72)
                    imagem = f"midia/catastrofes/{x['id']}.webp"
                    credito = {"autor": info["autor"], "licenca": info["licenca"], "pagina": info["url"], "arquivo": nome}
        saida[x["id"]] = {"texto": v["texto"], "pagina": v["pagina"], "imagem": imagem, "credito": credito,
                          "fonte_texto": "Wikipédia (CC BY-SA), resumo do verbete"}
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("matérias: %d; com foto: %d", len(saida), sum(1 for v in saida.values() if v["imagem"]))
    return saida


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    d = gravar(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("site/midia"))
    print(len(d), "matérias")
