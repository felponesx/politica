"""Fotos das pessoas dos escândalos (árvore e lista), da Wikipédia/Wikimedia Commons.

    python -m scripts.fotos_escandalos [site/midia]

Só entra a foto quando o verbete da Wikipédia em português tem o mesmo nome da pessoa (ou redireciona para ele) E cita
o escândalo no texto (palavras de PISTAS): assim um homônimo nunca ganha a foto de outra pessoa. Grava nos blocos
fotos_<N>.json com a chave "esc:<nome como está no caso>". O robô chama fotos_escandalos() junto das outras fotos.
"""
import json
import logging
import os
import re
import sys
import unicodedata

from app import escandalos
from scripts.midia_site import BLOCOS, WIKI, cli, fnv1a, miniatura

log = logging.getLogger("brasilplus.midia")
ALTURA = 160
# palavras que o verbete precisa citar para a foto valer para aquele caso
PISTAS = {"lava-jato": ["lava jato", "petrolao", "petrobras"], "mensalao": ["mensalao", "acao penal 470", "ap 470"],
          "mensalao-mineiro": ["mensalao mineiro", "mensalao tucano", "valerioduto"], "zelotes": ["zelotes", "carf"],
          "banco-master": ["banco master"], "fraude-inss": ["inss"], "covaxin": ["covaxin", "precisa medicamentos"],
          "joias-sauditas": ["joias", "joia"], "emendas-orcamento-secreto": ["orcamento secreto", "emendas de relator", "emendas"],
          "collor-pc-farias": ["pc farias", "impeachment", "esquema pc"], "anoes-do-orcamento": ["anoes do orcamento"],
          "sanguessugas": ["sanguessuga", "mafia das ambulancias"]}


def _n(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _pagina(titulo: str) -> dict | None:
    try:
        d = cli.get(WIKI, params={"action": "query", "format": "json", "redirects": 1, "prop": "pageimages|extracts",
                                  "piprop": "thumbnail", "pithumbsize": 400, "explaintext": 1, "exlimit": 1,
                                  "titles": titulo}).json()
    except Exception as e:
        log.warning("Wikipédia (%s): %s", titulo, e)
        return None
    for pg in (d.get("query", {}).get("pages") or {}).values():
        if "missing" not in pg:
            return pg
    return None


def _busca(nome: str, caso: str) -> list[str]:
    try:
        d = cli.get(WIKI, params={"action": "query", "format": "json", "list": "search", "srlimit": 3,
                                  "srsearch": f'"{nome}" {caso}'}).json()
    except Exception:
        return []
    return [r["title"] for r in d.get("query", {}).get("search", [])]


def foto_de(nome: str, slug: str, nome_caso: str) -> str | None:
    pistas = PISTAS.get(slug) or [_n(nome_caso)]
    alvo = _n(re.sub(r"\s*\(.*\)$", "", nome))
    # o próprio nome; senão, um resultado da busca cujo título comece pelo nome (ex.: "Fulano (político)")
    titulos = [re.sub(r"\s*\(.*\)$", "", nome)] + [t for t in _busca(re.sub(r"\s*\(.*\)$", "", nome), nome_caso)
                                                    if _n(re.sub(r"\s*\(.*\)$", "", t)) == alvo]
    for t in dict.fromkeys(titulos):
        pg = _pagina(t)
        if not pg:
            continue
        txt = _n(pg.get("extract") or "")
        thumb = (pg.get("thumbnail") or {}).get("source")
        if not thumb or "desambigua" in txt[:400] or not any(p in txt for p in pistas):
            continue
        try:
            r = cli.get(thumb)
            return miniatura(r.content, ALTURA) if r.status_code == 200 else None
        except Exception:
            return None
    return None


def fotos_escandalos() -> dict:
    out = {}
    for slug, c in escandalos.casos().items():
        for p in c["pessoas"]:
            img = foto_de(p["nome"], slug, c["nome"])
            if img:
                out["esc:" + p["nome"]] = img
    log.info("fotos dos escândalos: %d", len(out))
    return out


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pasta = argv[0] if argv else "site/midia"
    novas = fotos_escandalos()
    for i in range(BLOCOS):
        arq = os.path.join(pasta, f"fotos_{i}.json")
        bloco = json.load(open(arq, encoding="utf-8"))
        mudou = False
        for k in [k for k in bloco if k.startswith("esc:") and k not in novas]:
            del bloco[k]
            mudou = True
        for k, v in novas.items():
            if fnv1a(k) % BLOCOS == i:
                bloco[k] = v
                mudou = True
        if mudou:
            with open(arq, "w", encoding="utf-8") as f:
                json.dump(bloco, f, separators=(",", ":"))
    print(f"{len(novas)} fotos de pessoas dos escândalos gravadas em {pasta}")


if __name__ == "__main__":
    main(sys.argv[1:])
