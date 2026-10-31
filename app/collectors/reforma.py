"""Monitor da reforma tributária do consumo (CBS e IBS): confere se as fontes oficiais já publicam a ARRECADAÇÃO desses tributos.

Conferido em 30/10/2026: a planilha de arrecadação por estado da Receita não tem coluna de CBS nem de IBS (nenhuma coluna nova em 2026) e o portal de transparência
do Comitê Gestor do IBS só publica contratos, portarias e orçamento. Este coletor NÃO inventa valores: todo mês ele (1) lê o cabeçalho da planilha da Receita e
procura colunas CBS/IBS (se aparecerem, soma por mês) e (2) lista os arquivos da página de transparência do CGIBS. O resultado diz, com data, se há ou não arrecadação publicada."""
import csv
import io
import logging
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path

from app import alertas, http
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Registro
from app.utils import sem_acento, upsert

log = logging.getLogger("brasilplus.reforma")
CGIBS = "https://www.cgibs.gov.br/transparencia"
CGIBS_RELATORIOS = "https://cgibs.gov.br/relatorios"
RECEITA_RELATORIOS = "https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/arrecadacao-federal"
ABREV = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}
VERIFICAR_CONTEUDO = 3   # abre o PDF e o anexo dos últimos N meses para procurar CBS/IBS
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


def publicacoes_receita(html: str, ano: int) -> list[dict]:
    """"Análise Mensal - Set 2026" (PDF) e o "Anexo" (xlsx) de cada mês, da página do ano em `arrecadacao-federal/<ano>`. CBS: administrada pela Receita Federal."""
    out, vistos = [], set()
    for m in re.finditer(r'href="([^"]*/arrecadacao-federal/%d/(analise-mensal-([a-z]{3})-%d(-anexo)?\.(pdf|xlsx))(?:/view)?)"' % (ano, ano), html):
        url = m.group(1).split("/view")[0]
        if url in vistos or m.group(3) not in ABREV:
            continue
        vistos.add(url)
        out.append({"url": url if url.startswith("http") else "https://www.gov.br" + url, "tipo": "anexo (planilha)" if m.group(4) else "análise mensal (PDF)", "formato": m.group(5),
                    "competencia": f"{ano}-{ABREV[m.group(3)]:02d}", "titulo": f"Análise Mensal da Arrecadação - {m.group(3).capitalize()} {ano}" + (" - Anexo" if m.group(4) else "")})
    return out


def publicacoes_cgibs(html: str) -> list[dict]:
    """Arquivos (PDF/planilhas) da página de relatórios do Comitê Gestor do IBS. IBS: administrado pelo CGIBS."""
    out, vistos = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]+\.(?:pdf|xlsx?|csv|ods))"[^>]*>([\s\S]*?)</a>', html, re.I):
        url = m.group(1)
        url = url if url.startswith("http") else "https://cgibs.gov.br" + url
        titulo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip() or url.rsplit("/", 1)[-1]
        if url not in vistos:
            vistos.add(url)
            out.append({"url": url, "titulo": titulo[:160], "formato": url.rsplit(".", 1)[-1].lower()})
    return out


def menciona_cbs_ibs(conteudo: bytes, formato: str) -> bool | None:
    """True/False se o arquivo cita CBS/IBS; None se não deu para ler (sem `pdftotext`, arquivo ilegível)."""
    try:
        if formato == "xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
            for ws in wb.worksheets:
                for linha in ws.iter_rows(values_only=True):
                    for c in linha:
                        if isinstance(c, str) and PADRAO.search(sem_acento(c).upper()):
                            return True
            return False
        if formato == "pdf" and shutil.which("pdftotext"):
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "a.pdf").write_bytes(conteudo)
                subprocess.run(["pdftotext", "-layout", str(Path(d) / "a.pdf"), str(Path(d) / "a.txt")], check=True, timeout=120)
                return bool(PADRAO.search(sem_acento((Path(d) / "a.txt").read_text(errors="replace")).upper()))
    except Exception as e:  # noqa: BLE001
        log.warning("não consegui ler %s: %s", formato, type(e).__name__)
    return None


def coletar_reforma_tributaria():
    """Confere as fontes oficiais e grava o estado ("arrecadação publicada: sim/não") com a data da conferência.
    CBS (federal, Receita): planilha de arrecadação por estado + "Análise Mensal" e anexo de cada mês. IBS (compartilhado, Comitê Gestor): páginas de transparência e de relatórios.
    Cada publicação guarda a URL original, a competência (quando há) e a data em que foi DESCOBERTA; publicação nova dispara um alerta (Telegram/webhook, se configurados)."""
    with registrar_coleta("reforma", "iva_monitor") as (db, n):
        hoje = date.today()
        agora = datetime.now().isoformat(timespec="seconds")
        r = http.get(settings.receita_arrecadacao_url, headers={"Accept": "*/*"}, timeout=120)
        planilha = analisar_planilha(r.content.decode("latin-1"))
        anterior = db.query(Registro).filter_by(fonte="reforma", tipo="iva_monitor", chave="ultimo").first()
        conhecidas: dict[str, dict] = {p["url"]: p for p in ((anterior.dados or {}).get("publicacoes", {}).get("todas", []) if anterior else [])}
        # CBS: relatórios mensais da Receita (páginas do ano corrente e do anterior)
        cbs, erro_receita = [], None
        for ano in (hoje.year, hoje.year - 1):
            try:
                cbs += publicacoes_receita(http.get(f"{RECEITA_RELATORIOS}/{ano}", headers={"Accept": "*/*"}, timeout=60).text, ano)
            except Exception as e:  # noqa: BLE001
                erro_receita = f"{ano}: {type(e).__name__}"
                n.avisos.append(f"Receita relatórios {erro_receita}")
        # IBS: transparência e relatórios do Comitê Gestor
        arquivos, ibs, erro_cgibs = [], [], None
        try:
            arquivos = arquivos_cgibs(http.get(CGIBS, headers={"Accept": "*/*"}, timeout=60).text)
            ibs = publicacoes_cgibs(http.get(CGIBS_RELATORIOS, headers={"Accept": "*/*"}, timeout=60).text)
        except Exception as e:  # noqa: BLE001 - a Receita já responde a pergunta principal
            erro_cgibs = f"{type(e).__name__}: {str(e)[:120]}"
            n.avisos.append(f"CGIBS: {erro_cgibs}")
        # competência mais recente primeiro; só os últimos meses têm o conteúdo aberto para procurar CBS/IBS
        cbs.sort(key=lambda x: (x["competencia"], x["formato"]), reverse=True)
        recentes = {x["competencia"] for x in cbs[: VERIFICAR_CONTEUDO * 2]}
        todas = []
        for tributo, lista in (("CBS", cbs), ("IBS", ibs)):
            for pub in lista:
                antigo = conhecidas.get(pub["url"], {})
                pub = {**pub, "tributo": tributo, "orgao": "Receita Federal" if tributo == "CBS" else "Comitê Gestor do IBS (CGIBS)", "descoberto_em": antigo.get("descoberto_em") or hoje.isoformat(),
                       "menciona_cbs_ibs": antigo.get("menciona_cbs_ibs")}
                if tributo == "CBS" and pub["competencia"] in recentes and pub["menciona_cbs_ibs"] is None:
                    try:
                        pub["menciona_cbs_ibs"] = menciona_cbs_ibs(http.get(pub["url"], headers={"Accept": "*/*"}, timeout=120).content, pub["formato"])
                    except Exception as e:  # noqa: BLE001
                        n.avisos.append(f"{pub['titulo']}: {type(e).__name__}")
                todas.append(pub)
        # se a leitura anterior falhou, mantém o que já se sabia em vez de apagar
        if erro_receita and not cbs:
            todas += [p for p in conhecidas.values() if p.get("tributo") == "CBS"]
        if erro_cgibs and not ibs:
            todas += [p for p in conhecidas.values() if p.get("tributo") == "IBS"]
        novas = [p for p in todas if p["url"] not in conhecidas]
        primeira_vez = anterior is None
        palavras = re.compile(r"arrecada|recolhi|repartic|distribui", re.I)
        sobre_arrecadacao = [a for a in arquivos + ibs if palavras.search(a["titulo"] + a["url"])]
        menciona = [p for p in todas if p.get("menciona_cbs_ibs")]
        publicada = bool(planilha["colunas_cbs_ibs"]) or bool(sobre_arrecadacao) or bool(menciona)
        if novas and not primeira_vez:
            alertas.enviar("BRASIL+: nova publicação sobre arrecadação/reforma tributária — " + "; ".join(f"{p['tributo']}: {p['titulo']} ({p['url']})" for p in novas[:5])
                           + (" [cita CBS/IBS]" if any(p.get("menciona_cbs_ibs") for p in novas) else ""))
        d = {"checado_em": agora, "arrecadacao_publicada": publicada,
             "receita": {**planilha, "url": settings.receita_arrecadacao_url, "relatorios_url": RECEITA_RELATORIOS, "erro_relatorios": erro_receita},
             "cgibs": {"url": CGIBS, "relatorios_url": CGIBS_RELATORIOS, "arquivos": arquivos, "arquivos_sobre_arrecadacao": sobre_arrecadacao, "erro": erro_cgibs},
             "publicacoes": {"todas": todas, "cbs_receita": [p for p in todas if p["tributo"] == "CBS"], "ibs_cgibs": [p for p in todas if p["tributo"] == "IBS"],
                             "novas_nesta_conferencia": novas if not primeira_vez else [], "que_citam_cbs_ibs": menciona, "primeira_conferencia": primeira_vez}}
        upsert(db, Registro, {"fonte": "reforma", "tipo": "iva_monitor", "chave": "ultimo"}, {"titulo": "Monitor da arrecadação de CBS e IBS", "dados": d})
        db.commit()
        n += 1
    return n.itens
