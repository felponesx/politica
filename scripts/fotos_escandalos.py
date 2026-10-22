"""Fotos das pessoas dos escândalos (árvore e lista): retrato oficial da Câmara para quem foi deputado federal e, para os demais,
da Wikipédia/Wikimedia Commons.

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
from scripts.logos_arquivo import webp
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


# conferidas à mão: a imagem do verbete não é um retrato da pessoa (ex.: foto de protesto)
SEM_FOTO = {"Ricardo Fiuza"}


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
    h = hashlib.md5(nome.encode(), usedforsecurity=False).hexdigest()
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


CAMARA = "https://dadosabertos.camara.leg.br/api/v2/deputados"
LEGISLATURAS = ",".join(str(i) for i in range(45, 58))  # 1975 em diante: a API só lista a atual se não pedir
# siglas do mesmo partido ao longo do tempo (o cadastro da Câmara guarda a sigla de cada legislatura)
PARTIDOS_IGUAIS = [{"PP", "PPB", "PPR", "PDS"}, {"PMDB", "MDB"}, {"PFL", "DEM"}, {"PL", "PR"}, {"PTB"}, {"PT"}, {"PSDB"}]


def _sigla(p: str) -> str:
    return re.sub(r"[^A-Z]", "", (p or "").upper())


def _mesmo_partido(a: str, b: str) -> bool:
    a, b = _sigla(a), _sigla(b)
    return a == b or any(a in g and b in g for g in PARTIDOS_IGUAIS)


def escolher_deputado(pessoa: dict, linhas: list[dict]) -> dict | None:
    """Entre as linhas do cadastro da Câmara (uma por legislatura), o deputado que é a pessoa do caso: nome igual ao da pessoa
    (ou ao apelido entre parênteses), partido e estado da época quando o caso os informa, e uma única pessoa (mesmo `id`)
    depois dos filtros. Na dúvida (homônimo, dois candidatos), devolve None: sem foto é melhor que foto da pessoa errada."""
    cargo = _n(pessoa.get("cargo_na_epoca") or "")
    if "deputado" not in cargo or "estadual" in cargo or "distrital" in cargo:
        return None
    nome = pessoa["nome"]
    apelido = re.search(r"\(([^)]+)\)\s*$", nome)
    nomes = {_n(re.sub(r"\s*\(.*\)$", "", nome)).strip()} | ({_n(apelido.group(1)).strip("'\" ")} if apelido else set())
    por_id: dict[int, list[dict]] = {}
    for d in linhas:
        if _n(d.get("nome")).strip() in nomes:
            por_id.setdefault(d["id"], []).append(d)
    partido = pessoa.get("partido_na_epoca")
    uf = re.search(r"\(([A-Z]{2})\)", pessoa.get("cargo_na_epoca") or "")
    if partido:
        por_id = {i: v for i, v in por_id.items() if any(_mesmo_partido(partido, d.get("siglaPartido")) for d in v)}
    if uf:
        por_id = {i: v for i, v in por_id.items() if any(d.get("siglaUf") == uf.group(1) for d in v)}
    if len(por_id) != 1:
        return None
    return next(iter(por_id.values()))[-1]


def foto_camara(pessoa: dict) -> str | None:
    """Retrato oficial da Câmara dos Deputados (inclusive de quem já saiu) para quem foi deputado federal."""
    cargo = _n(pessoa.get("cargo_na_epoca") or "")
    if "deputado" not in cargo or "estadual" in cargo or "distrital" in cargo:
        return None
    apelido = re.search(r"\(([^)]+)\)\s*$", pessoa["nome"])
    consulta = apelido.group(1).strip("'\" ") if apelido else re.sub(r"\s*\(.*\)$", "", pessoa["nome"])
    cod, corpo = _get(CAMARA, {"nome": consulta, "idLegislatura": LEGISLATURAS, "itens": 100})
    if cod != 200:
        return None
    escolhido = escolher_deputado(pessoa, json.loads(corpo).get("dados") or [])
    if not escolhido or not escolhido.get("urlFoto"):
        return None
    from scripts.midia_site import foto_maior
    for url in (foto_maior(escolhido["urlFoto"]), escolhido["urlFoto"]):
        cod, img = _get(url)
        if cod == 200 and img:
            return miniatura(img, ALTURA)
    return None


def foto_de(nome: str, slug: str, nome_caso: str, pessoa: dict | None = None) -> str | None:
    """Foto oficial da Câmara (quem foi deputado federal) e, se não houver, a da Wikipédia: verbete com o nome (ou o apelido
    entre parênteses) que é de uma pessoa e cita o caso."""
    if pessoa:
        try:
            img = foto_camara({**pessoa, "nome": nome})
        except Limite:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("%s: Câmara fora do ar (%s)", nome, e)
            img = None
        if img:
            return img
    if nome in SEM_FOTO:
        return None
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
                    feito[k] = foto_de(p["nome"], slug, c["nome"], p)
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
                bloco[k] = webp(v, 80)
                mudou = True
        if mudou:
            with open(arq, "w", encoding="utf-8") as f:
                json.dump(bloco, f, separators=(",", ":"))
    print(f"{len(novas)} fotos de pessoas dos escândalos gravadas em {pasta}")


if __name__ == "__main__":
    main(sys.argv[1:])
