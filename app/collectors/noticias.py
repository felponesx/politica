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

# (veículo, url, só política?) — feeds alternativos do mesmo veículo vêm em sequência; vale o primeiro que responder
FEEDS = [
    ("g1", "https://g1.globo.com/rss/g1/politica/", True),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/politica/feed", True),
    ("CNN Brasil", "https://www.cnnbrasil.com.br/feed/", False),
    ("O Globo", "https://oglobo.globo.com/rss/oglobo", False),
    ("O Globo", "https://oglobo.globo.com/rss/politica", True),
    ("Folha de S.Paulo", "https://feeds.folha.uol.com.br/poder/rss091.xml", True),
    ("Agência Câmara / TV Câmara", "https://www.camara.leg.br/noticias/rss/dinamico/POLITICA", True),
    ("Agência Câmara / TV Câmara", "https://www.camara.leg.br/noticias/rss/ultimas-noticias", True),
    ("Agência Senado", "https://www12.senado.leg.br/noticias/rss", True),
    ("Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml", True),
    ("UOL", "https://rss.uol.com.br/feed/noticias.xml", False),
]
PALAVRAS = re.compile(r"\b(congresso|camara|senado|deputad|senador|governo|presiden|ministr|stf|supremo|tse|eleic|"
                      r"eleitor|partido|planalto|lula|bolsonaro|governador|prefeit|lei\b|projeto de lei|pec\b|cpi\b|"
                      r"votac|reforma|orcamento|politic)", re.I)


def _tag(item: str, nome: str) -> str:
    m = re.search(rf"<{nome}[^>]*>(.*?)</{nome}>", item, re.S | re.I)
    if not m:
        return ""
    t = m.group(1).strip()
    t = re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", t, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", t)).strip()


def ler_feed(xml: str, veiculo: str, so_politica: bool) -> list[dict]:
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
        out.append({"veiculo": veiculo, "titulo": titulo, "link": link.strip(), "resumo": resumo,
                    "data": data.astimezone(timezone.utc).isoformat() if data else None})
    return out


def coletar_noticias(dias: int = 14):
    """Últimas notícias de política dos feeds; apaga as mais antigas que `dias`."""
    from sqlalchemy import delete
    with registrar_coleta("noticias", "politica") as (db, n):
        feitos = set()
        for veiculo, url, so_pol in FEEDS:
            if veiculo in feitos:
                continue
            try:
                r = http._cliente.get(url, headers=UA, timeout=30, follow_redirects=True)
                if r.status_code != 200 or "<item" not in r.text:
                    continue
            except Exception as e:  # um veículo fora do ar não derruba os outros
                n.avisos.append(f"{veiculo}: {type(e).__name__}")
                continue
            itens = ler_feed(r.text, veiculo, so_pol)
            if not itens:
                continue
            feitos.add(veiculo)
            for it in itens:
                chave = hashlib.sha1(it["link"].encode()).hexdigest()[:20]
                ano = int(it["data"][:4]) if it["data"] else None
                upsert(db, Registro, {"fonte": "noticias", "tipo": "materia", "chave": chave},
                       {"ano": ano, "titulo": it["titulo"][:500], "dados": it})
                n += 1
        faltaram = sorted({v for v, _, _ in FEEDS} - feitos)
        if faltaram:
            n.avisos.append("sem resposta: " + ", ".join(faltaram))
        limite = (datetime.now(timezone.utc) - timedelta(days=int(dias))).isoformat()
        velhas = [r.id for r in db.query(Registro).filter(Registro.fonte == "noticias", Registro.tipo == "materia")
                  if (r.dados or {}).get("data") and r.dados["data"] < limite]
        if velhas:
            db.execute(delete(Registro).where(Registro.id.in_(velhas)))
    return n.itens
