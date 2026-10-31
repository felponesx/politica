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
import time
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


def _texto(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def competencia_cgibs(titulo: str, url: str) -> dict:
    """Competência e data de publicação de um documento do CGIBS, só do que está escrito no título e no caminho do arquivo (`/upload/arquivos/AAAAMM/…`): a pasta é o mês em que
    o arquivo foi PUBLICADO no portal (não a data exata). Nada é inferido além disso."""
    t = sem_acento(titulo).lower()
    comp: dict = {"competencia": None, "periodo": None}
    quad = re.search(r"(\d)\D{0,3}\s*quadrimestre[^0-9]{0,80}(\d{4})", t)
    mes = re.search(r"(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+(?:de\s+)?(\d{4})", t)
    ano = re.search(r"(?:exercicio(?: financeiro)?|balanco[^0-9]{0,30}|em)\s*(?:de\s+)?(20\d{2})", t)
    if quad:
        comp = {"competencia": f"{quad.group(2)}-Q{quad.group(1)}", "periodo": f"{quad.group(1)}º quadrimestre de {quad.group(2)}"}
    elif mes:
        comp = {"competencia": f"{mes.group(2)}-{MESES[mes.group(1)]:02d}", "periodo": f"{mes.group(1)} de {mes.group(2)}"}
    elif ano:
        comp = {"competencia": ano.group(1), "periodo": f"exercício de {ano.group(1)}"}
    up = re.search(r"/upload/arquivos/(\d{4})(\d{2})/", url)
    comp["publicado_em_mes"] = f"{up.group(1)}-{up.group(2)}" if up else None
    return comp


def publicacoes_cgibs(html: str) -> list[dict]:
    """Documentos da página de relatórios do Comitê Gestor do IBS. A página é um acordeão: cada painel tem um título (o assunto e o período) e os arquivos dele.
    Guarda título do painel, nome do arquivo, formato, competência e mês de publicação. IBS: administrado pelo CGIBS."""
    out, vistos = [], set()
    painéis = re.split(r'<div class="panel panel-default">', html)[1:] or [html]
    for bloco in painéis:
        titulo_painel = ""
        m = re.search(r'<h4 class="panel-title">([\s\S]*?)</h4>', bloco)
        if m:
            titulo_painel = _texto(m.group(1))
        for a in re.finditer(r'<a[^>]+href="([^"]+\.(?:pdf|xlsx?|csv|ods|zip))"[^>]*>([\s\S]*?)</a>', bloco, re.I):
            url = a.group(1)
            url = url if url.startswith("http") else "https://cgibs.gov.br" + url
            nome = re.sub(r"\s*\(\.\w+ [\d.,]+ \w+\)\s*$", "", _texto(a.group(2))) or url.rsplit("/", 1)[-1]   # tira o "(.pdf 2,95 MBytes)" que o portal põe depois do nome
            if url in vistos:
                continue
            vistos.add(url)
            titulo = f"{titulo_painel} — {nome}" if titulo_painel else nome
            out.append({"url": url, "titulo": titulo[:300], "assunto": titulo_painel[:200], "arquivo": nome[:160], "formato": url.rsplit(".", 1)[-1].lower(), **competencia_cgibs(titulo_painel or nome, url)})
    return out


def buscar_pagina(urls: list[str], tentativas: int = 3, timeout: float = 45.0, pausa: float = 4.0) -> dict:
    """Lê uma página tentando cada endereço (com e sem `www`) e repetindo com espera crescente. Devolve SEMPRE um diagnóstico:
    estado = "ok" | "erro_conexao" (nada respondeu: timeout, DNS, TLS, 5xx) | "erro_http" (o portal respondeu com 4xx), e a lista de tentativas.
    Quem chama nunca deve ler `erro_conexao` como "não há publicação"."""
    import httpx
    log_t: list[dict] = []
    http_4xx = None
    for i in range(tentativas):
        for url in urls:
            try:
                r = http._cliente.get(url, headers={"Accept": "text/html,*/*"}, timeout=timeout)
                if r.status_code >= 500 or r.status_code == 429:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                if r.status_code >= 400:
                    http_4xx = f"HTTP {r.status_code}"
                    log_t.append({"url": url, "resultado": http_4xx})
                    continue
                log_t.append({"url": url, "resultado": "ok"})
                return {"estado": "ok", "texto": r.text, "url": str(r.url), "tentativas": log_t}
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                log_t.append({"url": url, "resultado": f"{type(e).__name__}"})
        if i < tentativas - 1:
            time.sleep(pausa * (i + 1))
    return {"estado": "erro_http" if http_4xx and all(t["resultado"] == http_4xx for t in log_t[-len(urls):]) else "erro_conexao", "texto": None, "url": None, "tentativas": log_t}


def situacao_do_tributo(leitura_ok: bool, publicacoes: list[dict], com_arrecadacao: bool) -> str:
    """Quatro situações que NUNCA se confundem: `indisponivel` (não deu para ler o portal), `sem_publicacao` (portal lido, nenhum documento),
    `publicacoes_sem_arrecadacao` (há documentos, nenhum traz arrecadação) e `arrecadacao_publicada`."""
    if not leitura_ok:
        return "indisponivel"
    if not publicacoes:
        return "sem_publicacao"
    return "arrecadacao_publicada" if com_arrecadacao else "publicacoes_sem_arrecadacao"


MENSAGEM = {"indisponivel": "Não foi possível ler o portal nesta conferência (erro de conexão). Isso NÃO significa que não há publicação: a leitura anterior foi mantida.",
            "sem_publicacao": "O portal respondeu, mas não lista nenhum documento.",
            "publicacoes_sem_arrecadacao": "O portal lista documentos, mas nenhum informa a arrecadação deste tributo. Não estimamos valores.",
            "arrecadacao_publicada": "Há documento ou coluna com a arrecadação deste tributo: veja os arquivos."}
PALAVRAS_ARRECADACAO = re.compile(r"arrecada|recolhi|repartic|distribui", re.I)


def _historico(anterior, agora: str, situacao: str, n_pub: int) -> list[dict]:
    h = list(((anterior.dados or {}).get("historico") or []) if anterior else [])
    h.append({"em": agora, "situacao": situacao, "publicacoes": n_pub})
    return h[-60:]


def _marcar(lista: list[dict], conhecidas: dict, tributo: str, orgao: str, hoje: date) -> list[dict]:
    return [{**p, "tributo": tributo, "orgao": orgao, "descoberto_em": (conhecidas.get(p["url"]) or {}).get("descoberto_em") or hoje.isoformat(),
             "menciona_cbs_ibs": (conhecidas.get(p["url"]) or {}).get("menciona_cbs_ibs")} for p in lista]


def avaliar_api_cbs() -> dict:
    """Lê (sem chamar a API) a documentação pública da API de Apuração da CBS e registra para que ela serve e quem pode usá-la.
    Conferido em 31/10/2026: as rotas (débitos, créditos, pagamentos, recolhimentos) são POR CONTRIBUINTE (`/debitos/{cnpj}` com CNPJ base), exigem token OAuth2 (client credentials),
    credenciais do estabelecimento matriz e IP autorizado, e respondem 401 "consumidor não autorizado para este NI" fora do próprio contribuinte. NÃO é arrecadação pública agregada: não é usada."""
    pag = buscar_pagina(["https://docs.receitafederal.gov.br/apuracao-cbs/"], tentativas=2, timeout=30, pausa=3)
    if pag["estado"] != "ok":
        return {"url": "https://docs.receitafederal.gov.br/apuracao-cbs/", "estado": pag["estado"], "tentativas": pag["tentativas"]}
    t = _texto(pag["texto"])
    rotas = sorted({h.rsplit("/", 1)[-1].replace(".html", "") for h in re.findall(r'href="([^"#]*apuracao-cbs/[^"#]+\.html)"', pag["texto"]) if "faq" not in h and "guia" not in h and "situacao" not in h})
    guia = buscar_pagina(["https://docs.receitafederal.gov.br/apuracao-cbs/guiaapiassincrona.html"], tentativas=2, timeout=30, pausa=3)
    g = _texto(guia["texto"]) if guia["estado"] == "ok" else ""
    por_contribuinte = bool(re.search(r"cnpj base|ni base do contribuinte|estabelecimento matriz", g, re.I))
    oauth = bool(re.search(r"oauth", g, re.I))
    return {"url": pag["url"], "estado": "ok", "titulo": t[:90], "rotas": rotas, "acesso_por_contribuinte": por_contribuinte, "exige_oauth2": oauth,
            "usada_pelo_sistema": False,
            "motivo": "A API devolve débitos, créditos, pagamentos e recolhimentos de UM contribuinte (CNPJ base), com credenciais e IP autorizados. Não traz a arrecadação pública agregada de CBS; por isso não é chamada."}


def _conferir_cbs(db, n) -> dict:
    """CBS (Receita Federal): planilha de arrecadação por estado, relatórios mensais "Análise Mensal" (+ anexo), página do Receita Data e a documentação da API de apuração."""
    hoje, agora = date.today(), datetime.now().isoformat(timespec="seconds")
    anterior = db.query(Registro).filter_by(fonte="receita", tipo="cbs_monitor", chave="ultimo").first() or db.query(Registro).filter_by(fonte="reforma", tipo="iva_monitor", chave="ultimo").first()
    pubs_antes = ((anterior.dados or {}).get("publicacoes") or []) if anterior else []
    if isinstance(pubs_antes, dict):   # monitor antigo (iva_monitor): lista única com CBS e IBS
        pubs_antes = [p for p in (pubs_antes.get("todas") or []) if p.get("tributo") == "CBS"]
    conhecidas = {p["url"]: p for p in pubs_antes}
    planilha, erro_planilha = {"n_colunas": 0, "colunas_cbs_ibs": [], "ultimo_mes": None, "total_por_mes": {}}, None
    try:
        r = http.get(settings.receita_arrecadacao_url, headers={"Accept": "*/*"}, timeout=120)
        planilha = analisar_planilha(r.content.decode("latin-1"))
    except Exception as e:  # noqa: BLE001
        erro_planilha = f"{type(e).__name__}: {str(e)[:100]}"
        n.avisos.append(f"Receita planilha: {erro_planilha}")
    cbs, paginas = [], []
    for ano in (hoje.year, hoje.year - 1):
        pag = buscar_pagina([f"{RECEITA_RELATORIOS}/{ano}"], tentativas=3, timeout=60)
        paginas.append({"ano": ano, "estado": pag["estado"], "tentativas": pag["tentativas"]})
        if pag["estado"] == "ok":
            cbs += publicacoes_receita(pag["texto"], ano)
        else:
            n.avisos.append(f"Receita relatórios {ano}: {pag['estado']}")
    leitura_ok = any(p["estado"] == "ok" for p in paginas)
    cbs.sort(key=lambda x: (x["competencia"], x["formato"]), reverse=True)
    recentes = {x["competencia"] for x in cbs[: VERIFICAR_CONTEUDO * 2]}
    todas = _marcar(cbs, conhecidas, "CBS", "Receita Federal", hoje)
    for pub in todas:
        if pub["competencia"] in recentes and pub["menciona_cbs_ibs"] is None:
            try:
                pub["menciona_cbs_ibs"] = menciona_cbs_ibs(http.get(pub["url"], headers={"Accept": "*/*"}, timeout=120).content, pub["formato"])
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"{pub['titulo']}: {type(e).__name__}")
    if not leitura_ok and conhecidas:
        todas = list(conhecidas.values())   # leitura falhou: mantém o que já se sabia em vez de apagar
    novas = [p for p in todas if p["url"] not in conhecidas]
    primeira_vez = anterior is None
    receitadata = buscar_pagina(["https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/receitadata/arrecadacao"], tentativas=2, timeout=60)
    com_arrecadacao = bool(planilha["colunas_cbs_ibs"]) or any(p.get("menciona_cbs_ibs") for p in todas)
    situacao = situacao_do_tributo(leitura_ok or not erro_planilha, todas or ([{}] if planilha["n_colunas"] else []), com_arrecadacao)
    if novas and not primeira_vez:
        alertas.enviar("BRASIL+: nova publicação da Receita sobre arrecadação (CBS) — " + "; ".join(f"{p['titulo']} ({p['url']})" for p in novas[:5]) + (" [cita CBS]" if any(p.get("menciona_cbs_ibs") for p in novas) else ""))
    d = {"tributo": "CBS", "orgao": "Receita Federal", "checado_em": agora, "situacao": situacao, "mensagem": MENSAGEM[situacao], "arrecadacao_publicada": com_arrecadacao,
         "planilha": {**planilha, "url": settings.receita_arrecadacao_url, "erro": erro_planilha}, "paginas_relatorios": paginas, "relatorios_url": RECEITA_RELATORIOS,
         "receitadata": {"url": "https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos/receitadata/arrecadacao", "estado": receitadata["estado"]},
         "api_apuracao": avaliar_api_cbs(), "publicacoes": todas, "novas_nesta_conferencia": novas if not primeira_vez else [], "primeira_conferencia": primeira_vez,
         "ultima_competencia": max([p["competencia"] for p in todas] or [planilha.get("ultimo_mes") or ""]) or None, "historico": _historico(anterior if anterior and anterior.tipo == "cbs_monitor" else None, agora, situacao, len(todas))}
    upsert(db, Registro, {"fonte": "receita", "tipo": "cbs_monitor", "chave": "ultimo"}, {"titulo": "Monitor da arrecadação de CBS (Receita Federal)", "dados": d})
    db.commit()
    return d


def _conferir_ibs(db, n) -> dict:
    """IBS (Comitê Gestor do IBS): página de relatórios e página de transparência, lidas em separado (uma que falha não impede a outra) com e sem `www`."""
    hoje, agora = date.today(), datetime.now().isoformat(timespec="seconds")
    anterior = db.query(Registro).filter_by(fonte="cgibs", tipo="ibs_monitor", chave="ultimo").first()
    conhecidas = {p["url"]: p for p in (((anterior.dados or {}).get("publicacoes") or []) if anterior else [])}
    rel = buscar_pagina(["https://cgibs.gov.br/relatorios", "https://www.cgibs.gov.br/relatorios"])
    tra = buscar_pagina(["https://cgibs.gov.br/transparencia", "https://www.cgibs.gov.br/transparencia"], tentativas=2)
    pubs = publicacoes_cgibs(rel["texto"]) if rel["estado"] == "ok" else []
    transp = arquivos_cgibs(tra["texto"]) if tra["estado"] == "ok" else []
    for a in transp:
        a.update({"arquivo": a["titulo"], "assunto": "Transparência", "formato": a["url"].rsplit(".", 1)[-1].lower(), **competencia_cgibs(a["titulo"], a["url"])})
    unidas = {p["url"]: p for p in pubs + transp}
    leitura_ok = rel["estado"] == "ok" or tra["estado"] == "ok"
    for estado, nome in ((rel["estado"], "relatórios"), (tra["estado"], "transparência")):
        if estado != "ok":
            n.avisos.append(f"CGIBS {nome}: {estado}")
    todas = _marcar(list(unidas.values()), conhecidas, "IBS", "Comitê Gestor do IBS (CGIBS)", hoje)
    if not leitura_ok and conhecidas:
        todas = list(conhecidas.values())
    novas = [p for p in todas if p["url"] not in conhecidas]
    primeira_vez = anterior is None
    sobre_arrecadacao = [p for p in todas if PALAVRAS_ARRECADACAO.search(p["titulo"] + " " + p["url"])]
    situacao = situacao_do_tributo(leitura_ok, todas, bool(sobre_arrecadacao))
    if novas and not primeira_vez:
        alertas.enviar("BRASIL+: novo documento do Comitê Gestor do IBS — " + "; ".join(f"{p['titulo']} ({p['url']})" for p in novas[:5]))
    d = {"tributo": "IBS", "orgao": "Comitê Gestor do IBS (CGIBS)", "checado_em": agora, "situacao": situacao, "mensagem": MENSAGEM[situacao], "arrecadacao_publicada": situacao == "arrecadacao_publicada",
         "paginas": {"relatorios": {"estado": rel["estado"], "tentativas": rel["tentativas"]}, "transparencia": {"estado": tra["estado"], "tentativas": tra["tentativas"]}},
         "publicacoes": todas, "sobre_arrecadacao": sobre_arrecadacao, "novas_nesta_conferencia": novas if not primeira_vez else [], "primeira_conferencia": primeira_vez,
         "ultima_competencia": max([p["competencia"] for p in todas if p.get("competencia")] or [""]) or None, "ultima_publicacao_em_mes": max([p["publicado_em_mes"] for p in todas if p.get("publicado_em_mes")] or [""]) or None,
         "historico": _historico(anterior, agora, situacao, len(todas))}
    upsert(db, Registro, {"fonte": "cgibs", "tipo": "ibs_monitor", "chave": "ultimo"}, {"titulo": "Monitor do IBS (Comitê Gestor)", "dados": d})
    db.commit()
    return d


def coletar_cbs():
    """Só a CBS (Receita Federal)."""
    with registrar_coleta("receita", "cbs_monitor") as (db, n):
        _conferir_cbs(db, n)
        n += 1
    return n.itens


def coletar_ibs():
    """Só o IBS (Comitê Gestor)."""
    with registrar_coleta("cgibs", "ibs_monitor") as (db, n):
        _conferir_ibs(db, n)
        n += 1
    return n.itens


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
    """Confere as duas fontes, cada uma por conta própria (CBS: Receita; IBS: CGIBS), e grava os dois monitores separados (`cbs_monitor` e `ibs_monitor`).
    Uma fonte fora do ar não impede a outra. Nunca grava arrecadação zero nem estimada: sem publicação, o monitor diz "sem arrecadação publicada" ou "portal indisponível"."""
    with registrar_coleta("reforma", "iva_monitor") as (db, n):
        for nome, fn in (("CBS", _conferir_cbs), ("IBS", _conferir_ibs)):
            try:
                fn(db, n)
                n += 1
            except Exception as e:  # noqa: BLE001
                db.rollback()
                n.avisos.append(f"{nome}: {type(e).__name__}: {str(e)[:120]}")
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhuma fonte foi conferida")
    return n.itens
