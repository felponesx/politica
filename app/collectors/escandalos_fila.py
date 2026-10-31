"""Fila de revisão de escândalos e investigações: notícias de órgãos oficiais que citam investigação, denúncia, condenação etc.

NADA aqui é publicado como caso. Cada item é uma notícia OFICIAL com título, resumo (o que o órgão escreveu), data, órgão e URL; a etapa é só uma sugestão pelas palavras do título;
"pessoas envolvidas", "local" e "situação atual" ficam EM BRANCO até uma pessoa conferir a fonte e, se houver documentação suficiente, criar o caso curado (app/dados/escandalos).
Nenhum nome é extraído por programa e nenhuma suspeita vira fato. Fontes lidas (conferido em 31/10/2026 pelo ambiente de desenvolvimento): Polícia Federal e CGU (lista de notícias do gov.br),
STF (feed). MPF (404), STJ (403) e TCU (lista só por JavaScript) ficam registrados como não alcançáveis por este método, sem simular nada."""
import hashlib
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.ocorrencias import classificar
from app.utils import upsert

log = logging.getLogger("brasilplus.fila")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
FONTES = [
    {"id": "pf", "orgao": "Polícia Federal", "tipo": "html", "lista": "https://www.gov.br/pf/pt-br/assuntos/noticias", "padrao": r"https://www\.gov\.br/pf/pt-br/assuntos/noticias/20\d\d/[^\"'#?]+"},
    {"id": "cgu", "orgao": "Controladoria-Geral da União", "tipo": "html", "lista": "https://www.gov.br/cgu/pt-br/assuntos/noticias", "padrao": r"https://www\.gov\.br/cgu/pt-br/assuntos/noticias/20\d\d/[^\"'#?]+"},
    {"id": "stf", "orgao": "Supremo Tribunal Federal", "tipo": "rss", "lista": "https://noticias.stf.jus.br/feed/"},
    {"id": "mpf", "orgao": "Ministério Público Federal", "tipo": "html", "lista": "https://www.mpf.mp.br/sala-de-imprensa/noticias", "padrao": r"", "ativo": False, "motivo": "página devolve 404 ao ambiente de teste"},
    {"id": "stj", "orgao": "Superior Tribunal de Justiça", "tipo": "html", "lista": "https://www.stj.jus.br/sites/portalp/Paginas/Comunicacao/Noticias", "padrao": r"", "ativo": False, "motivo": "página devolve 403 ao ambiente de teste"},
    {"id": "tcu", "orgao": "Tribunal de Contas da União", "tipo": "html", "lista": "https://portal.tcu.gov.br/imprensa/noticias", "padrao": r"", "ativo": False, "motivo": "a lista de notícias só aparece com JavaScript (sem links no HTML)"},
]
RELEVANTE = re.compile(r"opera[cç][aã]o|investiga|inqu[eé]rito|den[uú]ncia|denunciad|condena|absolv|arquiv|fraude|desvi|corrup|lavagem|improbidade|cartel|propina|peculato|"
                       r"organiza[cç][aã]o criminosa|pris[aã]o|preso|mandado|busca e apreens|san[cç][aã]o|inid[oô]ne|leni[eê]ncia|irregularidade|tomada de contas|superfatur|licita[cç][aã]o", re.I)
SITUACAO = "Não verificada: é uma notícia do próprio órgão. Abra a fonte e confirme a fase do processo antes de criar um caso."
MAX_NOVOS = 25
MESES_ANTIGOS = 14   # ignora notícia mais velha que isto (em meses)


def limpar(t: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()


def links_da_lista(texto: str, padrao: str) -> list[str]:
    vistos, out = set(), []
    for u in re.findall(padrao, html.unescape(texto)):
        u = u.rstrip("/")
        if u not in vistos:
            vistos.add(u)
            out.append(u)
    return out


def ler_artigo(texto: str) -> dict:
    """Título (og:title), resumo (og:description) e data (dd/mm/aaaa depois de 'Publicado em') da página da notícia."""
    t = html.unescape(re.sub(r"<!--[\s\S]*?-->", "", texto))   # o modelo da página traz uma data de exemplo dentro de comentário HTML
    og = lambda k: (re.search(rf'<meta[^>]+property="og:{k}"[^>]+content="([^"]*)"', t) or re.search(rf'<meta[^>]+content="([^"]*)"[^>]+property="og:{k}"', t))  # noqa: E731
    titulo, resumo = og("title"), og("description")
    d = re.search(r'documentPublished[\s\S]{0,400}?class="value">\s*(\d{2})/(\d{2})/(\d{4})', t) or re.search(r"Publicado em[\s\S]{0,300}?(\d{2})/(\d{2})/(\d{4})", t)
    return {"titulo": limpar(titulo.group(1)) if titulo else "", "resumo": limpar(resumo.group(1)) if resumo else "", "data": f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None}


def itens_rss(texto: str) -> list[dict]:
    out = []
    for it in ET.fromstring(texto).iter("item"):
        data = it.findtext("pubDate") or ""
        try:
            iso = datetime.strptime(data[:25], "%a, %d %b %Y %H:%M:%S").date().isoformat()
        except ValueError:
            iso = None
        out.append({"titulo": limpar(it.findtext("title")), "resumo": limpar(it.findtext("description"))[:500], "url": (it.findtext("link") or "").strip(), "data": iso})
    return out


def montar(fonte: dict, item: dict, agora: str) -> dict:
    texto = f"{item['titulo']} {item['resumo']}"
    return {"titulo": item["titulo"], "resumo": item["resumo"][:600], "orgao": fonte["orgao"], "orgao_id": fonte["id"], "url": item["url"], "data": item["data"], "local": None,
            "pessoas_ou_instituicoes": [], "etapa_sugerida": classificar(item["titulo"]), "situacao_atual": SITUACAO, "ultima_verificacao": agora, "status_revisao": "pendente",
            "pendencias": ["pessoas envolvidas e local não preenchidos", "situação do processo não confirmada na fonte", "etapa sugerida só pelo título"],
            "mencionado_nos_termos": sorted({m.group(0).lower() for m in RELEVANTE.finditer(texto)})[:6]}


def coletar_escandalos_fila(limite: int = MAX_NOVOS):
    """Lê as fontes oficiais ativas e põe na fila as notícias novas que tratam de investigação/denúncia/condenação/etc.; registra o estado de cada fonte."""
    with registrar_coleta("escandalos", "fila") as (db, n):
        agora = datetime.now().isoformat(timespec="seconds")
        estado = []
        for f in FONTES:
            e = {"id": f["id"], "orgao": f["orgao"], "url": f["lista"], "ativa": f.get("ativo", True), "lidos": 0, "novos": 0, "na_fila": 0, "erro": f.get("motivo")}
            estado.append(e)
            if not e["ativa"]:
                continue
            try:
                r = http.get(f["lista"], headers=UA, timeout=60)
                if f["tipo"] == "rss":
                    itens = itens_rss(r.text)
                else:
                    itens = [{"url": u} for u in links_da_lista(r.text, f["padrao"])]
                e["lidos"] = len(itens)
                if not itens:
                    e["erro"] = "nenhum item na lista (a página mudou?)"
                    n.avisos.append(f"{f['id']}: {e['erro']}")
                    continue
                for it in itens:
                    chave = hashlib.sha1(it["url"].encode(), usedforsecurity=False).hexdigest()[:24]
                    if db.query(Registro).filter_by(fonte="escandalos", tipo="fila_item", chave=chave).first():
                        continue
                    if e["novos"] >= int(limite):
                        break
                    if "titulo" not in it:   # lista em HTML: abre a notícia para ler título, resumo e data
                        it = {**it, **ler_artigo(http.get(it["url"], headers=UA, timeout=60).text)}
                    e["novos"] += 1
                    if not it.get("titulo") or not RELEVANTE.search(f"{it['titulo']} {it.get('resumo', '')}"):
                        continue
                    if not it.get("data"):
                        continue   # sem data não entra: a fila exige data e URL da fonte
                    upsert(db, Registro, {"fonte": "escandalos", "tipo": "fila_item", "chave": chave},
                           {"titulo": it["titulo"][:250], "dados": montar(f, it, agora)})
                    e["na_fila"] += 1
                    n += 1
                db.commit()
            except Exception as ex:  # noqa: BLE001 - uma fonte fora do ar não derruba as outras
                e["erro"] = f"{type(ex).__name__}: {str(ex)[:120]}"
                n.avisos.append(f"{f['id']}: {e['erro']}")
        upsert(db, Registro, {"fonte": "escandalos", "tipo": "fila_fontes", "chave": "ultimo"}, {"titulo": "Estado das fontes da fila de escândalos", "dados": {"verificado_em": agora, "fontes": estado}})
        db.commit()
        if not any(x["lidos"] for x in estado):
            raise RuntimeError("; ".join(n.avisos) or "nenhuma fonte respondeu")
    return n.itens
