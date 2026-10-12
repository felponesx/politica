"""Notícias de política dos principais veículos (feeds RSS públicos).

Guardamos só título, resumo curto, data, veículo e o link para a matéria original (o texto completo fica no site do
veículo). Feeds que já são de política entram inteiros; feeds gerais passam por um filtro de palavras.
"""
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ leitor de RSS; dados publicos)", "Accept": "application/rss+xml, application/xml, text/xml, */*"}

# (veículo, url, só política?, tema). Feeds do mesmo veículo e tema vêm em sequência: vale o primeiro que responder.
# Feeds de editoria (economia, justiça) entram inteiros; feeds gerais passam pelo filtro de palavras de política.
FEEDS = [
    ("g1", "https://g1.globo.com/rss/g1/politica/", True, "geral"),
    ("g1", "https://g1.globo.com/rss/g1/economia/", True, "economia"),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/politica/feed", True, "geral"),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/feed/", False, "geral"),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/economia/feed", True, "economia"),
    ("O Globo", "https://oglobo.globo.com/rss/oglobo", False, "geral"),
    ("O Globo", "https://oglobo.globo.com/rss/politica", True, "geral"),
    ("Folha de S.Paulo", "https://feeds.folha.uol.com.br/poder/rss091.xml", True, "geral"),
    ("Folha de S.Paulo", "https://feeds.folha.uol.com.br/mercado/rss091.xml", True, "economia"),
    ("Estadão", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/", True, "geral"),
    ("Agência Câmara / TV Câmara", "https://www.camara.leg.br/noticias/rss/dinamico/POLITICA", True, "legislativo"),
    ("Agência Câmara / TV Câmara", "https://www.camara.leg.br/noticias/rss/ultimas-noticias", True, "legislativo"),
    ("Agência Senado", "https://www12.senado.leg.br/noticias/rss", True, "legislativo"),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml", True, "geral"),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml", True, "economia"),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/justica/feed.xml", True, "juridico"),
    ("UOL", "https://rss.uol.com.br/feed/noticias.xml", False, "geral"),
    ("UOL", "https://rss.uol.com.br/feed/economia.xml", True, "economia"),
    ("Poder360", "https://www.poder360.com.br/feed/", False, "geral"),
    ("Metrópoles", "https://www.metropoles.com/feed", False, "geral"),
    ("CartaCapital", "https://www.cartacapital.com.br/feed/", False, "geral"),
    ("Congresso em Foco", "https://congressoemfoco.uol.com.br/feed/", True, "legislativo"),
    ("InfoMoney", "https://www.infomoney.com.br/feed/", True, "economia"),
    ("Exame", "https://exame.com/feed/", False, "economia"),
    ("Consultor Jurídico (Conjur)", "https://www.conjur.com.br/rss.xml", True, "juridico"),
    ("Migalhas", "https://www.migalhas.com.br/rss/quentes", True, "juridico"),
    ("Conselho Nacional de Justiça", "https://www.cnj.jus.br/feed/", True, "juridico"),
]
PALAVRAS = re.compile(r"\b(congresso|camara|senado|deputad|senador|governo|presiden|ministr|stf|supremo|tse|eleic|"
                      r"eleitor|partido|planalto|lula|bolsonaro|governador|prefeit|lei\b|projeto de lei|pec\b|cpi\b|"
                      r"votac|reforma|orcamento|politic)", re.I)


def _tag(item: str, nome: str) -> str:
    m = re.search(rf"<{nome}[^>]*>(.*?)</{nome}>", item, re.S | re.I)
    if not m:
        return ""
    t = m.group(1).strip()
    t = re.sub(r"^<!\[CDATA\[(.*?)\]\]>$", r"\1", t, flags=re.S)
    t = html.unescape(t)  # alguns feeds mandam HTML escapado (&lt;a href...&gt;); só depois tiramos as tags
    t = re.sub(r"<!\[CDATA\[|\]\]>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def decodificar(conteudo: bytes, cabecalho: str = "") -> str:
    """Texto do feed no charset certo: o da declaração <?xml encoding=...?> ou do cabeçalho (a Folha usa ISO-8859-1)."""
    m = re.search(rb"<\?xml[^>]*encoding=[\"']([\w-]+)", conteudo[:300]) or re.search(r"charset=([\w-]+)", cabecalho or "", re.I)
    cod = (m.group(1).decode() if m and isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return conteudo.decode(cod, errors="replace")
    except LookupError:
        return conteudo.decode("utf-8", errors="replace")


def ler_feed(xml: str, veiculo: str, so_politica: bool, tema: str = "geral") -> list[dict]:
    """Itens de um RSS (título, link, data, resumo). Itens fora de política saem quando o feed é geral."""
    out = []
    for item in re.findall(r"<item\b.*?</item>", xml, re.S | re.I):
        titulo = re.sub(r"\s+", " ", _tag(item, "title"))
        link = _tag(item, "link") or (re.search(r'<link[^>]+href="([^"]+)"', item) or [None, ""])[1]
        if not titulo or not link.startswith("http"):
            continue
        resumo = re.sub(r"\s+", " ", _tag(item, "description") or _tag(item, "atom:subtitle"))[:400]
        cat = " ".join(_tag(c, "category") for c in re.findall(r"<category.*?</category>", item, re.S))
        if not so_politica and not PALAVRAS.search(sem_acento(f"{titulo} {resumo} {cat}")):
            continue
        data = None
        for t in ("pubDate", "dc:date", "published", "updated"):
            v = _tag(item, t)
            if v:
                try:
                    data = parsedate_to_datetime(v)
                except (TypeError, ValueError):
                    try:
                        data = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    except ValueError:
                        data = None
                if data:
                    break
        if data and data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)
        out.append({"veiculo": veiculo, "tema": tema, "titulo": titulo, "link": link.strip(), "resumo": resumo,
                    "data": data.astimezone(timezone.utc).isoformat() if data else None})
    return out


def coletar_noticias(dias: int = 14):
    """Últimas notícias de política dos feeds; apaga as mais antigas que `dias`."""
    from sqlalchemy import delete
    with registrar_coleta("noticias", "politica") as (db, n):
        feitos = set()
        for veiculo, url, so_pol, tema in FEEDS:
            if (veiculo, tema) in feitos:
                continue
            try:
                r = http._cliente.get(url, headers=UA, timeout=30, follow_redirects=True)
                texto = decodificar(r.content, r.headers.get("content-type", ""))
                if r.status_code != 200 or "<item" not in texto:
                    continue
            except Exception as e:  # um veículo fora do ar não derruba os outros
                n.avisos.append(f"{veiculo}: {type(e).__name__}")
                continue
            itens = ler_feed(texto, veiculo, so_pol, tema)
            if not itens:
                continue
            feitos.add((veiculo, tema))
            for it in itens:
                chave = hashlib.sha1(it["link"].encode()).hexdigest()[:20]
                ano = int(it["data"][:4]) if it["data"] else None
                upsert(db, Registro, {"fonte": "noticias", "tipo": "materia", "chave": chave},
                       {"ano": ano, "titulo": it["titulo"][:500], "dados": it})
                n += 1
        faltaram = sorted({f"{v} ({t})" for v, _, _, t in FEEDS} - {f"{v} ({t})" for v, t in feitos})
        if faltaram:
            n.avisos.append("sem resposta: " + ", ".join(faltaram))
        limite = (datetime.now(timezone.utc) - timedelta(days=int(dias))).isoformat()
        velhas = [r.id for r in db.query(Registro).filter(Registro.fonte == "noticias", Registro.tipo == "materia")
                  if (r.dados or {}).get("data") and r.dados["data"] < limite]
        if velhas:
            db.execute(delete(Registro).where(Registro.id.in_(velhas)))
    return n.itens
