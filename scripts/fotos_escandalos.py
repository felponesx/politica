"""Fotos das pessoas dos escândalos (árvore e lista), da Wikipédia/Wikimedia Commons.

    python -m scripts.fotos_escandalos [site/midia] [arquivo_de_cache.json]

Só entra a foto quando o verbete da Wikipédia em português tem o mesmo nome da pessoa (ou redireciona para ele) E cita
o escândalo no texto (palavras de PISTAS): assim um homônimo nunca ganha a foto de outra pessoa. Grava nos blocos
fotos_<N>.json com a chave "esc:<nome como está no caso>". O robô chama fotos_escandalos() junto das outras fotos.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import unicodedata
from urllib.parse import quote

from app import escandalos
from scripts.midia_site import BLOCOS, fnv1a, miniatura

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


RAW = "https://pt.wikipedia.org/w/index.php"
_IMG = re.compile(r"\|\s*(?:imagem|image|foto)\s*=\s*(?:\[\[(?:Ficheiro|Arquivo|File|Imagem):)?([^\n|\]]+\.(?:jpe?g|png|webp|tiff?))", re.I)


def _raw(titulo: str, saltos: int = 2) -> tuple[str, str] | None:
    """Texto (wikitexto) do verbete, seguindo redirecionamentos. Usa action=raw, que a Wikimedia não limita como a API."""
    cod, corpo = _get(RAW, {"title": titulo, "action": "raw"})
    texto = corpo.decode("utf-8", "replace")
    if cod != 200 or not texto:
        return None
    m = re.match(r"\s*#(?:REDIRECIONAMENTO|REDIRECT)\s*\[\[([^\]|#]+)", texto, re.I)
    if m and saltos:
        return _raw(m.group(1).strip(), saltos - 1)
    return titulo, texto


def _thumb(arquivo: str, largura: int = 250) -> list[str]:
    """Endereços da miniatura no Wikimedia Commons (e, se o arquivo for só da Wikipédia em português, no acervo dela).
    A Wikimedia só serve larguras padronizadas (250, 330, 500...); outras dão erro 400."""
    nome = arquivo.strip().replace(" ", "_")
    h = hashlib.md5(nome.encode()).hexdigest()
    q = quote(nome)
    return [f"https://upload.wikimedia.org/wikipedia/{w}/thumb/{h[0]}/{h[:2]}/{q}/{largura}px-{q}" for w in ("commons", "pt")]


def _get(url: str, params: dict | None = None) -> tuple[int, bytes]:
    """GET pelo curl (com o User-Agent do projeto); devolve (status, corpo)."""
    from scripts.midia_site import UA
    if params:
        url += ("&" if "?" in url else "?") + "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    # devagar (1,5 s entre pedidos) e, no 429/403 de limite, espera e tenta de novo
    for espera in (0, 10, 30):
        time.sleep(espera or 1.5)
        try:
            r = subprocess.run(["curl", "-s", "-L", "-m", "40", "-A", UA["User-Agent"], "-w", "\n%{http_code}", url],
                               capture_output=True, timeout=60)
        except Exception:
            continue
        corpo, _, cod = r.stdout.rpartition(b"\n")
        if cod not in (b"429", b"403"):
            return int(cod or 0), corpo
    return 429, b""


WD = "https://www.wikidata.org/w/api.php"


def _wikidata(nome: str) -> str | None:
    """Arquivo da foto (P18) da pessoa no Wikidata, só se houver UM ser humano brasileiro com exatamente esse nome
    (rótulo ou apelido); dois ou mais com o mesmo nome = homônimo, sem foto."""
    alvo = _n(nome)
    cod, corpo = _get(WD, {"action": "wbsearchentities", "search": nome, "language": "pt", "uselang": "pt",
                           "type": "item", "limit": 10, "format": "json"})
    if cod != 200:
        return None
    ids = [r["id"] for r in json.loads(corpo).get("search", [])]
    if not ids:
        return None
    cod, corpo = _get(WD, {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|labels|aliases",
                           "languages": "pt|en", "format": "json"})
    if cod != 200:
        return None
    achados = []
    for e in json.loads(corpo).get("entities", {}).values():
        cl = e.get("claims", {})
        vals = lambda p: [c.get("mainsnak", {}).get("datavalue", {}).get("value") for c in cl.get(p, [])]
        humano = any(isinstance(v, dict) and v.get("id") == "Q5" for v in vals("P31"))
        brasil = any(isinstance(v, dict) and v.get("id") == "Q155" for v in vals("P27"))
        nomes = [x.get("value") for x in (e.get("labels") or {}).values()]
        nomes += [a.get("value") for lst in (e.get("aliases") or {}).values() for a in lst]
        if humano and brasil and any(_n(x) == alvo for x in nomes):
            achados.append(next((v for v in vals("P18") if isinstance(v, str)), None))
    return achados[0] if len(achados) == 1 else None


def _baixar_thumb(arquivo: str) -> str | None:
    for url in _thumb(arquivo):
        cod, corpo = _get(url)
        if cod == 200 and corpo:
            return miniatura(corpo, ALTURA)
    return None


def foto_de(nome: str, slug: str, nome_caso: str) -> str | None:
    """Pela Wikipédia (verbete com o nome e que cita o caso); se ela não responder, pelo Wikidata (um só brasileiro
    com esse nome exato)."""
    try:
        img = _foto_wikipedia(nome, slug, nome_caso)
    except Exception:
        img = None
    if img:
        return img
    arq = _wikidata(re.sub(r"\s*\(.*\)$", "", nome))
    return _baixar_thumb(arq) if arq else None


def _foto_wikipedia(nome: str, slug: str, nome_caso: str) -> str | None:
    pistas = PISTAS.get(slug) or [_n(nome_caso)]
    achado = _raw(re.sub(r"\s*\(.*\)$", "", nome))
    if not achado:
        return None
    _, txt = achado
    tn = _n(txt)
    if "{{desambiguacao" in tn or not any(p in tn for p in pistas):
        return None  # outro verbete com o mesmo nome, ou que não fala do caso: sem foto
    m = _IMG.search(txt)
    if not m:
        return None
    return _baixar_thumb(m.group(1))


def fotos_escandalos(cache: str | None = None) -> dict:
    """{"esc:<nome>": data-URL}. Com `cache` (arquivo JSON), guarda o resultado de cada pessoa e retoma de onde parou."""
    feito = {}
    if cache and os.path.exists(cache):
        feito = json.load(open(cache, encoding="utf-8"))
    out = {}
    for slug, c in escandalos.casos().items():
        for p in c["pessoas"]:
            k = "esc:" + p["nome"]
            if k not in feito:
                feito[k] = foto_de(p["nome"], slug, c["nome"])
                log.info("%s: %s", p["nome"], "foto" if feito[k] else "sem foto")
                if cache:
                    with open(cache, "w", encoding="utf-8") as f:
                        json.dump(feito, f)
            if feito[k]:
                out[k] = feito[k]
    log.info("fotos dos escândalos: %d", len(out))
    return out


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pasta = argv[0] if argv else "site/midia"
    novas = fotos_escandalos(argv[1] if len(argv) > 1 else None)
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
