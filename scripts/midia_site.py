"""Fotos oficiais e logos para o site sem servidor (o site publicado não pode carregar imagens de outros endereços).

Gera em `site/midia/`:
- `logos.json`: logos dos partidos e brasões das polícias, da Wikipédia/Wikimedia Commons (com o arquivo de origem);
- `fotos_<N>.json`: fotos oficiais em miniatura (Câmara, Senado e TSE), em blocos por hash da chave;
- `indice.json`: quantos blocos e de onde vem cada coisa.

Chaves das fotos: a URL oficial (Câmara/Senado, como está em `foto_url`) ou `tse:<sq_candidato>`.
Uso: python -m scripts.midia_site site/midia
"""
import base64
import io
import json
import logging
import os
import re
import sys
import zipfile
from datetime import date

import httpx

log = logging.getLogger("brasilplus.midia")
UA = {"User-Agent": "BRASIL+ (dados publicos; github.com/felponesx/politica)"}
WIKI = "https://pt.wikipedia.org/w/api.php"
BLOCOS = 16

# sigla do partido (como vem da Câmara/TSE) -> artigo da Wikipédia
PARTIDOS = {
    "PT": "Partido dos Trabalhadores", "PL": "Partido Liberal (2006)", "UNIÃO": "União Brasil", "PP": "Progressistas",
    "MDB": "Movimento Democrático Brasileiro (1980)", "PSD": "Partido Social Democrático (2011)",
    "REPUBLICANOS": "Republicanos (partido político)", "PSDB": "Partido da Social Democracia Brasileira",
    "PDT": "Partido Democrático Trabalhista", "PSB": "Partido Socialista Brasileiro", "PSOL": "Partido Socialismo e Liberdade",
    "PODE": "Podemos (Brasil)", "AVANTE": "Avante", "PCdoB": "Partido Comunista do Brasil", "PV": "Partido Verde (Brasil)",
    "CIDADANIA": "Cidadania (partido político)", "NOVO": "Partido Novo", "SOLIDARIEDADE": "Solidariedade (partido político)",
    "PRD": "Partido Renovação Democrática", "REDE": "Rede Sustentabilidade", "AGIR": "Agir (Brasil)",
    "MOBILIZA": "Mobilização Nacional", "DC": "Democracia Cristã (Brasil)", "PMB": "Democrata (Brasil)",
    "DEMOCRATA": "Democrata (Brasil)", "PSTU": "Partido Socialista dos Trabalhadores Unificado",
    "PCO": "Partido da Causa Operária", "UP": "Unidade Popular", "PCB": "Partido Comunista Brasileiro",
    "MISSÃO": "Partido Missão", "PRTB": "Partido Renovador Trabalhista Brasileiro", "PSL": "Partido Social Liberal",
    "DEM": "Democratas (Brasil)", "PTB": "Partido Trabalhista Brasileiro (1979)", "PSC": "Partido Social Cristão",
    "PROS": "Partido Republicano da Ordem Social", "PATRIOTA": "Patriota (Brasil)", "PTC": "Agir (Brasil)",
    "PHS": "Partido Humanista da Solidariedade", "PPL": "Partido Pátria Livre", "PRP": "Partido Republicano Progressista",
    "PR": "Partido Liberal (2006)", "PPS": "Cidadania (partido político)", "PMN": "Mobilização Nacional",
}
# polícias e unidades: chave usada no site -> artigo
POLICIAS_FIXAS = {
    "pf": "Polícia Federal (Brasil)", "prf": "Polícia Rodoviária Federal", "fn": "Força Nacional de Segurança Pública",
    "spf": "Sistema Penitenciário Federal", "receita": "Receita Federal do Brasil",
    "u:SP:ROTA": "Rondas Ostensivas Tobias de Aguiar", "u:RJ:BOPE": "Batalhão de Operações Policiais Especiais",
    "u:BR:COT": "Comando de Operações Táticas", "u:RJ:CORE": "Coordenadoria de Recursos Especiais",
    "u:BR:FNSP": "Força Nacional de Segurança Pública", "u:SP:ROMU": "Guarda Civil Metropolitana de São Paulo",
    "u:BR:SPF": "Sistema Penitenciário Federal", "gcm:SP": "Guarda Civil Metropolitana de São Paulo",
}
NOMES_UF = {"AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
            "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
            "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
            "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
            "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
            "SE": "Sergipe", "TO": "Tocantins"}

cli = httpx.Client(timeout=60, follow_redirects=True, headers=UA)


def fnv1a(texto: str) -> int:
    h = 0x811C9DC5
    for c in texto:
        h = ((h ^ ord(c)) * 0x01000193) & 0xFFFFFFFF
    return h


def miniatura(bruto: bytes, altura: int, formato: str = "JPEG") -> str | None:
    """Imagem reduzida como data URI (JPEG para fotos, PNG com transparência para logos)."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(bruto))
        im.load()
    except Exception:
        return None
    if im.height > altura:
        im = im.resize((max(1, round(im.width * altura / im.height)), altura), Image.LANCZOS)
    out = io.BytesIO()
    if formato == "JPEG":
        im.convert("RGB").save(out, "JPEG", quality=70, optimize=True, progressive=True)
        mime = "image/jpeg"
    else:
        if im.mode not in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
        im.save(out, "PNG", optimize=True)
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(out.getvalue()).decode()


def wiki_imagens(titulos: list[str]) -> dict:
    """{título pedido: {thumb, arquivo, pagina, efetivo}} pela API da Wikipédia (segue redirecionamentos)."""
    out = {}
    for k in range(0, len(titulos), 20):
        lote = titulos[k:k + 20]
        try:
            d = cli.get(WIKI, params={"action": "query", "format": "json", "redirects": 1, "prop": "pageimages|revisions",
                                      "piprop": "thumbnail|name", "pithumbsize": 200, "rvprop": "content", "rvslots": "main",
                                      "rvsection": 0, "titles": "|".join(lote)}).json()
        except Exception as e:
            log.warning("Wikipédia: %s", e)
            continue
        alias = {r["from"]: r["to"] for r in d.get("query", {}).get("redirects", [])}
        alias.update({n["from"]: n["to"] for n in d.get("query", {}).get("normalized", [])})
        por_titulo = {}
        for pg in d.get("query", {}).get("pages", {}).values():
            txt = ((pg.get("revisions") or [{}])[0].get("slots", {}).get("main", {}).get("*") or "")
            ef = re.search(r"\|\s*efetivo\s*=\s*([^\n|]*)", txt, re.I)
            efetivo = None
            if ef:
                nums = re.findall(r"\d{1,3}(?:\.\d{3})+|\d{3,}", re.sub(r"\{\{[^}]*\}\}", " ", ef.group(1)))
                efetivo = int(nums[0].replace(".", "")) if nums else None
            por_titulo[pg.get("title")] = {"thumb": (pg.get("thumbnail") or {}).get("source"), "arquivo": pg.get("pageimage"),
                                           "pagina": "https://pt.wikipedia.org/wiki/" + str(pg.get("title")).replace(" ", "_"),
                                           "efetivo_wikipedia": efetivo}
        for t in lote:
            alvo = alias.get(alias.get(t, t), alias.get(t, t))
            if alvo in por_titulo:
                out[t] = por_titulo[alvo]
    return out


def buscar_titulo(consulta: str, deve_ter: list[str]) -> str | None:
    """Primeiro artigo da busca da Wikipédia cujo título contém todas as palavras pedidas."""
    try:
        d = cli.get(WIKI, params={"action": "query", "format": "json", "list": "search", "srsearch": consulta,
                                  "srlimit": 5}).json()
    except Exception:
        return None
    for r in d.get("query", {}).get("search", []):
        t = r["title"]
        if all(p.lower() in t.lower() for p in deve_ter):
            return t
    return None


def logos() -> dict:
    out = {"partidos": {}, "policias": {}}
    titulos_pol = dict(POLICIAS_FIXAS)
    for uf, nome in NOMES_UF.items():
        for chave, base, extra in (("pm", "Polícia Militar", ["Militar"]), ("pc", "Polícia Civil", ["Civil"]),
                                   ("cbm", "Corpo de Bombeiros Militar", ["Bombeiros"]), ("pp", "Polícia Penal", ["Penal"])):
            if chave == "pm" and uf == "RS":
                titulos_pol["pm:RS"] = "Brigada Militar do Rio Grande do Sul"
                continue
            t = buscar_titulo(f"{base} {nome}", extra + [nome.split()[-1]])
            if t:
                titulos_pol[f"{chave}:{uf}"] = t
    info = wiki_imagens(sorted(set(PARTIDOS.values()) | set(titulos_pol.values())))
    def baixar(meta, altura):
        if not meta or not meta.get("thumb"):
            return None
        try:
            r = cli.get(meta["thumb"])
            return miniatura(r.content, altura, "PNG") if r.status_code == 200 else None
        except Exception:
            return None
    cache = {}
    for sigla, t in PARTIDOS.items():
        if t not in cache:
            cache[t] = baixar(info.get(t), 64)
        if cache[t]:
            out["partidos"][sigla] = {"img": cache[t], "arquivo": info[t].get("arquivo"), "pagina": info[t]["pagina"]}
    for chave, t in titulos_pol.items():
        if t not in cache:
            cache[t] = baixar(info.get(t), 96)
        if cache[t]:
            out["policias"][chave] = {"img": cache[t], "titulo": t, "arquivo": info[t].get("arquivo"),
                                      "pagina": info[t]["pagina"], "efetivo_wikipedia": info[t].get("efetivo_wikipedia")}
    log.info("logos: %d partidos, %d polícias", len(out["partidos"]), len(out["policias"]))
    return out


def fotos_congresso(db) -> dict:
    from sqlalchemy import select

    from app.models import Parlamentar
    out = {}
    for url, in db.execute(select(Parlamentar.foto_url).where(Parlamentar.foto_url.is_not(None),
                                                         Parlamentar.em_exercicio.is_(True))):
        try:
            r = cli.get(url)
            img = miniatura(r.content, 96) if r.status_code == 200 else None
        except Exception:
            img = None
        if img:
            out[url] = img
    log.info("fotos do Congresso: %d", len(out))
    return out


def fotos_tse(db, anos=(2022, 2026)) -> dict:
    """Eleitos (menos vereadores e prefeitos de fora das capitais) e todos os candidatos a presidente, governador e
    senador de cada ano, a partir dos zips de fotos do TSE por estado."""
    from sqlalchemy import or_, select

    from app.models import Candidato
    out = {}
    for ano in anos:
        q = select(Candidato.sq_candidato, Candidato.uf).where(Candidato.ano == ano, or_(
            Candidato.cargo.in_(["PRESIDENTE", "GOVERNADOR", "SENADOR"]),
            Candidato.resultado.ilike("ELEITO%")), Candidato.cargo.not_in(["VEREADOR", "PREFEITO", "VICE-PREFEITO"]))
        por_uf = {}
        for sq, uf in db.execute(q):
            por_uf.setdefault(uf or "BR", set()).add(str(sq))
        for uf, sqs in sorted(por_uf.items()):
            url = f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/fotos/foto_cand{ano}_{uf}_div.zip"
            try:
                caminho = f"/tmp/fotos_{ano}_{uf}.zip"
                with cli.stream("GET", url, timeout=600) as r:
                    if r.status_code != 200:
                        continue
                    with open(caminho, "wb") as f:
                        for b in r.iter_bytes(1 << 20):
                            f.write(b)
                with zipfile.ZipFile(caminho) as z:
                    for nome in z.namelist():
                        m = re.match(r"F[A-Z]{2}(\d+)_div\.\w+$", os.path.basename(nome))
                        if m and m.group(1) in sqs:
                            img = miniatura(z.read(nome), 96)
                            if img:
                                out[f"tse:{m.group(1)}"] = img
                os.remove(caminho)
            except Exception as e:
                log.warning("fotos TSE %s %s: %s", ano, uf, e)
    log.info("fotos do TSE: %d", len(out))
    return out


def nomes_indicados(site="site/index.html") -> list[str]:
    """Nomes de ministros, tribunais e colegiados que o site lista (NO_CARGO e MINISTROS)."""
    try:
        txt = open(site, encoding="utf-8").read()
    except OSError:
        return []
    nomes = set()
    for ini, fim in (("const NO_CARGO=[", "function painelNoCargo"), ("const MINISTROS=[", "const AREA_MIN")):
        i = txt.find(ini)
        j = txt.find(fim, i)
        if i < 0 or j < 0:
            continue
        bloco = txt[i:j]
        if ini.startswith("const MINISTROS"):
            nomes |= {re.sub(r" \(.*\)$", "", m) for m in re.findall(r'\["[^"]+","([^"]+)",\d\]', bloco)}
        else:
            nomes |= set(re.findall(r'\[\s*"([^"]+)",\s*"[^"]*",\s*"[^"]*"\s*\]', bloco))
    return sorted(n for n in nomes if n != "Vaga aberta")


def fotos_wikipedia(nomes: list[str]) -> dict:
    """Retrato da Wikipédia de cada nome, só quando o verbete é de uma autoridade brasileira (evita homônimos)."""
    out = {}
    pista = re.compile(r"(ministr|jurista|juiz|magistrad|polític|advogad|economist|militar|diplomat|servidor|presidente|"
                       r"desembargad|procurador|governador|deputad|senador|general|almirante|brigadeiro)", re.I)
    for k in range(0, len(nomes), 20):
        lote = nomes[k:k + 20]
        try:
            d = cli.get(WIKI, params={"action": "query", "format": "json", "redirects": 1, "prop": "pageimages|extracts",
                                      "piprop": "thumbnail", "pithumbsize": 200, "exintro": 1, "explaintext": 1,
                                      "exsentences": 2, "titles": "|".join(lote)}).json()
        except Exception as e:
            log.warning("Wikipédia (retratos): %s", e)
            continue
        alias = {r["from"]: r["to"] for r in d.get("query", {}).get("redirects", [])}
        alias.update({n["from"]: n["to"] for n in d.get("query", {}).get("normalized", [])})
        paginas = {pg.get("title"): pg for pg in d.get("query", {}).get("pages", {}).values()}
        for nome in lote:
            pg = paginas.get(alias.get(alias.get(nome, nome), alias.get(nome, nome)))
            if not pg or "missing" in pg:
                continue
            ext = pg.get("extract") or ""
            thumb = (pg.get("thumbnail") or {}).get("source")
            if not thumb or "brasil" not in ext.lower() or not pista.search(ext) or "desambigua" in ext.lower():
                continue
            try:
                r = cli.get(thumb)
                img = miniatura(r.content, 96) if r.status_code == 200 else None
            except Exception:
                img = None
            if img:
                out["wiki:" + nome] = img
    log.info("retratos da Wikipédia: %d de %d", len(out), len(nomes))
    return out


def main(pasta: str):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db import SessionLocal
    os.makedirs(pasta, exist_ok=True)
    lg = logos()
    with open(os.path.join(pasta, "logos.json"), "w", encoding="utf-8") as f:
        json.dump(lg, f, ensure_ascii=False, separators=(",", ":"))
    with SessionLocal() as db:
        fotos = {**fotos_congresso(db), **fotos_tse(db), **fotos_wikipedia(nomes_indicados())}
    blocos = [{} for _ in range(BLOCOS)]
    for k, v in fotos.items():
        blocos[fnv1a(k) % BLOCOS][k] = v
    for i, b in enumerate(blocos):
        with open(os.path.join(pasta, f"fotos_{i}.json"), "w", encoding="utf-8") as f:
            json.dump(b, f, separators=(",", ":"))
    with open(os.path.join(pasta, "indice.json"), "w", encoding="utf-8") as f:
        json.dump({"gerado_em": date.today().isoformat(), "blocos": BLOCOS, "fotos": len(fotos),
                   "partidos": len(lg["partidos"]), "policias": len(lg["policias"]),
                   "fontes": {"fotos": "Câmara dos Deputados, Senado Federal, TSE (DivulgaCand) e, para ministros e "
                                       "tribunais, retratos da Wikipédia/Wikimedia Commons",
                              "logos": "Wikipédia / Wikimedia Commons (arquivo indicado em cada logo)"}}, f, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "site/midia")
