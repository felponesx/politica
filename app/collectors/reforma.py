"""Monitor da reforma tributária do consumo (CBS e IBS): confere se as fontes oficiais já publicam a ARRECADAÇÃO desses tributos.

Conferido em 30/10/2026: a planilha de arrecadação por estado da Receita não tem coluna de CBS nem de IBS (nenhuma coluna nova em 2026) e o portal de transparência
do Comitê Gestor do IBS só publica contratos, portarias e orçamento. Este coletor NÃO inventa valores: todo mês ele (1) lê o cabeçalho da planilha da Receita e
procura colunas CBS/IBS (se aparecerem, soma por mês) e (2) lista os arquivos da página de transparência do CGIBS. O resultado diz, com data, se há ou não arrecadação publicada."""
import csv
import io
import logging
import re
from datetime import datetime

from app import http
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Registro
from app.utils import sem_acento, upsert

log = logging.getLogger("brasilplus.reforma")
CGIBS = "https://www.cgibs.gov.br/transparencia"
PADRAO = re.compile(r"(?<![A-Z0-9])(CBS|IBS|IVA)(?![A-Z0-9])")
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


def num(v) -> float:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if str(v or "").strip() else 0.0
    except ValueError:
        return 0.0


def analisar_planilha(texto: str) -> dict:
    """Cabeçalho + colunas de CBS/IBS (com soma por mês, se existirem) da planilha de arrecadação por estado."""
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = next(leitor)
    achadas = [i for i, c in enumerate(cab) if PADRAO.search(sem_acento(c).upper())]
    por_mes: dict[str, dict] = {}
    ultimo = None
    i_ano, i_mes = 0, 1
    for l in leitor:
        if len(l) < len(cab):
            continue
        mes = MESES.get(sem_acento(l[i_mes]).lower())
        if not mes:
            continue
        chave = f"{l[i_ano]}-{mes:02d}"
        ultimo = max(ultimo or chave, chave)
        for i in achadas:
            por_mes.setdefault(chave, {}).setdefault(cab[i].strip(), 0.0)
            por_mes[chave][cab[i].strip()] += num(l[i])
    return {"n_colunas": len(cab), "colunas_cbs_ibs": [cab[i].strip() for i in achadas], "ultimo_mes": ultimo,
            "total_por_mes": {k: {c: round(v, 2) for c, v in d.items()} for k, d in sorted(por_mes.items())[-24:]}}


def arquivos_cgibs(html: str) -> list[dict]:
    """Links de arquivos (PDF/planilhas) da página de transparência do Comitê Gestor do IBS."""
    vistos, out = set(), []
    for m in re.finditer(r'href="([^"]+\.(?:pdf|xlsx?|csv|ods))"[^>]*>(.*?)</a>', html, re.I | re.S):
        url, titulo = m.group(1), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        if url not in vistos:
            vistos.add(url)
            out.append({"url": url if url.startswith("http") else "https://www.cgibs.gov.br" + url, "titulo": titulo[:160]})
    return out


def coletar_reforma_tributaria():
    """Confere as duas fontes e grava o estado ("arrecadação publicada: sim/não") com a data da conferência."""
    with registrar_coleta("reforma", "iva_monitor") as (db, n):
        r = http.get(settings.receita_arrecadacao_url, headers={"Accept": "*/*"}, timeout=120)
        planilha = analisar_planilha(r.content.decode("latin-1"))
        arquivos, aviso_cgibs = [], None
        try:
            arquivos = arquivos_cgibs(http.get(CGIBS, headers={"Accept": "*/*"}, timeout=60).text)
        except Exception as e:  # noqa: BLE001 - a Receita já responde a pergunta principal
            aviso_cgibs = f"{type(e).__name__}: {str(e)[:120]}"
            n.avisos.append(f"CGIBS: {aviso_cgibs}")
        palavras = re.compile(r"arrecada|recolhi|repartic|distribui", re.I)
        sobre_arrecadacao = [a for a in arquivos if palavras.search(a["titulo"] + a["url"])]
        publicada = bool(planilha["colunas_cbs_ibs"]) or bool(sobre_arrecadacao)
        d = {"checado_em": datetime.now().isoformat(timespec="seconds"), "arrecadacao_publicada": publicada,
             "receita": {**planilha, "url": settings.receita_arrecadacao_url}, "cgibs": {"url": CGIBS, "arquivos": arquivos, "arquivos_sobre_arrecadacao": sobre_arrecadacao, "erro": aviso_cgibs}}
        upsert(db, Registro, {"fonte": "reforma", "tipo": "iva_monitor", "chave": "ultimo"}, {"titulo": "Monitor da arrecadação de CBS e IBS", "dados": d})
        db.commit()
        n += 1
    return n.itens
