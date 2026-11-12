"""Concursos, cursos gratuitos e eventos pagos com dinheiro público: leitura dos registros gravados por
app/collectors/oportunidades.py (tarefas concursos, cursos-gratuitos, eventos-shows, eventos-patrocinios)."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Coleta, Registro
from app.utils import UFS

AVISO_CONCURSOS = ("Lista montada a partir dos diários oficiais: Diário Oficial da União (órgãos federais, Câmara, Senado, tribunais, "
                   "universidades, conselhos) e, quando o serviço está no ar, os diários das prefeituras (Querido Diário). Concursos de "
                   "governos estaduais (como delegado da Polícia Civil) saem nos diários de cada estado e ainda não entram. Vagas, salário e "
                   "datas aparecem só quando estão escritos no texto do edital; confira sempre o edital oficial pelo link.")
AVISO_CURSOS = ("Só cursos gratuitos: Escola Virtual.Gov (Enap, governo federal; todos gratuitos e com certificado) e Sebrae (só os de "
                "preço zero na loja do Sebrae). Senai, Senac, Sesi e os cursos dos CRAS e das prefeituras não publicam catálogo aberto "
                "que dê para ler automaticamente: veja os links de onde procurar.")
ONDE_PROCURAR = [
    {"nome": "Senai — cursos gratuitos", "url": "https://www.portaldaindustria.com.br/senai/", "obs": "Cada estado tem seu catálogo; muitos cursos técnicos e de qualificação são gratuitos."},
    {"nome": "Senac — Programa Senac de Gratuidade (PSG)", "url": "https://www.senac.br/", "obs": "Vagas gratuitas para quem tem renda familiar de até 2 salários mínimos por pessoa."},
    {"nome": "Sesi", "url": "https://www.portaldaindustria.com.br/sesi/", "obs": "Educação básica e cursos para trabalhadores da indústria e dependentes."},
    {"nome": "CRAS da sua cidade", "url": "https://aplicacoes.mds.gov.br/sagi/cras/", "obs": "Cursos e oficinas gratuitas do serviço de assistência social do município."},
    {"nome": "Pronatec / Novos Caminhos (MEC)", "url": "https://www.gov.br/mec/pt-br/novos-caminhos", "obs": "Cursos técnicos e de qualificação gratuitos em institutos federais e redes estaduais."},
]
AVISO_EVENTOS = ("Shows e apresentações artísticas que prefeituras, governos estaduais e órgãos federais contrataram sem licitação "
                 "(inexigibilidade: contratação de artista, Lei 14.133, art. 74, II), publicados no Portal Nacional de Contratações "
                 "Públicas (PNCP). Valor = valor homologado; sem ele, o estimado (marcado). Artista, nome da festa e data só quando estão "
                 "escritos no objeto do contrato. Palco, som, segurança e outros gastos da festa são contratados à parte e não estão somados. "
                 "Contratação publicada não prova que o show aconteceu nem indica irregularidade.")
AVISO_PATROCINIO = ("Patrocínio de festa da prefeitura por empresas não é publicado em base aberta. O que existe é a Lei Rouanet: "
                    "projetos culturais (festivais, festas, feiras, shows) e as empresas que patrocinaram, com abatimento no imposto de renda "
                    "(sistema SALIC do Ministério da Cultura). Pessoas físicas aparecem só somadas, sem nome.")


def _dados(db: Session, tipo: str, fontes: tuple[str, ...] | None = None) -> list[dict]:
    q = select(Registro.dados).where(Registro.tipo == tipo)
    if fontes:
        q = q.where(Registro.fonte.in_(fontes))
    return [d for (d,) in db.execute(q) if d]


def _ultima(db: Session, tarefa: str) -> dict | None:
    c = db.execute(select(Coleta).where(Coleta.fonte == "oportunidades", Coleta.tarefa == tarefa, Coleta.status.in_(("ok", "parcial")))
                   .order_by(Coleta.id.desc()).limit(1)).scalar_one_or_none()
    if not c:
        return None
    return {"quando": (c.fim or c.inicio).isoformat() if (c.fim or c.inicio) else None, "status": c.status, "aviso": c.erro}


def concursos(db: Session, dias: int = 120) -> dict | None:
    hoje = date.today().isoformat()
    corte = (date.today() - timedelta(days=dias)).isoformat()
    itens = []
    for d in _dados(db, "concurso"):
        if (d.get("publicado") or "") < corte:
            continue
        x = {k: d.get(k) for k in ("titulo", "orgao", "vinculo", "esfera", "uf", "municipio", "tipo", "area", "publicado", "url", "fonte",
                                   "vagas", "salario_max", "inscricoes_inicio", "inscricoes_fim", "cargos", "banca", "escolaridade", "resumo")}
        x["situacao"] = ("inscrições encerradas" if x.get("inscricoes_fim") and x["inscricoes_fim"] < hoje else
                         "inscrições abertas" if x.get("inscricoes_inicio") and x["inscricoes_inicio"] <= hoje <= (x.get("inscricoes_fim") or hoje) else
                         "inscrições ainda não começaram" if x.get("inscricoes_inicio") and x["inscricoes_inicio"] > hoje else "ver edital")
        itens.append({k: v for k, v in x.items() if v not in (None, [], "")})
    if not itens:
        return None
    itens.sort(key=lambda x: x.get("publicado") or "", reverse=True)
    areas, esferas = defaultdict(int), defaultdict(int)
    for x in itens:
        areas[x.get("area") or "Outras áreas"] += 1
        esferas[x.get("esfera") or "?"] += 1
    return {"total": len(itens), "itens": itens, "areas": dict(sorted(areas.items(), key=lambda a: -a[1])), "esferas": dict(esferas),
            "periodo_dias": dias, "coleta": _ultima(db, "concursos"), "aviso": AVISO_CONCURSOS}


def cursos(db: Session) -> dict | None:
    itens = []
    for d in _dados(db, "curso"):
        x = {k: d.get(k) for k in ("nome", "ofertante", "quem_faz", "tema", "carga_horaria", "modalidade", "inscricoes_abertas", "certificado", "url", "resumo", "lancado")}
        if x.get("tema") and re.search(r"destaque|novidade|gratuit|mais vendid|lan[cç]amento|promo", x["tema"], re.I):
            x["tema"] = None
        if x.get("resumo"):
            x["resumo"] = x["resumo"][:140].rsplit(" ", 1)[0] + "…" if len(x["resumo"]) > 140 else x["resumo"]
        itens.append({k: v for k, v in x.items() if v not in (None, "")})
    if not itens:
        return None
    # os mais novos primeiro (a Escola Virtual informa o lançamento); sem data, em ordem alfabética
    itens.sort(key=lambda x: (not x.get("inscricoes_abertas", False), "" if x.get("lancado") else "1", "".join(chr(255 - ord(c)) for c in x.get("lancado") or ""), x.get("nome") or ""))
    temas, ofertantes = defaultdict(int), defaultdict(int)
    for x in itens:
        temas[x.get("tema") or "Outros"] += 1
        ofertantes[x.get("ofertante") or "?"] += 1
    return {"total": len(itens), "itens": itens, "temas": dict(sorted(temas.items(), key=lambda a: -a[1])), "ofertantes": dict(ofertantes),
            "onde_procurar": ONDE_PROCURAR, "coleta": _ultima(db, "cursos"), "aviso": AVISO_CURSOS}


_CAMPOS_EVENTO = ("artista", "evento", "data_evento", "municipio", "uf", "esfera", "orgao", "valor", "valor_tipo", "publicado", "url", "objeto")


def _evento(d: dict, objeto: int = 160) -> dict:
    """Formato enxuto: o texto do contrato só quando o artista não foi lido; o órgão só quando a esfera não é conhecida."""
    x = {k: d.get(k) for k in _CAMPOS_EVENTO if k != "publicado"}
    if x.get("artista"):
        x.pop("objeto", None)
    elif x.get("objeto"):
        x["objeto"] = x["objeto"][:objeto]
    if x.get("esfera"):
        x.pop("orgao", None)
    return {k: v for k, v in x.items() if v not in (None, "")}


def eventos(db: Session, uf: str | None = None) -> dict | None:
    todos = _dados(db, "evento_show", ("pncp",))
    if not todos:
        return None
    datas = sorted(d.get("publicado") for d in todos if d.get("publicado"))
    base = {"periodo": {"de": datas[0], "ate": datas[-1]} if datas else None, "coleta": _ultima(db, "eventos"), "aviso": AVISO_EVENTOS}
    if uf:
        sel = [d for d in todos if d.get("uf") == uf]
        cid = defaultdict(lambda: {"qtd": 0, "valor": 0.0})
        for d in sel:
            c = cid[d.get("municipio") or "(estado)"]
            c["qtd"] += 1
            c["valor"] += float(d.get("valor") or 0)
        itens = sorted((_evento(d) for d in sel), key=lambda x: -(x.get("valor") or 0))
        return {**base, "uf": uf, "total": len(itens), "valor_total": round(sum(x.get("valor") or 0 for x in itens), 2), "itens": itens,
                "cidades": sorted(({"municipio": k, **v} for k, v in cid.items()), key=lambda c: -c["valor"])}
    por_uf = {u: {"qtd": 0, "valor": 0.0} for u in UFS}
    por_esfera = defaultdict(lambda: {"qtd": 0, "valor": 0.0})
    cid = defaultdict(lambda: {"qtd": 0, "valor": 0.0})
    for d in todos:
        v = float(d.get("valor") or 0)
        if d.get("uf") in por_uf:
            por_uf[d["uf"]]["qtd"] += 1
            por_uf[d["uf"]]["valor"] += v
        por_esfera[d.get("esfera") or "?"]["qtd"] += 1
        por_esfera[d.get("esfera") or "?"]["valor"] += v
        if d.get("municipio"):
            c = cid[(d["municipio"], d.get("uf"))]
            c["qtd"] += 1
            c["valor"] += v
    hoje = date.today().isoformat()
    proximos = sorted((d for d in todos if (d.get("data_evento") or "") >= hoje), key=lambda d: d["data_evento"])[:60]
    return {**base, "total": len(todos), "valor_total": round(sum(float(d.get("valor") or 0) for d in todos), 2),
            "com_artista": sum(1 for d in todos if d.get("artista")), "cidades_total": len(cid), "por_uf": por_uf, "por_esfera": dict(por_esfera),
            "maiores": [_evento(d) for d in sorted(todos, key=lambda d: -float(d.get("valor") or 0))[:60]],
            "proximos": [_evento(d) for d in proximos],
            "cidades": [{"municipio": k[0], "uf": k[1], **v} for k, v in sorted(cid.items(), key=lambda a: -a[1]["valor"])[:60]]}


def patrocinios(db: Session, uf: str | None = None) -> dict | None:
    ps = _dados(db, "patrocinio", ("salic",))
    if not ps:
        return None
    if uf:
        ps = [p for p in ps if p.get("uf") == uf or any(str(l).endswith("/" + uf) for l in p.get("locais") or [])]
    emp = defaultdict(lambda: {"valor": 0.0, "projetos": 0})
    for p in ps:
        for s in p.get("patrocinadores") or []:
            if s.get("cnpj"):
                e = emp[s["nome"]]
                e["valor"] += float(s.get("valor") or 0)
                e["projetos"] += 1
    ps.sort(key=lambda p: -float(p.get("captado") or 0))
    return {"uf": uf, "total": len(ps), "captado_total": round(sum(float(p.get("captado") or 0) for p in ps), 2),
            "projetos": [{**{k: v for k, v in p.items() if k not in ("fonte", "tipologia")}, "locais": (p.get("locais") or [])[:8],
                          "patrocinadores": (p.get("patrocinadores") or [])[:8]} for p in ps[:400]],
            "empresas": [{"nome": k, **v} for k, v in sorted(emp.items(), key=lambda a: -a[1]["valor"])[:40]],
            "coleta": _ultima(db, "patrocinios"), "aviso": AVISO_PATROCINIO}
