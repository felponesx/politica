"""Concursos, cursos gratuitos e eventos pagos com dinheiro público (menus "Concursos e cursos" e "Eventos").

Fontes (todas oficiais ou do próprio ofertante; nada é estimado):
- Concursos federais: busca do Diário Oficial da União (in.gov.br, seção 3). Só editais de ABERTURA (retificação, resultado,
  homologação, convocação e prorrogação ficam fora). Vagas, salário, inscrições, cargos e banca só quando estão escritos no texto.
- Concursos municipais: Querido Diário (diários oficiais das prefeituras). Fora do ar → aviso, nada inventado.
- Cursos: Escola Virtual.Gov (Enap, governo federal, todos gratuitos) e loja do Sebrae (só os de preço zero).
- Eventos: PNCP, contratações por inexigibilidade cujo objeto é show/apresentação artística (contratação de artista: Lei 14.133,
  art. 74, II). Valor = homologado, senão o estimado (marcado). Artista, evento e data só quando estão no texto do objeto.
- Patrocínio: Lei Rouanet (SALIC), projetos de música/festivais/festas com valor captado e quem patrocinou (incentivadores).
  Patrocínio privado direto de festa da prefeitura não existe em base aberta: a tela diz isso.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
import unicodedata
from datetime import date, datetime, timedelta

import httpx

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.oportunidades")
UA = {"User-Agent": "Mozilla/5.0 (compatible; BRASILmais/1.0; dados publicos)"}


def _cli(timeout=60) -> httpx.Client:
    return httpx.Client(headers=UA, timeout=timeout, follow_redirects=True)


def _get(cli, url, tentativas=4, **kw):
    for t in range(tentativas):
        try:
            r = cli.get(url, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and t < tentativas - 1:
                time.sleep(2 * (t + 1))
                continue
            return r
        except httpx.HTTPError:
            if t == tentativas - 1:
                raise
            time.sleep(2 * (t + 1))


def _sa(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def _limpa(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _num(t: str) -> float | None:
    try:
        return float(t.replace(".", "").replace(",", "."))
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------------------------------- concursos
DOU_BUSCA = "https://www.in.gov.br/consulta/-/buscar/dou"
DOU_ARTIGO = "https://www.in.gov.br/web/dou/-/{}"
QD_API = "https://api.queridodiario.org.br/gazettes"

_FORA = re.compile(r"retifica|homologa|resultado|convoca|prorroga|nomea|nomeia|sem efeito|cancela|suspen|anula|revoga|"
                   r"reabertura de prazo|gabarito|classifica[cç][aã]o final|aprovad[oa]s|recurso|errata|adiamento|reti-ratifica", re.I)
_ALUNO = re.compile(r"ingresso (no|em|nos) curso|mestrado|doutorado|p[oó]s-gradua|resid[eê]ncia (m[eé]dica|multiprofissional|em)|\baluno|discente|"
                    r"estudante|monitoria|transfer[eê]ncia (externa|interna)|vestibular|especializa[cç][aã]o|\bppg|programa de p[oó]s|"
                    r"\bbolsas?\b|licita[cç][aã]o|preg[aã]o|chamamento p[uú]blico|credenciamento", re.I)
_EMPREGO = re.compile(r"\bcargos?\b|provimento|empregos? p[uú]blicos?|contrata[cç][aã]o tempor[aá]ria|professor substituto|professor visitante|"
                      r"servidor|\bvagas?\b.{0,80}(cargo|fun[cç][aã]o|emprego)|remunera[cç][aã]o|vencimento b[aá]sico", re.I)
_ABRE = re.compile(r"abertura|torna[mr]?\s+p[uú]blic[ao]s?\s+(a\s+)?realiza[cç][aã]o|abertas? as inscri|estar[aã]o abertas|"
                   r"realiza[cç][aã]o de (concurso|processo seletivo)|inscri[cç][oõ]es (ser[aã]o|estar[aã]o) (realizadas|abertas)", re.I)
BANCAS = ["Cebraspe", "Cespe", "FGV", "Fundação Getulio Vargas", "Cesgranrio", "FCC", "Fundação Carlos Chagas", "Vunesp", "IBFC",
          "Quadrix", "Idecan", "Instituto AOCP", "AOCP", "Consulplan", "Fundatec", "Instituto Consulplan", "IBADE", "Selecon",
          "FEPESE", "Comperve", "Fundep", "Instituto Access", "Avança SP", "Objetiva", "Legalle", "IADES", "Cetro", "UFPR", "Copeve"]
AREAS = [  # (área, palavras) — a primeira que casar vence
    ("Segurança", r"delegad|policia|policial|agente penitenci|guarda municipal|perito criminal|escriv[aã]o de pol|bombeiro|investigador"),
    ("Tecnologia (TI)", r"tecnologia da informa|\bti\b|analista de sistemas|desenvolvedor|programador|ciencia de dados|ciência de dados|infraestrutura de ti|seguran[cç]a da informa"),
    ("Legislativo", r"c[aâ]mara dos deputados|senado federal|c[aâ]mara municipal|assembleia legislativa|c[aâ]mara legislativa"),
    ("Judiciário e Ministério Público", r"tribunal|justi[cç]a|minist[eé]rio p[uú]blico|defensoria|procuradoria|juiz|promotor"),
    ("Saúde", r"m[eé]dic|enferm|sa[uú]de|hospital|farmac|odontol|fisioterap|psic[oó]log|nutricion"),
    ("Educação", r"professor|docente|magist[eé]rio|ensino|educa[cç][aã]o|pedagog|t[eé]cnico-administrativo em educa"),
    ("Fiscal e controle", r"auditor|fiscal|receita|tribunal de contas|controlador|contador"),
    ("Militar", r"ex[eé]rcito brasileiro|comando da marinha|comando da aeron[aá]utica|for[cç]as armadas|sargento|soldado|cadete|corpo de fuzileiros"),
    ("Conselhos profissionais", r"conselho (regional|federal) de"),
]


def _area(texto: str) -> str:
    t = _sa(texto)
    for nome, pad in AREAS:
        if re.search(_sa(pad), t):
            return nome
    return "Outras áreas"


def eh_abertura(titulo: str, inicio: str) -> bool:
    """Edital de abertura: o começo do texto fala em abrir/realizar o concurso e não é retificação, resultado etc."""
    cab = f"{titulo} {inicio[:400]}"
    return bool(_ABRE.search(cab)) and not _FORA.search(cab) and not _ALUNO.search(cab) and bool(_EMPREGO.search(inicio[:4000]))


def detalhes_edital(texto: str) -> dict:
    """Só o que está escrito: vagas, maior remuneração citada, período de inscrição, cargos, banca, escolaridade."""
    out: dict = {}
    t = texto
    m = re.search(r"total de\s+(\d[\d.]*)\s*(?:\([^)]{0,40}\))?\s*vagas", t, re.I) or re.search(r"(?<![\d/.,])(\d{1,5})\s*(?:\([a-zçãéêíóôú\s-]{2,40}\))?\s*vagas?\b", t, re.I)
    if m:
        v = _num(m.group(1))
        if v and 0 < v < 20000 and not (1990 <= v <= 2100 and "(" not in m.group(0)):
            out["vagas"] = int(v)
    sal = []
    for m in re.finditer(r"(remunera[cç][aã]o|vencimento|sal[aá]rio|subs[ií]dio|retribui[cç][aã]o)[^R]{0,160}R\$\s*([\d.]+,\d{2})", t, re.I):
        v = _num(m.group(2))
        if v and 500 < v < 100000:
            sal.append(v)
    if sal:
        out["salario_max"] = max(sal)
    m = re.search(r"inscri[cç][oõ]es[^.]{0,200}?(\d{1,2}/\d{1,2}/\d{4})[^.]{0,40}?(?:a|at[eé]|e)\s+(\d{1,2}/\d{1,2}/\d{4})", t, re.I)
    if m:
        out["inscricoes_inicio"], out["inscricoes_fim"] = _iso(m.group(1)), _iso(m.group(2))
    cargos = []
    for m in re.finditer(r"(?:cargos? (?:efetivos? )?de|emprego p[uú]blico de|fun[cç][aã]o de|cargo:)\s+([^,.;:()]{3,70})", t, re.I):
        c = re.split(r"\s+(?:do quadro|da carreira|do plano|para (?:o|a|os|as)|n[oa]s?\s|com\s|integrante|pertencente|regido|nos termos|conforme|de n[ií]vel)\b", m.group(1).strip(), maxsplit=1)[0].strip(" -/")
        if len(c) < 3 or re.match(r"(provimento|carreira|n[ií]vel|classe|natureza|seus?\b|suas?\b|o\b|a\b|os\b|as\b|quadro)", c, re.I):
            continue
        c = c[:1].upper() + c[1:]
        if c and c.lower() not in (x.lower() for x in cargos) and len(cargos) < 6:
            cargos.append(c)
    if cargos:
        out["cargos"] = cargos
    for b in BANCAS:
        if re.search(r"\b" + re.escape(b) + r"\b", t, re.I):
            out["banca"] = b
            break
    niv = [n for n, p in (("superior", r"n[ií]vel superior"), ("médio", r"n[ií]vel m[eé]dio"), ("fundamental", r"n[ií]vel fundamental")) if re.search(p, t, re.I)]
    if niv:
        out["escolaridade"] = niv
    return out


def _iso(d: str) -> str | None:
    try:
        return datetime.strptime(d, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _dou_busca(cli, q: str, de: date, ate: date, pagina: int = 1) -> list[dict]:
    p = {"q": q, "s": "do3", "exactDate": "personalizado", "publishFrom": de.strftime("%d-%m-%Y"), "publishTo": ate.strftime("%d-%m-%Y"),
         "sortType": 0, "delta": 75}
    if pagina > 1:
        p.update(currentPage=pagina, newPage=pagina)
    r = _get(cli, DOU_BUSCA, params=p)
    m = re.search(r'BuscaDouPortlet_params" type="application/json">(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("DOU: a página de busca mudou (sem o bloco de resultados)")
    return json.loads(m.group(1)).get("jsonArray") or []


def _dou_texto(cli, url_title: str) -> str:
    r = _get(cli, DOU_ARTIGO.format(url_title))
    m = re.search(r'<div class="texto-dou">(.*?)</div>\s*</div>', r.text, re.S) or re.search(r'<div class="texto-dou">(.*)', r.text, re.S)
    return _limpa(m.group(1))[:20000] if m else ""


def _orgao(hier: str) -> tuple[str, str]:
    partes = [p.strip() for p in (hier or "").split("/") if p.strip()]
    return (partes[1] if len(partes) > 1 else (partes[0] if partes else "")), (partes[0] if partes else "")


def coletar_concursos(dias: int = 30, municipais: bool = True):
    """Editais de abertura de concurso público e processo seletivo dos últimos `dias` dias."""
    dias = int(dias)
    with registrar_coleta("oportunidades", "concursos", dias=dias) as (db, n), _cli() as cli:
        hoje = date.today()
        vistos = set()
        for q in ('"concurso público"', '"processo seletivo"'):
            ini = hoje - timedelta(days=dias)
            while ini <= hoje:  # janelas de 7 dias (a busca devolve até 75 por página)
                fim = min(ini + timedelta(days=6), hoje)
                for pagina in range(1, 15):
                    try:
                        itens = _dou_busca(cli, q, ini, fim, pagina)
                    except Exception as e:  # noqa: BLE001
                        n.avisos.append(f"DOU {ini}: {type(e).__name__}: {str(e)[:120]}")
                        break
                    for x in itens:
                        pk = str(x.get("classPK") or x.get("urlTitle"))
                        if pk in vistos:
                            continue
                        vistos.add(pk)
                        tit, resumo = _limpa(x.get("title")), _limpa(x.get("content"))
                        if _FORA.search(f"{tit} {resumo[:300]}"):
                            continue
                        try:
                            texto = _dou_texto(cli, x["urlTitle"])
                        except Exception as e:  # noqa: BLE001
                            n.avisos.append(f"DOU artigo {pk}: {type(e).__name__}")
                            continue
                        if not eh_abertura(tit, texto or resumo):
                            continue
                        orgao, ministerio = _orgao(x.get("hierarchyStr"))
                        tipo = "Processo seletivo" if re.search(r"processo seletivo", (texto or resumo)[:600], re.I) else "Concurso público"
                        d = {"titulo": tit, "orgao": orgao, "vinculo": ministerio, "esfera": "federal", "uf": None, "municipio": None,
                             "tipo": tipo, "area": _area(f"{orgao} {texto[:3000] or resumo}"), "publicado": _iso(x.get("pubDate") or ""),
                             "resumo": (texto or resumo)[:400], "url": DOU_ARTIGO.format(x["urlTitle"]), "fonte": "Diário Oficial da União"}
                        d.update(detalhes_edital(texto))
                        upsert(db, Registro, {"fonte": "dou", "tipo": "concurso", "chave": pk},
                               {"titulo": tit[:300], "ano": int(d["publicado"][:4]) if d.get("publicado") else None, "valor": d.get("salario_max"), "dados": d})
                        n += 1
                    db.commit()
                    if len(itens) < 75:
                        break
                ini = fim + timedelta(days=1)
        if municipais:
            try:
                n += _concursos_municipais(db, cli, dias)
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"Querido Diário (concursos das prefeituras) fora do ar: {type(e).__name__}: {str(e)[:120]}")
        db.commit()
    return n.itens


def _concursos_municipais(db, cli, dias: int) -> int:
    feitos = 0
    desde = (date.today() - timedelta(days=dias)).isoformat()
    for offset in range(0, 2000, 100):
        r = _get(cli, QD_API, params={"querystring": '"edital de abertura" "concurso público"', "published_since": desde, "size": 100,
                                      "offset": offset, "excerpt_size": 600, "number_of_excerpts": 2, "sort_by": "descending_date"})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        gs = r.json().get("gazettes") or []
        for g in gs:
            trecho = " ".join(_limpa(e) for e in g.get("excerpts") or [])
            if not trecho or _FORA.search(trecho[:300]) and not _ABRE.search(trecho[:300]):
                continue
            chave = f"{g.get('territory_id')}-{g.get('date')}-{abs(hash(trecho[:200])) % 10**9}"
            d = {"titulo": f"Concurso público — Prefeitura de {g.get('territory_name')}", "orgao": f"Prefeitura de {g.get('territory_name')}",
                 "esfera": "municipal", "uf": g.get("state_code"), "municipio": g.get("territory_name"), "codigo_ibge": g.get("territory_id"),
                 "tipo": "Concurso público", "area": _area(trecho), "publicado": g.get("date"), "resumo": trecho[:400], "url": g.get("url"),
                 "fonte": "Diário oficial do município (Querido Diário)"}
            d.update(detalhes_edital(trecho))
            upsert(db, Registro, {"fonte": "querido_diario", "tipo": "concurso", "chave": chave},
                   {"titulo": d["titulo"][:300], "uf": d["uf"], "ano": int(str(d["publicado"])[:4]) if d.get("publicado") else None,
                    "valor": d.get("salario_max"), "dados": d})
            feitos += 1
        if len(gs) < 100:
            break
    return feitos


# ---------------------------------------------------------------------------------------------------- cursos
EVG_API = "https://api-evg.enap.gov.br/v1/cursos"
EVG_CURSO = "https://www.escolavirtual.gov.br/cursos/{}"
SEBRAE_GQL = "https://loja.sebrae.com.br/graphql"


def coletar_cursos():
    """Cursos gratuitos: Escola Virtual.Gov (todos gratuitos, com certificado) e Sebrae (só os de preço zero)."""
    with registrar_coleta("oportunidades", "cursos") as (db, n), _cli() as cli:
        evg = 0
        try:
            pagina, ultima = 1, 1
            while pagina <= ultima and pagina <= 60:
                d = _get(cli, EVG_API, params={"page": pagina, "limit": 100}).json()
                ultima = int((d.get("meta") or {}).get("last_page") or 1)
                for c in d.get("data") or []:
                    if c.get("tp_situacao_curso") not in (None, "A"):
                        continue
                    x = {"nome": _limpa(c.get("tx_nome_curso")), "ofertante": "Escola Virtual.Gov (Enap)", "quem_faz": _limpa(c.get("tx_conteudista")),
                         "tema": c.get("tx_nome_tematica_curso"), "carga_horaria": c.get("qt_carga_horaria"), "modalidade": "Online",
                         "inscricoes_abertas": bool(c.get("inscricoes_abertas")), "certificado": True, "gratuito": True,
                         "resumo": _limpa(c.get("tx_apresentacao"))[:350], "url": EVG_CURSO.format(c.get("tx_slug")), "lancado": (c.get("dt_lancamento") or "")[:10],
                         "imagem": c.get("tx_url_imagem_curso"), "uf": None, "abrangencia": "Brasil (online)"}
                    upsert(db, Registro, {"fonte": "evg", "tipo": "curso", "chave": str(c.get("id_curso"))},
                           {"titulo": x["nome"][:300], "valor": float(x["carga_horaria"] or 0), "dados": x})
                    evg += 1
                pagina += 1
            db.commit()
        except Exception as e:  # noqa: BLE001
            n.avisos.append(f"Escola Virtual.Gov: {type(e).__name__}: {str(e)[:120]}")
        n += evg
        seb = 0
        try:
            q = ("query($p:Int){ products(search:\"\", pageSize:100, currentPage:$p){ total_count page_info{ total_pages } "
                 "items{ sku name url_key categories{ name } price_range{ minimum_price{ final_price{ value } } } } } }")
            pagina, total = 1, 1
            while pagina <= total and pagina <= 40:
                r = cli.post(SEBRAE_GQL, json={"query": q, "variables": {"p": pagina}}, headers={"Content-Type": "application/json"})
                pr = ((r.json().get("data") or {}).get("products") or {})
                total = int((pr.get("page_info") or {}).get("total_pages") or 1)
                for it in pr.get("items") or []:
                    preco = (((it.get("price_range") or {}).get("minimum_price") or {}).get("final_price") or {}).get("value")
                    cats = [c.get("name") for c in it.get("categories") or [] if c.get("name")]
                    if preco != 0 or not any(re.search(r"curso|oficina|trilha|palestra", _sa(c)) for c in cats + [it.get("name") or ""]):
                        continue
                    tema = next((c for c in cats if not re.search(r"curso|todos|online|presencial|default", _sa(c))), None)
                    x = {"nome": _limpa(it.get("name")), "ofertante": "Sebrae", "quem_faz": "Sebrae", "tema": tema,
                         "modalidade": "Online" if any("online" in _sa(c) for c in cats) else None, "gratuito": True, "certificado": None,
                         "inscricoes_abertas": True, "url": f"https://loja.sebrae.com.br/{it.get('url_key')}", "uf": None, "abrangencia": "Brasil"}
                    upsert(db, Registro, {"fonte": "sebrae", "tipo": "curso", "chave": str(it.get("sku") or it.get("url_key"))},
                           {"titulo": x["nome"][:300], "dados": x})
                    seb += 1
                pagina += 1
            db.commit()
        except Exception as e:  # noqa: BLE001
            n.avisos.append(f"Sebrae: {type(e).__name__}: {str(e)[:120]}")
        n += seb
        if not evg and not seb:
            raise RuntimeError("nenhuma fonte de cursos respondeu: " + "; ".join(n.avisos))
    return n.itens


# ---------------------------------------------------------------------------------------------------- eventos
PNCP_PUB = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
PNCP_LINK = "https://pncp.gov.br/app/editais/{}/{}/{}"
SHOW = re.compile(r"\bshows?\b|apresenta[cç][aã]o (art[ií]stica|musical|cultural)|apresenta[cç][oõ]es art[ií]sticas|\bcantor|\bcantora\b|"
                  r"\bbanda\b|dupla sertaneja|atra[cç][aã]o (art[ií]stica|musical)|artista|\bdj\b|orquestra|grupo musical", re.I)
NAO_SHOW = re.compile(r"radar|banda larga|banda[- ](?:s|c|x|ku|l|ka)\b|internet|frequ[eê]ncia|telecomunica|sobressalente|equipamento|"
                      r"aquisi[cç][aã]o de|fornecimento de (?!show|apresenta)|loca[cç][aã]o de (?:palco|som|tenda|banheiro|gerador|estrutura)|"
                      r"software|sistema de gest|licen[cç]a de uso|ve[ií]culo|medicament|exame|consulta m[eé]dic|curso de|capacita[cç][aã]o|"
                      r"treinamento|inscri[cç][aã]o (de|em|no|para)|assinatura|publica[cç][aã]o|palestra", re.I)


_PARA = (r"(?=\s*(?:,|;|\.|\(|:|\s[-–]\s|$)|\s+(?:para|no|na|nos|nas|em|a ser|que|representad[oa]|inscrit[oa]|com dura[cç][aã]o|"
         r"durante|objetivando|visando|destinad[oa]|atrav[eé]s|por meio|neste|nesta|cnpj|pessoa jur[ií]dica|dia|dias)\b)")
_ART = re.compile(r"\b(cantora?|banda|grupo(?: musical)?|dupla(?: sertaneja)?|atra[cç][aã]o(?: art[ií]stica| musical)?|artista|m[uú]sico|dj|orquestra|cantor e compositor)"
                  r"\s+(?:musical\s+|art[ií]stic[oa]\s+)?[\"“”']?([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][^\"“”,;()]{1,60}?)[\"“”']?" + _PARA, re.I)
_ART_ASPAS = re.compile(r"(?:contrata[cç][aã]o d[oae]s?|apresenta[cç][aã]o (?:art[ií]stica|musical|cultural) d[oae]s?|show d[oae]s?|show com (?:o|a)?)\s*[\"“]([^\"”]{2,60})[\"”]", re.I)
_GENERICO = re.compile(r"^(art[ií]stic[oa]s?|musica(l|is)|cultura(l|is)|local|locais|regional|infantil|de|da|do|com|para|na|no|show|evento|empresa|"
                       r"profissionais?|pertinente|ramo|especializad[oa]|que|e|ou)$", re.I)


def _nome_ok(a: str) -> bool:
    a = a.strip(" -.,")
    if re.fullmatch(r"(SM|SEC|SEM|SME|FUND|PM|DPTO|DEP)[A-Z]{0,8}", a):  # sigla de secretaria/órgão, não artista
        return False
    return len(a) >= 3 and not _GENERICO.match(a.split()[0]) and not re.search(r"\bempresa\b|\bcnpj\b|\blicita|\bmunic[ií]pio\b|\bsecretaria\b", a, re.I)


def ler_show(objeto: str) -> dict:
    """Artista, evento e data quando estão escritos no objeto da contratação (nada é deduzido de outra fonte)."""
    o = re.sub(r"\s+", " ", objeto or "")
    out: dict = {}
    m = _ART_ASPAS.search(o)
    if m and _nome_ok(m.group(1)):
        out["artista"] = m.group(1).strip()
    if "artista" not in out:
        m = re.search(r"(?:apresenta[cç][aã]o (?:art[ií]stica|musical|cultural)(?: musical)?|show(?: musical| art[ií]stico)?)\s+(?:de|-|–)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\"“”,;()]{2,60}?)" + _PARA, o, re.I)
        if m and _nome_ok(m.group(1)) and m.group(1)[:1].isupper():
            out["artista"] = m.group(1).strip(" -.,")
    if "artista" not in out:
        for m in _ART.finditer(o):
            kw, nome = m.group(1), m.group(2).strip(" -.,")
            if not _nome_ok(nome):
                continue
            out["artista"] = (f"{kw.split()[0].capitalize()} {nome}" if re.match(r"(banda|grupo|dupla|orquestra)", kw, re.I)
                              and not re.match(r"(banda|grupo|dupla|orquestra)\b", nome, re.I) else nome)
            break
    ev = None
    for m in re.finditer(r"[\"“]([^\"”]{4,80})[\"”]", o):
        a = _sa(out.get("artista") or "#")
        qq = _sa(m.group(1)).strip()
        if qq != a and a not in qq and qq not in a:
            ev = m.group(1)
            break
    if not ev:
        m = re.search(r"(?:no evento|na festa|durante (?:a|o)|em comemora[cç][aã]o (?:a|ao|aos|à|às)|evento denominado|integrando a programa[cç][aã]o d[aoe]s?|"
                      r"programa[cç][aã]o d[aoe]s?|festividades? d[aoe]s?|para (?:o|a) (?=festival|festa|feira|carnaval|micareta|natal|r[eé]veillon|s[aã]o jo[aã]o|anivers[aá]rio|semana|encontro))"
                      r"\s*([^,;.]{4,80})", o, re.I)
        ev = m.group(1) if m else None
    if ev:
        ev = re.split(r"\s+(?:no dia|nos dias|no palco|a ser realizad|que ser[aá]|com dura|realizad[oa]|conforme|a realizar|no per[ií]odo|em [A-ZÁÉÍÓÚ][a-zá-ú]+-|-\s)", ev, maxsplit=1, flags=re.I)[0].strip(" -")
        if len(ev) >= 4:
            out["evento"] = ev
    m = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", o)
    if m:
        out["data_evento"] = _iso(m.group(1))
    else:
        m = re.search(r"\bdias? (\d{1,2}) de ([a-zç]+) de (\d{4})", o, re.I)
        meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
        if m and _sa(m.group(2)) in meses:
            try:
                out["data_evento"] = date(int(m.group(3)), meses.index(_sa(m.group(2))) + 1, int(m.group(1))).isoformat()
            except ValueError:
                pass
    if not out.get("data_evento"):
        out.pop("data_evento", None)
    return out


def coletar_eventos(dias: int = 60):
    """Shows e apresentações artísticas contratados por prefeituras, estados e União (PNCP, inexigibilidade)."""
    dias = int(dias)
    with registrar_coleta("oportunidades", "eventos", dias=dias) as (db, n), _cli(90) as cli:
        hoje = date.today()
        dia = hoje - timedelta(days=dias)
        while dia <= hoje:
            for pagina in range(1, 400):
                p = {"dataInicial": dia.strftime("%Y%m%d"), "dataFinal": dia.strftime("%Y%m%d"), "codigoModalidadeContratacao": 9,
                     "pagina": pagina, "tamanhoPagina": 50}
                try:
                    r = _get(cli, PNCP_PUB, params=p)
                    if r.status_code == 204:
                        break
                    d = r.json()
                except Exception as e:  # noqa: BLE001
                    n.avisos.append(f"PNCP {dia} p{pagina}: {type(e).__name__}")
                    break
                for x in d.get("data") or []:
                    obj = x.get("objetoCompra") or ""
                    if not SHOW.search(obj) or NAO_SHOW.search(obj):
                        continue
                    org, uni = x.get("orgaoEntidade") or {}, x.get("unidadeOrgao") or {}
                    hom, est = x.get("valorTotalHomologado"), x.get("valorTotalEstimado")
                    esf = {"M": "municipal", "E": "estadual", "F": "federal", "D": "distrital"}.get(org.get("esferaId"), org.get("esferaId"))
                    e = {"objeto": obj[:600], "orgao": _limpa(org.get("razaoSocial")), "unidade": _limpa(uni.get("nomeUnidade")), "esfera": esf,
                         "uf": uni.get("ufSigla"), "municipio": uni.get("municipioNome"), "codigo_ibge": uni.get("codigoIbge"),
                         "valor": hom if hom else est, "valor_tipo": "homologado" if hom else ("estimado" if est else None),
                         "publicado": (x.get("dataPublicacaoPncp") or "")[:10], "processo": x.get("processo"),
                         "url": PNCP_LINK.format(org.get("cnpj"), x.get("anoCompra"), x.get("sequencialCompra")), "fonte": "PNCP"}
                    e.update(ler_show(obj))
                    upsert(db, Registro, {"fonte": "pncp", "tipo": "evento_show", "chave": x.get("numeroControlePNCP") or e["url"]},
                           {"titulo": (e.get("artista") or obj)[:300], "uf": e["uf"], "ano": int(e["publicado"][:4]) if e["publicado"] else None,
                            "valor": e["valor"], "dados": e})
                    n += 1
                db.commit()
                if pagina >= int(d.get("totalPaginas") or 1):
                    break
            dia += timedelta(days=1)
        if not n.itens and n.avisos:
            raise RuntimeError("; ".join(n.avisos[:5]))
    return n.itens


SALIC = "https://api.salic.cultura.gov.br/api/v1/projetos"
SALIC_LINK = "https://versalic.cultura.gov.br/#/projetos/{}"
_FESTA = re.compile(r"festival|festa|feira|show|apresenta|m[uú]sica|carnaval|reveillon|r[eé]veillon|s[aã]o jo[aã]o|junin|turn[eê]|concerto|circula[cç][aã]o", re.I)


def coletar_patrocinios(anos: str | None = None, detalhes: int = 500):
    """Lei Rouanet: projetos da área Música (shows, festivais, festas) com valor captado e quem patrocinou."""
    hoje = date.today()
    anos = [int(a) % 100 for a in str(anos).split(",")] if anos else [(hoje.year - 1) % 100, hoje.year % 100]
    with registrar_coleta("oportunidades", "patrocinios", anos=",".join(map(str, anos))) as (db, n), _cli(300) as cli:
        candidatos = []
        for ano in anos:
            for off in range(0, 40000, 100):
                # área 3 = Música (shows, festivais de música, festas): ler todas as áreas leva horas e o resto não é evento
                r = _get(cli, SALIC, params={"limit": 100, "offset": off, "format": "json", "ano_projeto": f"{ano:02d}", "area": 3})
                ps = ((r.json() or {}).get("_embedded") or {}).get("projetos") or []
                for p in ps:
                    cap = float(p.get("valor_captado") or 0)
                    if cap > 0 and _FESTA.search(" ".join(str(p.get(k) or "") for k in ("tipologia", "segmento", "nome", "area"))):
                        candidatos.append(p)
                if len(ps) < 100:
                    break
        candidatos.sort(key=lambda p: -float(p.get("valor_captado") or 0))
        for p in candidatos[:int(detalhes)]:
            try:
                d = _get(cli, f"{SALIC}/{p['PRONAC']}", params={"format": "json"}).json()
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"SALIC {p.get('PRONAC')}: {type(e).__name__}")
                continue
            emb = d.get("_embedded") or {}
            pat: dict = {}
            for c in emb.get("captacoes") or []:
                nome = _limpa(c.get("nome_doador"))
                if not nome:
                    continue
                # pessoa física não é identificada pelo nome aqui: só empresas (CNPJ de 14 dígitos)
                doc = re.sub(r"\D", "", str(c.get("cgccpf") or ""))
                chave = nome if len(doc) == 14 else "Pessoas físicas"
                s = pat.setdefault(chave, {"nome": chave, "cnpj": doc if len(doc) == 14 else None, "valor": 0.0})
                s["valor"] += float(c.get("valor") or 0)
            locais = [f"{l.get('municipio')}/{l.get('sigla_uf')}" for l in emb.get("local_realizacao") or [] if l.get("municipio")]
            x = {"pronac": p["PRONAC"], "nome": _limpa(p.get("nome")), "proponente": _limpa(p.get("proponente")), "uf": p.get("UF"),
                 "municipio": p.get("municipio"), "locais": locais[:20], "segmento": p.get("segmento"), "tipologia": p.get("tipologia"),
                 "aprovado": float(p.get("valor_aprovado") or 0), "captado": float(p.get("valor_captado") or 0),
                 "inicio": p.get("data_inicio"), "fim": p.get("data_termino"), "patrocinadores": sorted(pat.values(), key=lambda s: -s["valor"]),
                 "url": SALIC_LINK.format(p["PRONAC"]), "fonte": "SALIC (Lei Rouanet)"}
            upsert(db, Registro, {"fonte": "salic", "tipo": "patrocinio", "chave": str(p["PRONAC"])},
                   {"titulo": x["nome"][:300], "uf": x["uf"], "valor": x["captado"], "dados": x})
            n += 1
        db.commit()
    return n.itens
