"""Fotos oficiais e logos para o site sem servidor (o site publicado não pode carregar imagens de outros endereços).

Gera em `site/midia/`:
- `logos.json` (índice) + `logos_<grupo>.json`: logos dos partidos, brasões das polícias, veículos e empresas, da
  Wikipédia/Wikimedia Commons (com o arquivo de origem), em WebP e um arquivo por grupo (`scripts/logos_arquivo.py`);
- `fotos_<N>.json`: fotos oficiais em miniatura (Câmara, Senado e TSE), em blocos por hash da chave;
- `indice.json`: quantos blocos e de onde vem cada coisa.

Chaves das fotos: a URL oficial (Câmara/Senado, como está em `foto_url`) ou `tse:<sq_candidato>`.
Uso: python -m scripts.midia_site site/midia
"""
import base64
import html
import io
import json
import logging
import os
import re
import unicodedata
import sys
import zipfile
from datetime import date

import httpx

log = logging.getLogger("brasilplus.midia")
UA = {"User-Agent": "BRASILmais-midia/1.0 (https://github.com/felponesx/politica; dados publicos)"}
WIKI = "https://pt.wikipedia.org/w/api.php"
# fotos em 64 blocos (~0,6 MB cada): a tela baixa só os blocos das pessoas que mostra
BLOCOS = 64

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
# veículos de notícias: nome usado no site -> título do artigo na Wikipédia (o logo vem do artigo)
VEICULOS = {
    "g1": "G1", "CNN Brasil": "CNN Brasil", "O Globo": "O Globo", "Folha de S.Paulo": "Folha de S.Paulo",
    "Estadão": "O Estado de S. Paulo", "Agência Câmara / TV Câmara": "TV Câmara", "Agência Senado": "Agência Senado",
    "Agência Brasil": "Agência Brasil", "UOL": "UOL", "Poder360": "Poder360", "Metrópoles": "Metrópoles (site)",
    "CartaCapital": "CartaCapital", "Congresso em Foco": "Congresso em Foco", "InfoMoney": "InfoMoney",
    "Exame": "Exame (revista)", "Consultor Jurídico (Conjur)": "Consultor Jurídico", "Migalhas": "Migalhas",
    "Conselho Nacional de Justiça": "Conselho Nacional de Justiça",
}
NOMES_UF = {"AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
            "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
            "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
            "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
            "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
            "SE": "Sergipe", "TO": "Tocantins"}

_cli = httpx.Client(timeout=60, follow_redirects=True, headers=UA)


class _Educado:
    """Pedidos à Wikipédia/Wikimedia sem pressa: pausa entre pedidos e nova tentativa quando pedem para esperar (429)."""
    def __init__(self, pausa=0.6):
        self.pausa, self.ultimo = pausa, 0.0

    def get(self, url, **kw):
        import time
        wiki = "wiki" in url
        for tentativa in range(6):
            if wiki:
                espera = self.pausa - (time.monotonic() - self.ultimo)
                if espera > 0:
                    time.sleep(espera)
                self.ultimo = time.monotonic()
            r = _cli.get(url, **kw)
            if r.status_code not in (429, 503) or not wiki:
                return r
            # arquivo original (sem miniatura) no upload.wikimedia.org: o limite para robôs é duro e cada espera custa
            # um minuto. Pede a miniatura padrão de 120 px do mesmo arquivo e segue em frente.
            m = re.match(r"(https://upload\.wikimedia\.org/wikipedia/commons)/(\w)/(\w\w)/([^/?]+)", url)
            if m and "/thumb/" not in url:
                alt = f"{m.group(1)}/thumb/{m.group(2)}/{m.group(3)}/{m.group(4)}/120px-{m.group(4)}"
                if m.group(4).lower().endswith(".svg"):
                    alt += ".png"
                r2 = _cli.get(alt, **kw)
                return r2 if r2.status_code == 200 else r
            time.sleep(min(60, float(r.headers.get("retry-after") or 0) or 5 * 2 ** tentativa))
        return r

    def stream(self, *a, **kw):
        return _cli.stream(*a, **kw)


cli = _Educado()


def fnv1a(texto: str) -> int:
    h = 0x811C9DC5
    for c in texto:
        h = ((h ^ ord(c)) * 0x01000193) & 0xFFFFFFFF
    return h


# tamanhos máximos (nunca amplia: se a fonte for menor, fica como veio). 360 px de altura é o que cabe na cópia publicada
# (limite de 256 MB por versão do Artifact); 720p/1080p reais de milhares de retratos passariam de 500 MB.
ALTURA_FOTO = 360
ALTURA_LOGO = 256


def foto_maior(url: str) -> str:
    """A Câmara serve o retrato pequeno em .../bandep/ID.jpg e o grande em .../bandep/ID.jpgmaior.jpg."""
    return url + "maior.jpg" if re.search(r"camara\.leg\.br/internet/deputado/bandep/\d+\.jpg$", url) else url


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
        im.convert("RGB").save(out, "JPEG", quality=78, optimize=True, progressive=True)
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
                                      "piprop": "thumbnail|name", "pithumbsize": 800, "rvprop": "content", "rvslots": "main",
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


def wiki_resumos(titulos: list[str]) -> dict:
    """{título: primeira frase do verbete} para os artigos pedidos."""
    out = {}
    for k in range(0, len(titulos), 20):
        lote = titulos[k:k + 20]
        try:
            d = cli.get(WIKI, params={"action": "query", "format": "json", "redirects": 1, "prop": "extracts",
                                      "exintro": 1, "explaintext": 1, "exsentences": 1, "titles": "|".join(lote)}).json()
        except Exception:
            continue
        alias = {r["from"]: r["to"] for r in d.get("query", {}).get("redirects", [])}
        alias.update({n["from"]: n["to"] for n in d.get("query", {}).get("normalized", [])})
        por = {pg.get("title"): _limpa(pg.get("extract") or "")[:240] for pg in d.get("query", {}).get("pages", {}).values()}
        for t in lote:
            out[t] = por.get(alias.get(alias.get(t, t), alias.get(t, t)), "")
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


# ---- batalhões e unidades especiais: descobertos na Wikipédia, só entram os que têm artigo ----
TIPOS_UNIDADE = ["Batalhão de Operações Especiais", "Batalhão de Operações Policiais Especiais", "Batalhão de Choque",
                 "Batalhão de Polícia de Choque", "Rondas Ostensivas", "Rondas Táticas", "Grupo de Ações Táticas",
                 "Grupo Tático", "Comando de Operações Especiais", "Batalhão de Missões Especiais",
                 "Batalhão de Ações com Cães", "Comando de Aviação", "Esquadrão antibombas", "Batalhão Rodoviário",
                 "Batalhão Ambiental", "Companhia de Operações Especiais"]
_RE_UNID = re.compile(r"^(Batalh[ãa]o|Rondas?|Grupo|Comando|Companhia|Esquadr[ãa]o|Grupamento|Coordenadoria|Regimento|"
                      r"Delegacia|Divis[ãa]o|Tropa|Pelot[ãa]o)\b", re.I)
_PROIBIDO = re.compile(r"ex[eé]rcito|marinha|fuzileiros|for[cç]a a[eé]rea|\bFAB\b|desambigua|lista de", re.I)


def _limpa(txt: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", txt or ""))).strip()


def sigla_de(titulo: str, trecho: str = "") -> str:
    """Sigla da unidade: a que vier entre parênteses no título ou no trecho; senão as iniciais do nome."""
    for t in (titulo, trecho):
        m = re.search(r"\(([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9º.\-]{2,10})\)", t or "")
        if m:
            return m.group(1)
    nome = re.sub(r"\s*\(.*\)", "", titulo)
    ini = "".join(w[0] for w in re.split(r"\s+", nome) if w[:1].isupper() and len(w) > 3)
    return ini.upper() if len(ini) >= 2 else nome[:12]


def unidade_de_resultado(titulo: str, trecho: str, nome_uf: str, uf: str) -> dict | None:
    """Decide se um resultado da busca é uma unidade policial do estado e devolve {uf, corp, sigla, nome}."""
    trecho = _limpa(trecho)
    texto = f"{titulo} {trecho}"
    if not _RE_UNID.match(titulo) or _PROIBIDO.search(texto):
        return None
    if nome_uf.lower() not in texto.lower() and f"({uf})" not in titulo:
        return None
    if not re.search(r"pol[ií]cia|bombeiro|guarda", texto, re.I):
        return None
    corp = "cbm" if re.search(r"bombeiro", texto, re.I) and not re.search(r"pol[ií]cia militar", texto, re.I) else \
        "pc" if re.search(r"pol[ií]cia civil", texto, re.I) else "pm"
    return {"uf": uf, "corp": corp, "sigla": sigla_de(titulo, trecho), "nome": re.sub(r"\s*\(.*\)", "", titulo).strip(),
            "titulo": titulo}


def descobrir_unidades(maximo_por_uf: int = 8) -> list[dict]:
    achadas, vistos = [], set()
    for uf, nome in NOMES_UF.items():
        n = 0
        for tipo in TIPOS_UNIDADE:
            if n >= maximo_por_uf:
                break
            try:
                d = cli.get(WIKI, params={"action": "query", "format": "json", "list": "search", "srlimit": 5,
                                          "srsearch": f"{tipo} Polícia {nome}"}).json()
            except Exception:
                continue
            for r in d.get("query", {}).get("search", []):
                u = unidade_de_resultado(r["title"], r.get("snippet", ""), nome, uf)
                if u and re.match(r"^(PM|PC|CBM|BM)[A-Z]{0,4}$", u["sigla"]):  # a própria corporação, não uma unidade
                    u = None
                if u and u["sigla"] in ("OPM", "OBM", "UPM"):  # "organização policial militar": termo genérico, não a sigla
                    u = None
                if u and (u["titulo"] not in vistos and f"{uf}:{u['sigla']}" not in vistos) and n < maximo_por_uf:
                    vistos.add(f"{uf}:{u['sigla']}")
                    vistos.add(u["titulo"])
                    achadas.append(u)
                    n += 1
    log.info("unidades encontradas na Wikipédia: %d", len(achadas))
    return achadas



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
    # brasão de cada estado: aparece nas polícias (PM, PC, penal, bombeiros, guardas) que não têm logo próprio
    titulos_uf = {}
    for uf, nome in NOMES_UF.items():
        t = buscar_titulo(f"Brasão {'do' if uf in ('RJ', 'RN', 'RS', 'PA', 'PR', 'PI', 'MA', 'AM', 'AP', 'AC', 'CE', 'ES', 'TO', 'DF') else 'de'} {nome}",
                          ["Brasão", nome.split()[-1]])
        if t:
            titulos_uf[uf] = t
    info_uf = wiki_imagens(sorted(set(titulos_uf.values())))
    titulos_vei = dict(VEICULOS)
    info_v = wiki_imagens(sorted(set(titulos_vei.values())))
    for nome, t in VEICULOS.items():  # sem imagem no título direto: tenta achar o artigo pela busca
        if not (info_v.get(t) or {}).get("thumb"):
            alt = buscar_titulo(nome.split(" (")[0].split(" / ")[-1], [nome.split(" (")[0].split(" / ")[-1].split()[0]])
            if alt and alt != t:
                titulos_vei[nome] = alt
                info_v.update(wiki_imagens([alt]))
    out["veiculos"] = {}
    unidades = descobrir_unidades()
    for u in unidades:
        titulos_pol[f"u:{u['uf']}:{u['sigla']}"] = u["titulo"]
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
            cache[t] = baixar(info.get(t), ALTURA_LOGO)
        if cache[t]:
            out["partidos"][sigla] = {"img": cache[t], "arquivo": info[t].get("arquivo"), "pagina": info[t]["pagina"]}
    for chave, t in titulos_pol.items():
        if t not in cache:
            cache[t] = baixar(info.get(t), ALTURA_LOGO)
        if cache[t]:
            out["policias"][chave] = {"img": cache[t], "titulo": t, "arquivo": info[t].get("arquivo"),
                                      "pagina": info[t]["pagina"], "efetivo_wikipedia": info[t].get("efetivo_wikipedia")}
    for nome, t in titulos_vei.items():
        meta = info_v.get(t)
        img = baixar(meta, ALTURA_LOGO)
        if img:
            out["veiculos"][nome] = {"img": img, "arquivo": meta.get("arquivo"), "pagina": meta["pagina"]}
    out["estados"] = {}
    for uf, t in titulos_uf.items():
        meta = info_uf.get(t)
        img = baixar(meta, ALTURA_LOGO)
        if img:
            out["estados"][uf] = {"img": img, "titulo": t, "arquivo": meta.get("arquivo"), "pagina": meta["pagina"]}
    resumos = wiki_resumos([u["titulo"] for u in unidades])
    out["unidades"] = [{**{k: u[k] for k in ("uf", "corp", "sigla", "nome")}, "desc": resumos.get(u["titulo"], "")}
                       for u in unidades if f"u:{u['uf']}:{u['sigla']}" in out["policias"] or resumos.get(u["titulo"])]
    log.info("logos: %d partidos, %d polícias, %d unidades, %d veículos", len(out["partidos"]), len(out["policias"]), len(out["unidades"]), len(out["veiculos"]))
    return out


def fotos_congresso(db) -> dict:
    from sqlalchemy import select

    from app.models import Parlamentar
    out = {}
    for url, in db.execute(select(Parlamentar.foto_url).where(Parlamentar.foto_url.is_not(None),
                                                         Parlamentar.em_exercicio.is_(True))):
        try:
            r = cli.get(foto_maior(url))
            if r.status_code != 200 and foto_maior(url) != url:
                r = cli.get(url)
            img = miniatura(r.content, ALTURA_FOTO) if r.status_code == 200 else None
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
                            img = miniatura(z.read(nome), ALTURA_FOTO)
                            if img:
                                out[f"tse:{m.group(1)}"] = img
                os.remove(caminho)
            except Exception as e:
                log.warning("fotos TSE %s %s: %s", ano, uf, e)
    log.info("fotos do TSE: %d", len(out))
    return out


# ---- empresas dos rankings de dívida: logo e resumo da Wikipédia, só quando o verbete é da mesma empresa ----
_SUFIXOS = re.compile(r"\b(S\.?\s?/?A\.?|LTDA\.?|EIRELI|ME|EPP|CIA\.?|COMPANHIA|EM RECUPERACAO JUDICIAL|EM LIQUIDACAO"
                      r"(\s+EXTRAJUDICIAL)?|MASSA FALIDA( DE| DA| DO)?|HOLDING|PARTICIPACOES)\b", re.I)


def _palavras(t: str) -> set:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 1 and w not in {"de", "da", "do", "das", "dos", "e", "sa"}}


def empresa_wikipedia(nome: str) -> dict | None:
    """Verbete de empresa ({{Info/Empresa}}) cujo título (sem o parêntese) tem só palavras do nome da empresa."""
    limpo = re.sub(r"\s+", " ", _SUFIXOS.sub(" ", unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode())).strip()
    if len(limpo) < 3:
        return None
    try:
        d = cli.get(WIKI, params={"action": "query", "format": "json", "list": "search", "srlimit": 5,
                                  "srsearch": f"{limpo} empresa"}).json()
    except Exception:
        return None
    alvo = _palavras(nome)
    for r in d.get("query", {}).get("search", []):
        t = r["title"]
        tp = _palavras(re.sub(r"\s*\(.*\)$", "", t))
        if not tp or not tp <= alvo:
            continue
        try:
            txt = cli.get(WIKI, params={"action": "parse", "page": t, "prop": "wikitext", "section": 0,
                                        "format": "json", "formatversion": 2}).json().get("parse", {}).get("wikitext", "")
        except Exception:
            continue
        if re.search(r"\{\{\s*Info/(Empresa|Companhia)", txt, re.I):
            return {"titulo": t}
    return None


def logos_empresas(db) -> dict:
    """{cnpj_basico: {img, resumo, pagina}} das empresas dos rankings de dívida (receita-empresas-porte)."""
    from app.models import Registro
    r = db.query(Registro).filter_by(fonte="receita", tipo="empresas_porte").order_by(Registro.chave.desc()).first()
    if not r:
        return {}
    vistos, alvo = set(), []
    for e in (r.dados or {}).get("maiores_devedoras", [])[:150] + (r.dados or {}).get("maiores_empresas", [])[:150]:
        if e["cnpj_basico"] not in vistos and e.get("nome"):
            vistos.add(e["cnpj_basico"])
            alvo.append(e)
    # os fornecedores que mais receberam em contratos públicos (aba Empresas e Contratos › Contratos públicos)
    try:
        from sqlalchemy import func
        from app.models import Contrato
        top = (db.query(Contrato.cnpj_fornecedor, func.max(Contrato.fornecedor), func.sum(Contrato.valor).label("t"))
               .filter(Contrato.cnpj_fornecedor.isnot(None)).group_by(Contrato.cnpj_fornecedor)
               .order_by(func.sum(Contrato.valor).desc()).limit(200).all())
        for cnpj, nome, _ in top:
            b8 = "".join(ch for ch in str(cnpj) if ch.isdigit())
            if len(b8) == 14 and b8[:8] not in vistos and nome:
                vistos.add(b8[:8])
                alvo.append({"cnpj_basico": b8[:8], "nome": nome})
    except Exception as e:  # noqa: BLE001 - sem contratos coletados, ficam só as empresas dos rankings
        log.warning("fornecedores de contratos fora dos logos: %s", e)
    achados = {}
    for e in alvo:
        w = empresa_wikipedia(e["nome"])
        if w:
            achados[e["cnpj_basico"]] = w["titulo"]
    info = wiki_imagens(sorted(set(achados.values())))
    resumos = wiki_resumos(sorted(set(achados.values())))
    out = {}
    for cnpj, t in achados.items():
        meta = info.get(t) or {}
        img = None
        if meta.get("thumb"):
            try:
                rr = cli.get(meta["thumb"])
                img = miniatura(rr.content, ALTURA_LOGO, "PNG") if rr.status_code == 200 else None
            except Exception:
                img = None
        out[cnpj] = {"img": img, "resumo": resumos.get(t) or "", "pagina": meta.get("pagina") or
                     "https://pt.wikipedia.org/wiki/" + t.replace(" ", "_"), "titulo": t}
    log.info("empresas com verbete na Wikipédia: %d de %d", len(out), len(alvo))
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
                                      "piprop": "thumbnail", "pithumbsize": 800, "exintro": 1, "explaintext": 1,
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
                img = miniatura(r.content, ALTURA_FOTO) if r.status_code == 200 else None
            except Exception:
                img = None
            if img:
                out["wiki:" + nome] = img
    log.info("retratos da Wikipédia: %d de %d", len(out), len(nomes))
    return out


def main(pasta: str):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.db import SessionLocal
    from scripts.logos_arquivo import gravar, ler
    os.makedirs(pasta, exist_ok=True)
    lg = logos()
    # a Wikimedia às vezes limita os pedidos (429): o que não veio desta vez fica como estava na cópia anterior
    try:
        antes = ler(os.path.join(pasta, "logos.json"))
        for k in ("partidos", "policias", "veiculos", "estados"):
            for chave, v in (antes.get(k) or {}).items():
                lg.setdefault(k, {}).setdefault(chave, v)
        tem = {(u["uf"], u["sigla"]) for u in lg.get("unidades", [])}
        lg.setdefault("unidades", []).extend(u for u in antes.get("unidades", []) if (u["uf"], u["sigla"]) not in tem)
    except (OSError, ValueError, KeyError):
        pass
    gravar(os.path.join(pasta, "logos.json"), lg)
    # logos de batalhões enviados à mão (site/midia/batalhoes/UF-SIGLA.png) valem mais que os da Wikipédia
    if os.path.isdir(os.path.join(pasta, "batalhoes")):
        from scripts.logos_batalhoes import main as batalhoes
        batalhoes(os.path.join(pasta, "batalhoes"), os.path.join(pasta, "logos.json"))
        lg = ler(os.path.join(pasta, "logos.json"))
    with SessionLocal() as db:
        lg["empresas"] = logos_empresas(db) or lg.get("empresas") or {}
    gravar(os.path.join(pasta, "logos.json"), lg)
    with SessionLocal() as db:
        fotos = {**fotos_congresso(db), **fotos_tse(db), **fotos_wikipedia(nomes_indicados())}
    from scripts.fotos_escandalos import fotos_escandalos
    fotos.update(fotos_escandalos())
    gravar_fotos(pasta, fotos)
    try:  # perfis dos indicados (ministros, tribunais, Banco Central): resumo da Wikipédia e data de nascimento
        from scripts.perfis_indicados import main as perfis
        perfis(pasta)
    except Exception as e:  # noqa: BLE001 - não derruba as fotos
        log.warning("perfis de indicados não atualizados: %s", e)
    with open(os.path.join(pasta, "indice.json"), "w", encoding="utf-8") as f:
        json.dump({"gerado_em": date.today().isoformat(), "blocos": BLOCOS, "fotos": len(fotos),
                   "partidos": len(lg["partidos"]), "policias": len(lg["policias"]),
                   "fontes": {"fotos": "Câmara dos Deputados, Senado Federal, TSE (DivulgaCand) e, para ministros e "
                                       "tribunais, retratos da Wikipédia/Wikimedia Commons",
                              "logos": "Wikipédia / Wikimedia Commons (arquivo indicado em cada logo)"}}, f, ensure_ascii=False)


def gravar_fotos(pasta: str, fotos: dict) -> None:
    """Fotos em BLOCOS arquivos (fotos_<N>.json, pelo hash da chave), em WebP quando fica menor; apaga blocos que sobraram."""
    from scripts.logos_arquivo import webp
    blocos = [{} for _ in range(BLOCOS)]
    for k, v in fotos.items():
        blocos[fnv1a(k) % BLOCOS][k] = webp(v, 80)
    for i, b in enumerate(blocos):
        with open(os.path.join(pasta, f"fotos_{i}.json"), "w", encoding="utf-8") as f:
            json.dump(b, f, separators=(",", ":"))
    for nome in os.listdir(pasta):
        m = re.fullmatch(r"fotos_(\d+)\.json", nome)
        if m and int(m.group(1)) >= BLOCOS:
            os.remove(os.path.join(pasta, nome))


def reblocar(pasta: str) -> None:
    """Refaz os blocos de uma cópia pronta (sem banco): python -m scripts.midia_site --reblocar site/midia"""
    with open(os.path.join(pasta, "indice.json"), encoding="utf-8") as f:
        idx = json.load(f)
    fotos = {}
    for i in range(idx.get("blocos", 16)):
        with open(os.path.join(pasta, f"fotos_{i}.json"), encoding="utf-8") as f:
            fotos.update(json.load(f))
    gravar_fotos(pasta, fotos)
    idx.update(blocos=BLOCOS, fotos=len(fotos))
    with open(os.path.join(pasta, "indice.json"), "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    print(f"{len(fotos)} fotos em {BLOCOS} blocos")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--reblocar"]:
        reblocar(sys.argv[2] if len(sys.argv) > 2 else "site/midia")
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "site/midia")
