"""Aba "Artistas e famosos": pessoas brasileiras por profissão, a partir do Wikidata (+ fãs no Deezer).

Uso:
    python -m scripts.famosos [--teste] [--so-lista]      # grava app/dados/famosos.json
    FAMOSOS_CACHE=/caminho  (cache das consultas; retoma de onde parou)

O que vem de onde (nada é estimado):
- Wikidata (SPARQL, https://query.wikidata.org): nome, descrição, nascimento/morte, local de nascimento (e o estado pelo ISO 3166-2),
  gêneros (P136), ocupações (P106), prêmios (P166), obras (atuação P161, voz P725, álbuns/singles/músicas P175, projetos P84/P287,
  obra notável P800), contas em redes (P2003 Instagram, P2397 YouTube, P2002/P6552 X, P7085 TikTok, P2013 Facebook, P1902 Spotify,
  P2722 Deezer) e seguidores (P8687, sempre com a data e a rede do qualificador).
- Deezer (https://api.deezer.com/artist/<id>): número de fãs, só para quem tem o ID do Deezer no Wikidata (identidade certa, sem busca por nome).

Limites que a tela repete: NÃO existe base aberta de horas ouvidas por artista; o ranking de música usa fãs no Deezer (e seguidores
com data). Seguidores de uma rede não se somam com os de outra. Campo ausente é "não informado", nunca zero.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

UA = "BRASILMais/1.0 (painel de dados publicos; contato via repositorio)"
SPARQL = "https://query.wikidata.org/sparql"
DEEZER = "https://api.deezer.com/artist/{}"
SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "famosos.json"
CACHE = Path(os.environ.get("FAMOSOS_CACHE") or Path.home() / ".cache" / "brasilmais" / "famosos")
PAUSA = 1.2  # segundos entre consultas ao Wikidata

# grupo → (rótulo, ocupações do Wikidata, mínimo de idiomas da Wikipédia)
GRUPOS = {
    "musico": ("Músicos", ["Q639669", "Q177220"], 1),
    "ator": ("Atores", ["Q33999"], 1),
    "dublador": ("Dubladores", ["Q214917"], 1),
    "arquiteto": ("Arquitetos", ["Q42973"], 1),
    "engenheiro": ("Engenheiros", ["Q81096"], 1),
    "rede": ("Redes sociais", ["Q17125263", "Q2906862", "Q2045208", "Q57414145", "Q8246794", "Q4110598", "Q111263847"], 1),
}
# "Famosos por profissão": só quem tem alguma projeção (mínimo de idiomas) para a lista não virar um catálogo inteiro
PROFS = {
    "humorista": ("Humoristas", ["Q245068", "Q12406482"], 1),
    "apresentador": ("Apresentadores", ["Q947873", "Q13590141"], 2),
    "esportista": ("Esportistas", ["Q2066131"], 12),
    "escritor": ("Escritores", ["Q36180"], 8),
    "diretor": ("Diretores de cinema e TV", ["Q2526255"], 5),
    "modelo": ("Modelos", ["Q4610556"], 3),
    "jornalista": ("Jornalistas", ["Q1930187"], 6),
    "chef": ("Chefs de cozinha", ["Q3499072"], 2),
    "cientista": ("Cientistas", ["Q901"], 8),
    "danca": ("Dançarinos e coreógrafos", ["Q5716684", "Q2490358"], 3),
    "plastico": ("Artistas plásticos", ["Q1028181", "Q1281618"], 8),
    "empresario": ("Empresários", ["Q43845"], 8),
}
JANELAS = [(1, 2), (3, 5), (6, 11), (12, 100000)]
REDES = {  # qualificador do P8687 → chave
    "P2397": "yt", "P2003": "ig", "P6552": "x", "P2002": "x", "P7085": "tt", "P2013": "fb", "P1902": "sp",
}
CONTAS = {"P2003": "ig", "P2397": "yt", "P2002": "x", "P7085": "tt", "P2013": "fb", "P1902": "sp", "P2722": "dz"}
TIPOS_MUSICA = "wd:Q482994 wd:Q208569 wd:Q209939 wd:Q169930 wd:Q134556 wd:Q7366"
LABEL = 'SERVICE wikibase:label { bd:serviceParam wikibase:language "pt-br,pt,en". }'


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _cache_de(q):
    return CACHE / (hashlib.sha1(q.encode()).hexdigest() + ".json")


_ultimo = [0.0]


def sparql(q, tentativas=5):
    """Roda uma consulta (com cache em disco). Devolve a lista de linhas {var: valor}."""
    arq = _cache_de(q)
    if arq.exists():
        return json.loads(arq.read_text())
    ultimo = None
    for t in range(tentativas):
        espera = PAUSA - (time.time() - _ultimo[0])
        if espera > 0:
            time.sleep(espera)
        _ultimo[0] = time.time()
        req = urllib.request.Request(SPARQL, data=urllib.parse.urlencode({"query": q}).encode(),
                                     headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
        try:
            with urllib.request.urlopen(req, timeout=80) as r:
                lin = [{k: v["value"] for k, v in b.items()} for b in json.load(r)["results"]["bindings"]]
            CACHE.mkdir(parents=True, exist_ok=True)
            arq.write_text(json.dumps(lin, ensure_ascii=False))
            return lin
        except urllib.error.HTTPError as e:
            ultimo = e
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After") or 20))
            elif e.code in (500, 502, 503, 504):
                time.sleep(8 * (t + 1))
                if e.code == 500 and t >= 1:
                    break  # estouro de tempo da consulta: quem chama divide o lote
            else:
                break
        except Exception as e:  # rede, JSON cortado, tempo
            ultimo = e
            time.sleep(6 * (t + 1))
    raise RuntimeError(f"consulta falhou: {ultimo}")


def em_lotes(consulta, ids, tam):
    """consulta(ids) → texto SPARQL. Divide o lote ao meio quando o Wikidata não aguenta."""
    saida = []
    for i in range(0, len(ids), tam):
        parte = ids[i:i + tam]
        saida += _um_lote(consulta, parte)
    return saida


def _um_lote(consulta, parte):
    try:
        return sparql(consulta(parte))
    except RuntimeError:
        if len(parte) == 1:
            log("  sem resposta para", parte[0])
            return []
        meio = len(parte) // 2
        return _um_lote(consulta, parte[:meio]) + _um_lote(consulta, parte[meio:])


def qid(uri):
    return uri.rsplit("/", 1)[-1]


def rotulo(v):
    """O serviço de rótulos devolve o próprio Q... quando não há nome: isso não é nome."""
    return None if (not v or re.fullmatch(r"Q\d+", v)) else v.strip()


def genero_norm(g):
    """Gêneros vêm do Wikidata com a caixa misturada (\"Arrocha\", \"sertanejo\"): inicial minúscula, menos siglas (MPB, R&B)."""
    g = g.strip()
    return g if len(g) < 2 or g.isupper() or g[1].isupper() else g[0].lower() + g[1:]


def ano(s):
    m = re.match(r"^(-?\d{4})", s or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- listas por profissão
def listar_ocupacao(ocupacoes, min_sl, limite=None):
    vals = " ".join("wd:" + o for o in ocupacoes)
    pessoas = {}
    for a, b in JANELAS:
        if b < min_sl:
            continue
        a = max(a, min_sl)
        q = f'''SELECT ?p ?pLabel ?sl ?nasc ?morte ?desc WHERE {{
 VALUES ?o {{ {vals} }}
 ?p wdt:P27 wd:Q155; wdt:P106 ?oc; wikibase:sitelinks ?sl. ?oc wdt:P279* ?o.
 FILTER(?sl >= {a} && ?sl <= {b})
 OPTIONAL {{ ?p wdt:P569 ?nasc }} OPTIONAL {{ ?p wdt:P570 ?morte }}
 OPTIONAL {{ ?p schema:description ?desc FILTER(LANG(?desc) = "pt") }}
 {LABEL} }}'''
        for r in sparql(q):
            i = qid(r["p"])
            nome = rotulo(r.get("pLabel"))
            if not nome:
                continue
            p = pessoas.setdefault(i, {"n": nome, "s": int(r["sl"]), "a": None, "m": None, "d": None})
            na, nm = ano(r.get("nasc")), ano(r.get("morte"))
            if na and (p["a"] is None or na < p["a"]):
                p["a"] = na
            if nm and (p["m"] is None or nm < p["m"]):
                p["m"] = nm
            if r.get("desc") and not p["d"]:
                p["d"] = r["desc"]
        if limite and len(pessoas) >= limite:
            break
    return pessoas


def listar_seguidores(minimo=1_000_000):
    """Brasileiros com 1 milhão ou mais de seguidores registrados (qualquer profissão, menos quem só é político)."""
    q = f'''SELECT DISTINCT ?p ?pLabel ?sl ?nasc ?morte ?desc WHERE {{
 ?p wdt:P27 wd:Q155; p:P8687/ps:P8687 ?v; wikibase:sitelinks ?sl. FILTER(?v >= {minimo})
 FILTER NOT EXISTS {{ ?p wdt:P106 wd:Q82955 }}
 OPTIONAL {{ ?p wdt:P569 ?nasc }} OPTIONAL {{ ?p wdt:P570 ?morte }}
 OPTIONAL {{ ?p schema:description ?desc FILTER(LANG(?desc) = "pt") }}
 {LABEL} }}'''
    pessoas = {}
    for r in sparql(q):
        nome = rotulo(r.get("pLabel"))
        if not nome:
            continue
        p = pessoas.setdefault(qid(r["p"]), {"n": nome, "s": int(r["sl"]), "a": None, "m": None, "d": None})
        na, nm = ano(r.get("nasc")), ano(r.get("morte"))
        if na and (p["a"] is None or na < p["a"]):
            p["a"] = na
        if nm and (p["m"] is None or nm < p["m"]):
            p["m"] = nm
        if r.get("desc") and not p["d"]:
            p["d"] = r["desc"]
    return pessoas


# ---------------------------------------------------------------- propriedades em lote
def V(ids):
    return " ".join("wd:" + i for i in ids)


def q_generos(ids):
    return f'SELECT ?p ?gLabel WHERE {{ VALUES ?p {{ {V(ids)} }} ?p wdt:P136 ?g. {LABEL} }}'


def q_ocupacoes(ids):
    return f'SELECT ?p ?oLabel WHERE {{ VALUES ?p {{ {V(ids)} }} ?p wdt:P106 ?o. {LABEL} }}'


def q_local(ids):
    return f'''SELECT ?p ?cLabel ?iso WHERE {{ VALUES ?p {{ {V(ids)} }} ?p wdt:P19 ?c.
 OPTIONAL {{ ?c wdt:P131* ?u. ?u wdt:P300 ?iso. FILTER(REGEX(?iso, "^BR-[A-Z]{{2}}$")) }} {LABEL} }}'''


def q_contas(ids):
    un = " UNION ".join(f'{{ ?p wdt:{p} ?v. BIND("{p}" AS ?k) }}' for p in CONTAS)
    return f'SELECT ?p ?k ?v WHERE {{ VALUES ?p {{ {V(ids)} }} {un} }}'


def q_seguidores(ids):
    qs = " ".join("pq:" + p for p in REDES)
    return f'''SELECT ?p ?v ?d ?q WHERE {{ VALUES ?p {{ {V(ids)} }} VALUES ?q {{ {qs} }}
 ?p p:P8687 ?st. ?st ps:P8687 ?v; pq:P585 ?d. ?st ?q ?x. }}'''


def q_premios(ids):
    return f'''SELECT ?p ?aLabel ?asl WHERE {{ VALUES ?p {{ {V(ids)} }} ?p wdt:P166 ?a. ?a wikibase:sitelinks ?asl. {LABEL} }}'''


def q_wiki(ids):
    return f'''SELECT ?p ?t WHERE {{ VALUES ?p {{ {V(ids)} }} ?a schema:about ?p; schema:isPartOf <https://pt.wikipedia.org/>; schema:name ?t. }}'''


def _obras(rel, ids, extra=""):
    return f'''SELECT ?p ?wLabel ?wsl (MIN(?dt) AS ?data) WHERE {{ VALUES ?p {{ {V(ids)} }} {rel} ?w wikibase:sitelinks ?wsl. {extra}
 OPTIONAL {{ ?w wdt:P577 ?dt }} OPTIONAL {{ ?w wdt:P571 ?dt }} {LABEL} }} GROUP BY ?p ?wLabel ?wsl'''


def q_atuacao(ids):
    return _obras("?w wdt:P161 ?p.", ids)


def q_voz(ids):
    return _obras("?w wdt:P725 ?p.", ids)


def q_musica(ids):
    return _obras("?w wdt:P175 ?p; wdt:P31 ?tp. VALUES ?tp {" + TIPOS_MUSICA + "}", ids)


def q_projetos(ids):
    return _obras("{ ?w wdt:P84 ?p } UNION { ?w wdt:P287 ?p }", ids)


def q_notavel(ids):
    return _obras("?p wdt:P800 ?w.", ids)


def juntar_obras(linhas, tipo, destino):
    for r in linhas:
        t = rotulo(r.get("wLabel"))
        if not t:
            continue
        d = destino.setdefault(qid(r["p"]), {})
        chave = (t.lower(), tipo)
        if chave not in d:
            d[chave] = [t, ano(r.get("data")), tipo, int(r.get("wsl") or 0)]


def deezer_fas(id_, tentativas=4):
    for t in range(tentativas):
        try:
            req = urllib.request.Request(DEEZER.format(id_), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            if "error" in d:
                if d["error"].get("code") == 4:  # limite de requisições
                    time.sleep(6)
                    continue
                return None
            return d.get("nb_fan")
        except Exception:
            time.sleep(2 * (t + 1))
    return None


def main(teste=False, so_lista=False):
    hoje = date.today().isoformat()
    limite = 25 if teste else None
    pessoas, grupos = {}, {}
    todos = {**{k: v for k, v in GRUPOS.items()}, **{"prof:" + k: v for k, v in PROFS.items()}}
    for chave, (rot, ocup, minsl) in todos.items():
        log("lista", chave)
        for i, p in listar_ocupacao(ocup, minsl, limite).items():
            pessoas.setdefault(i, p)
            grupos.setdefault(i, set()).add(chave)
    if not teste:
        for i, p in listar_seguidores().items():
            pessoas.setdefault(i, p)
            grupos.setdefault(i, set()).add("rede")
    log("pessoas:", len(pessoas))
    if so_lista:
        return
    ids = sorted(pessoas)
    com = lambda g: [i for i in ids if g in grupos[i]]  # noqa: E731

    generos, ocupacoes, local, contas, segs, prem, wiki = {}, {}, {}, {}, {}, {}, {}
    log("gêneros");     [generos.setdefault(qid(r["p"]), set()).add(rotulo(r.get("gLabel"))) for r in em_lotes(q_generos, ids, 200) if rotulo(r.get("gLabel"))]
    log("ocupações");   [ocupacoes.setdefault(qid(r["p"]), set()).add(rotulo(r.get("oLabel"))) for r in em_lotes(q_ocupacoes, ids, 200) if rotulo(r.get("oLabel"))]
    log("local")
    for r in em_lotes(q_local, ids, 150):
        i = qid(r["p"])
        atual = local.get(i)
        if not atual or (r.get("iso") and not atual[1]):
            local[i] = [rotulo(r.get("cLabel")), (r.get("iso") or "")[3:] or None]
    log("contas")
    for r in em_lotes(q_contas, ids, 150):
        contas.setdefault(qid(r["p"]), {}).setdefault(CONTAS[r["k"]], r["v"])
    log("seguidores")
    for r in em_lotes(q_seguidores, ids, 100):
        rede = REDES[qid(r["q"])]
        d = segs.setdefault(qid(r["p"]), {})
        v, dt = int(float(r["v"])), r["d"][:10]
        if rede not in d or dt > d[rede][1]:
            d[rede] = [v, dt]
    log("prêmios")
    for r in em_lotes(q_premios, ids, 100):
        n = rotulo(r.get("aLabel"))
        if n:
            prem.setdefault(qid(r["p"]), {})[n] = int(r.get("asl") or 0)
    log("wikipédia")
    for r in em_lotes(q_wiki, ids, 200):
        wiki.setdefault(qid(r["p"]), r["t"])

    obras = {}
    log("obras: atuação");   juntar_obras(em_lotes(q_atuacao, [i for i in com("ator") + com("dublador")], 40), "atuação", obras)
    log("obras: voz");       juntar_obras(em_lotes(q_voz, com("dublador"), 40), "voz", obras)
    log("obras: música");    juntar_obras(em_lotes(q_musica, com("musico"), 40), "música", obras)
    log("obras: projetos");  juntar_obras(em_lotes(q_projetos, com("arquiteto") + com("engenheiro"), 40), "projeto", obras)
    log("obras: notáveis");  juntar_obras(em_lotes(q_notavel, ids, 100), "obra notável", obras)

    log("deezer")
    dz = {}
    ids_dz = [(i, contas[i]["dz"]) for i in ids if "dz" in contas.get(i, {}) and "musico" in grupos[i]]
    for k, (i, d) in enumerate(ids_dz):
        f = deezer_fas(d)
        if f is not None:
            dz[i] = [int(f), hoje, d]
        time.sleep(0.12)
        if k % 100 == 0:
            log("  deezer", k, "/", len(ids_dz))

    saida = []
    for i in ids:
        p = pessoas[i]
        ob = list(obras.get(i, {}).values())
        conhecidas = sorted(ob, key=lambda o: (-o[3], -(o[1] or 0)))[:5]
        recentes = sorted([o for o in ob if o[1]], key=lambda o: (-o[1], -o[3]))[:4]
        premios = sorted(prem.get(i, {}).items(), key=lambda kv: -kv[1])
        reg = {"q": i, "n": p["n"], "g": sorted(grupos[i]), "s": p["s"]}
        if p["d"]: reg["d"] = p["d"]
        if p["a"]: reg["a"] = p["a"]
        if p["m"]: reg["m"] = p["m"]
        if i in local and local[i][0]: reg["c"] = local[i][0]
        if i in local and local[i][1]: reg["u"] = local[i][1]
        if generos.get(i): reg["ge"] = sorted({genero_norm(x) for x in generos[i]}, key=str.lower)[:8]
        if ocupacoes.get(i): reg["oc"] = sorted(ocupacoes[i], key=str.lower)[:6]
        if premios: reg["pr"] = [len(premios), [k for k, _ in premios[:3]]]
        if conhecidas: reg["ob"] = [[o[0], o[1], o[2]] for o in conhecidas]
        if recentes: reg["ob2"] = [[o[0], o[1], o[2]] for o in recentes]
        if segs.get(i): reg["rs"] = segs[i]
        if contas.get(i): reg["ct"] = {k: v for k, v in contas[i].items() if k != "dz"}
        if i in dz: reg["dz"] = dz[i]
        if i in wiki: reg["wp"] = wiki[i]
        saida.append(reg)
    saida.sort(key=lambda r: -r["s"])
    contagem = {k: sum(1 for r in saida if k in r["g"]) for k in todos}
    doc = {
        "gerado": hoje,
        "grupos": {k: {"nome": v[0], "n": contagem[k]} for k, v in todos.items()},
        "p": saida,
    }
    if not teste:
        SAIDA.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        log("gravado", SAIDA, len(saida), "pessoas")
    else:
        print(json.dumps(doc, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main(teste="--teste" in sys.argv, so_lista="--so-lista" in sys.argv)
