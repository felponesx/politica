"""Fotos das pessoas dos escândalos (árvore e lista), da Wikipédia/Wikimedia Commons.

    python -m scripts.fotos_escandalos [site/midia] [arquivo_de_cache.json]

Só entra a foto quando o verbete da Wikipédia em português tem o mesmo nome da pessoa (ou redireciona para ele) E cita
o escândalo no texto (palavras de PISTAS): assim um homônimo nunca ganha a foto de outra pessoa. Grava nos blocos
fotos_<N>.json com a chave "esc:<nome como está no caso>". Redirecionamento só vale para outro título da mesma pessoa
(todas as palavras do título estão no nome); verbete de desambiguação ou de operação/evento não dá foto. O robô chama fotos_escandalos() junto das outras fotos.
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
_IMG = re.compile(r"\|\s*(?:imagem|image|foto)\s*=\s*(?:\[\[)?(?:(?:Ficheiro|Arquivo|File|Imagem):)?([^\n|\]]+\.(?:jpe?g|png|webp|tiff?))",
                  re.I)
_INFO = re.compile(r"\{\{\s*(Info/[^}|\n]+?)\s*\}\}")


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


class Limite(RuntimeError):
    """A Wikimedia continuou recusando (limite de pedidos): a pessoa fica para a próxima rodada, sem virar "sem foto"."""


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
    raise Limite(url)


def _baixar_thumb(arquivo: str) -> str | None:
    for url in _thumb(arquivo):
        cod, corpo = _get(url)
        if cod == 200 and corpo:
            return miniatura(corpo, ALTURA)
    return None


def foto_de(nome: str, slug: str, nome_caso: str) -> str | None:
    """Pela Wikipédia: verbete com o nome (ou o apelido entre parênteses) que é de uma pessoa e cita o caso."""
    apelido = re.search(r"\(([^)]+)\)\s*$", nome)
    for n in [nome] + ([apelido.group(1).strip("'\" ")] if apelido else []):
        try:
            img = _foto_wikipedia(n, slug, nome_caso, nome)
        except Limite:
            raise
        except Exception:
            img = None
        if img:
            return img
    return None


def _foto_wikipedia(nome: str, slug: str, nome_caso: str, nome_completo: str | None = None) -> str | None:
    pistas = PISTAS.get(slug) or [_n(nome_caso)]
    achado = _raw(re.sub(r"\s*\(.*\)$", "", nome))
    if not achado:
        return None
    titulo, txt = achado
    palavras = set(re.findall(r"[a-z]+", _n(nome_completo or nome)))
    if not set(re.findall(r"[a-z]+", _n(re.sub(r"\s*\(.*\)$", "", titulo)))) <= palavras:
        return None  # redirecionou para outra coisa (ex.: a página da operação policial)
    tn = _n(txt)
    if "{{desambiguacao" in tn or not any(p in tn for p in pistas) or re.search(r"\{\{\s*info/(operacao|evento|caso|escandalo|crime)", tn):
        return None  # outro verbete com o mesmo nome, ou que não fala do caso: sem foto
    m = _IMG.search(txt)
    if not m:
        # quadro de dados em página própria ({{Info/Político/Fulano}}): a foto está nela
        info = _INFO.search(txt)
        sub = _raw("Predefinição:" + info.group(1)) if info else None
        m = _IMG.search(sub[1]) if sub else None
    if not m:
        return None
    return _baixar_thumb(m.group(1).strip())


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
                try:
                    feito[k] = foto_de(p["nome"], slug, c["nome"])
                except Limite:
                    log.warning("%s: limite da Wikimedia, fica para a próxima rodada", p["nome"])
                    continue
                log.info("%s: %s", p["nome"], "foto" if feito[k] else "sem foto")
                if cache:
                    with open(cache, "w", encoding="utf-8") as f:
                        json.dump(feito, f)
            if feito.get(k):
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
