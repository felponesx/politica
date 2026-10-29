"""Endpoints da versão 0.2: municípios, indicadores sociais, gastos por função, órgãos, dívidas,
cadastro de empresas, desastres e composição partidária."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (Contrato, Despesa, DevedorPGFN, EmpresaCadastro, IndicadorMunicipal, Municipio,
                        OcorrenciaDesastre, Parlamentar, Registro, ResultadoEleicao)
from app.routers.ligacoes import AVISO, resumo_fornecedor
from app.utils import UFS, formatar_documento, so_digitos, memo

router = APIRouter()


def _linha(obj, *excluir):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in ("atualizado_em", *excluir)}


def _uf(uf):
    if uf and uf.upper() not in UFS:
        raise HTTPException(404, "UF inválida")
    return uf.upper() if uf else None


# ---------- municípios ----------

@router.get("/municipios", tags=["Municípios"])
def municipios(uf: str | None = None, q: str | None = None, capag: str | None = None,
               ordenar: str = Query("nome", pattern="^(nome|populacao|pib)$"),
               limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0, le=1_000_000), db: Session = Depends(get_db)):
    stmt = select(Municipio)
    if uf:
        stmt = stmt.where(Municipio.uf == _uf(uf))
    if q:
        stmt = stmt.where(Municipio.nome.ilike(f"%{q}%"))
    if capag:
        stmt = stmt.where(Municipio.capag == capag.upper())
    col = {"nome": Municipio.nome, "populacao": Municipio.populacao.desc().nullslast(),
           "pib": Municipio.pib.desc().nullslast()}[ordenar]
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {"total": total, "itens": [_linha(m, "capag_detalhe") for m in db.scalars(stmt.order_by(col).limit(limit).offset(offset))]}


@router.get("/municipios/{codigo}", tags=["Municípios"])
def municipio(codigo: str, db: Session = Depends(get_db)):
    """Popout de cidade: dados do IBGE, CAPAG, indicadores sociais, desastres e contratos locais."""
    m = db.scalar(select(Municipio).where(Municipio.codigo_ibge == codigo))
    if not m and codigo.isdigit() and len(codigo) < 7:  # id interno (vindo da busca)
        m = db.get(Municipio, int(codigo))
        codigo = m.codigo_ibge if m else codigo
    if not m:
        raise HTTPException(404, "Município não encontrado. Rode a coleta ibge-municipios.")
    inds = db.scalars(select(IndicadorMunicipal).where(IndicadorMunicipal.codigo_ibge == codigo)
                      .order_by(IndicadorMunicipal.nome, IndicadorMunicipal.ano.desc())).all()
    ultimos = {}
    for i in inds:
        ultimos.setdefault(i.nome, {"nome": i.nome, "descricao": i.descricao, "ano": i.ano, "valor": i.valor,
                                    "unidade": i.unidade, "fonte": i.fonte})
    desastres = db.execute(select(OcorrenciaDesastre.tipo, func.count(), func.max(OcorrenciaDesastre.data))
                           .where(OcorrenciaDesastre.codigo_ibge == codigo)
                           .group_by(OcorrenciaDesastre.tipo).order_by(func.count().desc())).all()
    q, v = db.execute(select(func.count(), func.sum(Contrato.valor))
                      .where(Contrato.uf == m.uf, Contrato.municipio.ilike(m.nome))).one()
    return {"municipio": _linha(m), "indicadores": list(ultimos.values()),
            "desastres": [{"tipo": t, "ocorrencias": c, "ultima": d} for t, c, d in desastres],
            "contratos": {"quantidade": q, "total": round(v or 0, 2)}}


# ---------- indicadores sociais ----------

@router.get("/indicadores-sociais/nomes", tags=["Municípios"])
def indicadores_nomes(db: Session = Depends(get_db)):
    linhas = db.execute(select(IndicadorMunicipal.nome, func.max(IndicadorMunicipal.descricao),
                               func.max(IndicadorMunicipal.unidade), func.max(IndicadorMunicipal.ano),
                               func.count()).group_by(IndicadorMunicipal.nome)).all()
    return [{"nome": n, "descricao": d, "unidade": u, "ano": a, "municipios": c} for n, d, u, a, c in linhas]


@router.get("/indicadores-sociais", tags=["Municípios"])
def indicadores_sociais(nome: str, uf: str | None = None, ano: int | None = None,
                        db: Session = Depends(get_db)):
    """Valor mais recente (ou do `ano`) de um indicador em cada município, e a média por estado."""
    ano = ano or db.scalar(select(func.max(IndicadorMunicipal.ano)).where(IndicadorMunicipal.nome == nome))
    if not ano:
        raise HTTPException(404, "Indicador sem dados. Rode ibge-indicadores-sociais ou indicador-arquivo.")
    stmt = (select(IndicadorMunicipal, Municipio.nome, Municipio.populacao)
            .join(Municipio, Municipio.codigo_ibge == IndicadorMunicipal.codigo_ibge, isouter=True)
            .where(IndicadorMunicipal.nome == nome, IndicadorMunicipal.ano == ano))
    if uf:
        stmt = stmt.where(IndicadorMunicipal.uf == _uf(uf))
    linhas = db.execute(stmt).all()
    por_uf = {}
    for i, _, pop in linhas:
        if i.valor is None or not i.uf:
            continue
        a = por_uf.setdefault(i.uf, [0.0, 0.0])
        peso = pop or 1
        a[0] += i.valor * peso
        a[1] += peso
    d0 = linhas[0][0] if linhas else None
    return {"nome": nome, "ano": ano, "descricao": d0 and d0.descricao, "unidade": d0 and d0.unidade,
            "fonte": d0 and d0.fonte,
            "media_por_uf": {u: round(s / p, 3) for u, (s, p) in por_uf.items() if p},
            "municipios": sorted(({"codigo_ibge": i.codigo_ibge, "nome": nm, "uf": i.uf, "valor": i.valor}
                                  for i, nm, _ in linhas), key=lambda x: (x["valor"] is None, -(x["valor"] or 0)))[:1000]}


# ---------- gastos por função ----------

def _funcoes(db, esfera, uf, ano, municipio=None):
    return [r for r in _funcoes_todos(db, esfera, uf, municipio) if r.ano == ano]


@router.get("/gastos/entes", tags=["Gastos"])
def gastos_entes(db: Session = Depends(get_db)):
    linhas = db.execute(select(Registro.uf, Registro.ano, Registro.dados).where(Registro.tipo == "despesa_funcao")).all()
    out, municipais = {}, set()
    for uf, ano, d in linhas:
        if d.get("esfera") == "M":
            municipais.add(d.get("id_ente"))
            continue
        k = (d.get("esfera"), uf)
        e = out.setdefault(k, {"esfera": d.get("esfera"), "uf": uf, "ente": d.get("ente"), "anos": set()})
        e["anos"].add(ano)
    res = [{**e, "anos": sorted(e["anos"], reverse=True)} for e in out.values()]
    if municipais:
        res.append({"esfera": "M", "uf": None, "ente": "Prefeituras", "anos": [], "municipios": len(municipais)})
    return res


@router.get("/gastos/funcao", tags=["Gastos"])
def gastos_funcao(esfera: str = Query("U", pattern="^(U|E|C|M)$"), uf: str | None = None, ano: int | None = None,
                  municipio: str | None = None, db: Session = Depends(get_db)):
    """Despesa liquidada por função de governo (saúde, educação...). esfera U=União, E=estado, C=capital."""
    uf = _uf(uf)
    if esfera in ("E", "C") and not uf:
        raise HTTPException(422, "Informe a UF para estados e capitais.")
    if not ano:
        anos = sorted({r.ano for r in _funcoes_todos(db, esfera, uf, municipio)}, reverse=True)
        if not anos:
            raise HTTPException(404, "Sem dados. Rode a coleta siconfi-despesas-funcao.")
        ano = anos[0]
    rows = _funcoes(db, esfera, uf, ano, municipio)
    if not rows:
        raise HTTPException(404, "Sem dados para esse ente e ano.")
    itens = sorted(({"funcao": r.titulo, "liquidado": r.dados.get("liquidado"), "empenhado": r.dados.get("empenhado"),
                     "dotacao": r.dados.get("dotacao")} for r in rows), key=lambda x: -(x["liquidado"] or 0))
    return {"esfera": esfera, "uf": uf, "ano": ano, "ente": rows[0].dados.get("ente"),
            "bimestre": rows[0].dados.get("bimestre"), "total_liquidado": round(sum(i["liquidado"] or 0 for i in itens), 2),
            "funcoes": itens, "fonte": "SICONFI — RREO Anexo 02 (despesa por função)"}


def _funcoes_todos(db, esfera, uf, municipio=None):
    stmt = select(Registro).where(Registro.tipo == "despesa_funcao")
    if esfera == "M":
        if not municipio:
            raise HTTPException(422, "Informe o código IBGE do município.")
        stmt = stmt.where(Registro.chave.like(f"M-{int(municipio)}-%"))
    else:
        stmt = stmt.where(Registro.uf.is_(None)) if esfera == "U" else stmt.where(Registro.uf == uf)
    return [r for r in db.scalars(stmt) if (r.dados or {}).get("esfera") == esfera
            or (esfera == "M" and (r.dados or {}).get("esfera") in ("M", "C"))]


@router.get("/gastos/evolucao", tags=["Gastos"])
def gastos_evolucao(esfera: str = Query("U", pattern="^(U|E|C|M)$"), uf: str | None = None, funcao: str | None = None,
                    municipio: str | None = None, db: Session = Depends(get_db)):
    por_ano = {}
    for r in _funcoes_todos(db, esfera, _uf(uf), municipio):
        if funcao and r.titulo != funcao:
            continue
        por_ano[r.ano] = por_ano.get(r.ano, 0) + (r.dados.get("liquidado") or 0)
    return [{"ano": a, "liquidado": round(v, 2)} for a, v in sorted(por_ano.items())]


# ---------- órgãos federais ----------

def _gastos_orgaos(db, ano=None):
    stmt = select(Registro).where(Registro.fonte == "transparencia", Registro.tipo == "gasto_orgao")
    if ano:
        stmt = stmt.where(Registro.ano == ano)
    return db.scalars(stmt).all()


def _num(d, k):
    from app.utils import para_float
    return para_float((d or {}).get(k)) or 0.0


@router.get("/orgaos", tags=["Órgãos"])
def orgaos(q: str | None = None, ano: int | None = None, db: Session = Depends(get_db)):
    """Órgãos superiores do governo federal com empenhado, liquidado e pago no ano."""
    ano = ano or db.scalar(select(func.max(Registro.ano)).where(Registro.tipo == "gasto_orgao"))
    nomes = {r.chave: r.titulo for r in db.scalars(select(Registro).where(Registro.fonte == "transparencia",
                                                                          Registro.tipo == "orgao"))}
    sup = {}
    for r in _gastos_orgaos(db, ano):
        d = r.dados or {}
        cod = str(d.get("codigoOrgaoSuperior") or "")
        s = sup.setdefault(cod, {"codigo": cod, "nome": d.get("orgaoSuperior") or nomes.get(cod), "empenhado": 0.0,
                                 "liquidado": 0.0, "pago": 0.0, "orcamento_atualizado": 0.0, "vinculados": 0})
        for k in ("empenhado", "liquidado", "pago", "orcamento_atualizado"):
            s[k] += _num(d, k)
        s["vinculados"] += 1
    itens = list(sup.values())
    if not itens and nomes:  # só a lista (sem despesas coletadas ainda)
        itens = [{"codigo": c, "nome": n, "empenhado": None, "liquidado": None, "pago": None, "vinculados": None}
                 for c, n in nomes.items() if len(c) == 5 and c.endswith("000")]
    if q:
        itens = [i for i in itens if q.lower() in (i["nome"] or "").lower()]
    itens.sort(key=lambda i: -(i["pago"] or 0))
    return {"ano": ano, "total_pago": round(sum(i["pago"] or 0 for i in itens), 2),
            "total_orcamento": round(sum(i.get("orcamento_atualizado") or 0 for i in itens), 2), "itens": itens,
            "fonte": "Portal da Transparência (CGU) — orçamento e execução por órgão (arquivo de dados abertos)"}


@router.get("/emendas", tags=["Órgãos"])
def emendas(db: Session = Depends(get_db)):
    """Emendas parlamentares por ano: empenhado e pago (inclui restos a pagar pagos), por tipo, função, estado e autor."""
    regs = db.scalars(select(Registro).where(Registro.fonte == "transparencia", Registro.tipo == "emendas_ano")).all()
    if not regs:
        raise HTTPException(404, "Sem dados. Rode a coleta transparencia-emendas.")
    anos, detalhe = [], {}
    for r in sorted(regs, key=lambda r: r.ano or 0):
        d = r.dados or {}
        pago = _num(d, "pago") + _num(d, "restos_pagos")
        anos.append({"ano": r.ano, "empenhado": round(_num(d, "empenhado"), 2), "pago": round(pago, 2), "emendas": int(d.get("n") or 0)})
        lista = lambda k: [{"nome": n, **v} for n, v in (d.get(k) or {}).items()]
        detalhe[str(r.ano)] = {"empenhado": round(_num(d, "empenhado"), 2), "liquidado": round(_num(d, "liquidado"), 2), "pago": round(pago, 2),
                               "emendas": int(d.get("n") or 0), "tipos": lista("tipos"), "funcoes": lista("funcoes")[:12],
                               "ufs": {n: v for n, v in (d.get("ufs") or {}).items()}, "autores": lista("autores")[:10]}
    return {"anos": anos, "detalhe": detalhe, "fonte": "Portal da Transparência (CGU) — Emendas Parlamentares",
            "nota": ("Emendas são verbas do orçamento da União que deputados, senadores, bancadas e comissões indicam para obras e serviços. "
                     "\"Pago\" soma o que foi pago no ano e os restos a pagar pagos depois. O estado \"Múltiplo\" é quando a emenda atende vários estados; "
                     "\"Nacional\" e \"Exterior\" também aparecem. O ano em andamento ainda muda.")}


@router.get("/cartao-corporativo", tags=["Órgãos"])
def cartao_corporativo(db: Session = Depends(get_db)):
    """Cartão de Pagamento do Governo Federal (cartão corporativo): total por ano e, em cada ano, compras, saques, meses, órgãos e maiores favorecidos."""
    regs = db.scalars(select(Registro).where(Registro.fonte == "transparencia", Registro.tipo == "cartao_mes")).all()
    if not regs:
        raise HTTPException(404, "Sem dados. Rode a coleta transparencia-cartao.")
    por_ano: dict[int, list] = {}
    for r in regs:
        por_ano.setdefault(r.ano, []).append(r.dados or {})
    anos, detalhe = [], {}
    for ano, meses in sorted(por_ano.items()):
        meses.sort(key=lambda d: d.get("mes") or 0)
        total = sum(_num(m, "total") for m in meses)
        saques = sum(_num(m, "saques") for m in meses)
        orgs, favs = {}, {}
        for m in meses:
            for k, v in (m.get("orgaos") or {}).items():
                orgs[k] = orgs.get(k, 0.0) + (v or 0)
            for f in m.get("favorecidos") or []:
                x = favs.setdefault(f["cnpj"], {"cnpj": f["cnpj"], "nome": f.get("nome"), "valor": 0.0, "compras": 0})
                x["valor"] += f.get("valor") or 0
                x["compras"] += f.get("compras") or 0
        anos.append({"ano": ano, "total": round(total, 2), "meses": len(meses)})
        detalhe[str(ano)] = {
            "total": round(total, 2), "saques": round(saques, 2), "compras": round(total - saques, 2),
            "transacoes": sum(int(m.get("transacoes") or 0) for m in meses), "meses": len(meses),
            "por_mes": [{"mes": m.get("mes"), "total": _num(m, "total")} for m in meses],
            "orgaos": [{"nome": k, "valor": round(v, 2)} for k, v in sorted(orgs.items(), key=lambda x: -x[1])[:10]],
            "favorecidos": [{**f, "valor": round(f["valor"], 2)} for f in sorted(favs.values(), key=lambda x: -x["valor"])[:10]]}
    return {"anos": anos, "detalhe": detalhe, "fonte": "Portal da Transparência (CGU) — Cartão de Pagamento do Governo Federal",
            "nota": ("Gastos feitos com o cartão corporativo por servidores do governo federal. A lista de favorecidos mostra só empresas (CNPJ); "
                     "os valores por empresa vêm de cada mês, então uma empresa fora do topo 40 de algum mês pode ter total maior. O ano em andamento ainda muda.")}


@router.get("/cortes", tags=["Órgãos"])
def cortes(db: Session = Depends(get_db)):
    return memo(("cortes",), lambda: _cortes(db=db))


def _cortes(db: Session):
    """Cortes no orçamento federal: quanto o orçamento atualizado de cada órgão ficou abaixo do aprovado na lei orçamentária (inicial),
    por ano, e a parte de cada órgão superior (ministério, tribunal…) no total cortado."""
    por_ano: dict[int, dict] = {}
    for r in _gastos_orgaos(db):
        d = r.dados or {}
        ini, atu = _num(d, "orcamento_inicial"), _num(d, "orcamento_atualizado")
        if r.ano is None or ini <= 0:
            continue
        a = por_ano.setdefault(r.ano, {"inicial": 0.0, "atualizado": 0.0, "cortado": 0.0, "ampliado": 0.0, "sup": {}})
        a["inicial"] += ini
        a["atualizado"] += atu
        dif = ini - atu
        a["cortado" if dif > 0 else "ampliado"] += abs(dif)
        cod = str(d.get("codigoOrgaoSuperior") or "")
        sp = a["sup"].setdefault(cod, {"codigo": cod, "nome": d.get("orgaoSuperior") or "Sem órgão superior", "inicial": 0.0, "atualizado": 0.0, "cortado": 0.0})
        sp["inicial"] += ini
        sp["atualizado"] += atu
        if dif > 0:
            sp["cortado"] += dif
    if not por_ano:
        raise HTTPException(404, "Sem dados. Rode a coleta transparencia-orcamento.")
    anos, itens = [], {}
    for ano, a in sorted(por_ano.items()):
        anos.append({"ano": ano, "inicial": round(a["inicial"], 2), "atualizado": round(a["atualizado"], 2), "cortado": round(a["cortado"], 2),
                     "ampliado": round(a["ampliado"], 2), "percentual": round(a["cortado"] / a["inicial"] * 100, 2) if a["inicial"] else None})
        lista = sorted((x for x in a["sup"].values() if x["cortado"] > 0), key=lambda x: -x["cortado"])
        itens[str(ano)] = [{"codigo": x["codigo"], "nome": x["nome"], "inicial": round(x["inicial"], 2), "atualizado": round(x["atualizado"], 2),
                            "cortado": round(x["cortado"], 2), "percentual_do_corte": round(x["cortado"] / a["cortado"] * 100, 2),
                            "percentual_do_orcamento": round(x["cortado"] / x["inicial"] * 100, 2) if x["inicial"] else None} for x in lista]
    return {"anos": anos, "itens": itens, "fonte": "Portal da Transparência (CGU) — orçamento da despesa por órgão",
            "nota": ("Corte = quando o orçamento atualizado de um órgão ficou menor do que o aprovado na lei orçamentária (orçamento inicial). Vale para o órgão como um todo "
                     "e some os órgãos que perderam verba; os que ganharam (crédito extra) ficam em \"ampliado\". Não separa bloqueio temporário (contingenciamento) "
                     "de cancelamento definitivo. O ano em andamento ainda pode mudar.")}


@router.get("/orgaos/{codigo}", tags=["Órgãos"])
def orgao(codigo: str, db: Session = Depends(get_db)):
    linhas = [r for r in _gastos_orgaos(db) if str((r.dados or {}).get("codigoOrgaoSuperior")) == codigo
              or str((r.dados or {}).get("codigoOrgao")) == codigo]
    nome = db.scalar(select(Registro.titulo).where(Registro.tipo == "orgao", Registro.chave == codigo))
    if not linhas and not nome:
        raise HTTPException(404, "Órgão não encontrado. Rode transparencia-orgaos e transparencia-gastos-todos.")
    por_ano, vinc, funcoes = {}, {}, {}
    ultimo = max((r.ano for r in linhas), default=None)
    for r in linhas:
        d = r.dados or {}
        a = por_ano.setdefault(r.ano, {"ano": r.ano, "empenhado": 0.0, "liquidado": 0.0, "pago": 0.0,
                                       "orcamento_atualizado": 0.0})
        for k in ("empenhado", "liquidado", "pago", "orcamento_atualizado"):
            a[k] += _num(d, k)
        if r.ano == ultimo:
            vinc[str(d.get("codigoOrgao"))] = {"codigo": str(d.get("codigoOrgao")), "nome": d.get("orgao"),
                                               "pago": _num(d, "pago"), "empenhado": _num(d, "empenhado"),
                                               "orcamento_atualizado": _num(d, "orcamento_atualizado")}
            for f, v in (d.get("funcoes") or {}).items():
                funcoes[f] = funcoes.get(f, 0.0) + (v or 0)
        nome = nome or d.get("orgaoSuperior")
    return {"codigo": codigo, "nome": nome, "por_ano": sorted(por_ano.values(), key=lambda x: x["ano"]),
            "vinculados": sorted(vinc.values(), key=lambda x: -x["pago"]), "ano_vinculados": ultimo,
            "funcoes": [{"funcao": f, "pago": round(v, 2)} for f, v in sorted(funcoes.items(), key=lambda x: -x[1])],
            "fonte": "Portal da Transparência (CGU)"}


# ---------- dívidas ----------

@router.get("/dividas/familias-estados", tags=["Dívidas"])
def dividas_familias_estados(db: Session = Depends(get_db)):
    """Dívida de pessoas e empresas com bancos e inadimplência (atraso acima de 90 dias), por estado (SCR.data)."""
    regs = db.scalars(select(Registro).where(Registro.fonte == "bcb", Registro.tipo == "scr_uf")).all()
    if not regs:
        raise HTTPException(404, "Sem dados. Rode a coleta bcb-scr-estados.")
    ref = max((r.dados or {}).get("referencia") or "" for r in regs)
    estados = {r.uf: {k: (r.dados or {}).get(k) for k in ("pf", "pj")} for r in regs
               if (r.dados or {}).get("referencia") == ref}
    tot = {}
    for e in estados.values():
        for k in ("pf", "pj"):
            if e.get(k):
                t = tot.setdefault(k, {"carteira": 0.0, "inadimplida": 0.0})
                t["carteira"] += e[k]["carteira"] or 0
                t["inadimplida"] += e[k]["inadimplida"] or 0
    for t in tot.values():
        t["inadimplencia"] = round(100 * t["inadimplida"] / t["carteira"], 2) if t["carteira"] else None
    # histórico para os gráficos em linha: último mês coletado de cada ano, inadimplência das pessoas por estado
    ult = {}
    for r in regs:
        rf = str((r.dados or {}).get("referencia") or "")
        if rf[:4].isdigit() and rf > ult.get(rf[:4], ""):
            ult[rf[:4]] = rf
    hist = {}
    for r in regs:
        d = r.dados or {}
        rf = str(d.get("referencia") or "")
        if r.uf and ult.get(rf[:4]) == rf and (d.get("pf") or {}).get("inadimplencia") is not None:
            hist.setdefault(r.uf, {})[rf[:4]] = d["pf"]["inadimplencia"]
    return {"referencia": ref, "estados": estados, "brasil": tot,
            "historico": {"anos": sorted(ult), "estados": hist, "meses": ult},
            "fonte": "Banco Central do Brasil — SCR.data (Sistema de Informações de Créditos)",
            "nota": "Carteira ativa: tudo o que as pessoas (ou empresas) do estado devem aos bancos. Inadimplência: "
                    "parte com atraso acima de 90 dias."}


@router.get("/dividas/estados", tags=["Dívidas"])
def dividas_estados(db: Session = Depends(get_db)):
    """Dívida ativa da União por estado (pessoas físicas e empresas) + dívida consolidada dos governos estaduais."""
    from app.routers.dados import _divida_estado
    regs = db.scalars(select(Registro).where(Registro.tipo == "divida_ativa_uf")).all()
    ref = max(((r.dados or {}).get("referencia") or "" for r in regs), default=None)
    est = {uf: {"uf": uf, "pf": {"inscricoes": 0, "valor": 0.0}, "pj": {"inscricoes": 0, "valor": 0.0},
                "por_tipo": {}, "total": 0.0} for uf in UFS}
    for r in regs:
        d = r.dados or {}
        if d.get("referencia") != ref or r.uf not in est:
            continue
        e = est[r.uf]
        p = e["pj" if d.get("pessoa") == "PJ" else "pf"]
        p["inscricoes"] += d.get("inscricoes") or 0
        p["valor"] += r.valor or 0
        e["por_tipo"][d.get("tipo_divida")] = e["por_tipo"].get(d.get("tipo_divida"), 0) + (r.valor or 0)
        e["total"] += r.valor or 0
    for uf, e in est.items():
        e["governo_estadual"] = _divida_estado(db, uf)
    return {"referencia": ref, "estados": list(est.values()),
            "fonte": "PGFN (dívida ativa da União) e SICONFI RGF Anexo 02 (dívida dos estados)",
            "nota": "Inclui só o devedor principal de cada inscrição. Pessoas físicas aparecem apenas em totais."}


@router.get("/dividas/devedores", tags=["Dívidas"])
def dividas_devedores(uf: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=1_000_000),
                      db: Session = Depends(get_db)):
    """Maiores empresas devedoras da União (somando os tipos de dívida da referência mais recente)."""
    ref = db.scalar(select(func.max(DevedorPGFN.referencia)))
    if not ref:
        return {"referencia": None, "total": 0, "itens": [], "aviso": AVISO}
    stmt = (select(DevedorPGFN.cnpj, func.max(DevedorPGFN.nome), func.max(DevedorPGFN.uf), func.sum(DevedorPGFN.inscricoes),
                   func.sum(DevedorPGFN.valor), func.sum(DevedorPGFN.valor_ajuizado))
            .where(DevedorPGFN.referencia == ref).group_by(DevedorPGFN.cnpj))
    if uf:
        stmt = stmt.where(DevedorPGFN.uf == _uf(uf))
    if q:
        dig = so_digitos(q)
        stmt = stmt.where(or_(DevedorPGFN.nome.ilike(f"%{q}%"), DevedorPGFN.cnpj == dig) if dig else DevedorPGFN.nome.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    linhas = db.execute(stmt.order_by(func.sum(DevedorPGFN.valor).desc()).limit(limit).offset(offset)).all()
    return {"referencia": ref, "total": total, "aviso": "Estar inscrito na dívida ativa não significa condenação; "
            "o débito pode estar parcelado, garantido ou em discussão judicial.",
            "itens": [{"cnpj": c, "documento": formatar_documento(c), "nome": n, "uf": u, "inscricoes": i,
                       "valor": round(v or 0, 2), "valor_ajuizado": round(a or 0, 2)} for c, n, u, i, v, a in linhas]}


@router.get("/dividas/municipios", tags=["Dívidas"])
def dividas_municipios(uf: str | None = None, db: Session = Depends(get_db)):
    """Distribuição da nota CAPAG (capacidade de pagamento) dos municípios."""
    stmt = select(Municipio.uf, Municipio.capag, func.count()).where(Municipio.capag.isnot(None))
    if uf:
        stmt = stmt.where(Municipio.uf == _uf(uf))
    dist = {}
    for u, c, n in db.execute(stmt.group_by(Municipio.uf, Municipio.capag)):
        dist.setdefault(u, {})[c] = n
    ano = db.scalar(select(func.max(Municipio.capag_ano)))
    hist = {r.ano: (r.dados or {}).get("por_uf") or {} for r in db.scalars(
        select(Registro).where(Registro.fonte == "tesouro", Registro.tipo == "capag_resumo")) if r.ano}
    if ano and not uf:
        hist[ano] = dist
    if uf:
        hist = {a: {u: d for u, d in v.items() if u == _uf(uf)} for a, v in hist.items()}
    return {"ano": ano, "por_uf": dist, "historico": {str(a): hist[a] for a in sorted(hist)}, "fonte": "Tesouro Nacional — CAPAG dos municípios",
            "legenda": {"A": "boa capacidade de pagamento", "B": "boa", "C": "fraca", "D": "muito fraca",
                        "n.d.": "não avaliado (dados incompletos)"}}


# ---------- empresas (cadastro CNPJ + dívida ativa + contratos) ----------

@router.get("/empresas/{documento:path}", tags=["Empresas"])
def empresa(documento: str, db: Session = Depends(get_db)):
    cnpj = so_digitos(documento)
    if not cnpj or len(cnpj) != 14:
        raise HTTPException(422, "Informe um CNPJ com 14 dígitos.")
    cad = db.scalar(select(EmpresaCadastro).where(EmpresaCadastro.cnpj == cnpj))
    cad_dict = _linha(cad) if cad else None
    nas_bases = db.scalar(select(func.count()).select_from(Contrato).where(Contrato.cnpj_fornecedor == cnpj)) or \
        db.scalar(select(func.count()).select_from(Despesa).where(Despesa.cnpj_cpf == cnpj)) or \
        db.scalar(select(func.count()).select_from(DevedorPGFN).where(DevedorPGFN.cnpj == cnpj))
    if not cad and settings.cnpj_sob_demanda and nas_bases:
        from app.collectors.cnpj import consultar
        cad = consultar(db, cnpj)
        if cad:
            db.flush()
            cad_dict = _linha(cad)
            try:
                db.commit()
            except Exception:  # API com usuário só de leitura: mostra o cadastro sem gravar
                db.rollback()
    divida = db.scalars(select(DevedorPGFN).where(DevedorPGFN.cnpj == cnpj).order_by(DevedorPGFN.referencia.desc())).all()
    ref = divida[0].referencia if divida else None
    if not cad_dict and not nas_bases:
        raise HTTPException(404, "CNPJ não aparece nas bases coletadas.")
    return {"documento": formatar_documento(cnpj), "cadastro": cad_dict,
            "divida_ativa": [{"tipo": d.tipo_divida, "inscricoes": d.inscricoes, "valor": d.valor,
                              "valor_ajuizado": d.valor_ajuizado, "referencia": d.referencia}
                             for d in divida if d.referencia == ref],
            **resumo_fornecedor(db, cnpj), "aviso": AVISO,
            "fonte": "Receita Federal (CNPJ, via BrasilAPI), PGFN, PNCP e Câmara dos Deputados"}


# ---------- saneamento ----------

@router.get("/saneamento", tags=["Estados"])
def saneamento(db: Session = Depends(get_db)):
    """Água, esgoto, lixo e luz por estado (Censo 2022 e PNAD): % e número de pessoas com e sem o serviço."""
    linhas = db.scalars(select(Registro).where(Registro.fonte == "ibge", Registro.tipo == "saneamento")).all()
    if not linhas:
        raise HTTPException(404, "Sem dados. Rode a coleta ibge-saneamento.")
    return {"por_uf": {r.uf: r.dados for r in linhas}, "ano": 2022,
            "metodologia": "Água, esgoto e lixo: Censo 2022 (domicílios com rede geral/fossa ligada à rede/coleta). Luz: PNAD Contínua "
                           "(moradores com energia elétrica). Pessoas = % × população do Censo 2022 do estado (estimativa).",
            "fonte": "IBGE"}


# ---------- desastres ----------

@router.get("/riscos", tags=["Municípios"])
def riscos(uf: str | None = None, anos: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    """Desastres reconhecidos nos últimos `anos`: por município e por tipo."""
    corte = date(date.today().year - anos, 1, 1)
    stmt = select(OcorrenciaDesastre).where(or_(OcorrenciaDesastre.data.is_(None), OcorrenciaDesastre.data >= corte))
    if uf:
        stmt = stmt.where(OcorrenciaDesastre.uf == _uf(uf))
    por_mun, por_tipo, por_uf = {}, {}, {}
    for o in db.scalars(stmt):
        k = o.codigo_ibge or f"{o.municipio}-{o.uf}"
        m = por_mun.setdefault(k, {"codigo_ibge": o.codigo_ibge, "municipio": o.municipio, "uf": o.uf,
                                   "ocorrencias": 0, "tipos": {}, "ultima": None})
        m["ocorrencias"] += 1
        m["tipos"][o.tipo] = m["tipos"].get(o.tipo, 0) + 1
        if o.data and (not m["ultima"] or o.data > m["ultima"]):
            m["ultima"] = o.data
        por_tipo[o.tipo] = por_tipo.get(o.tipo, 0) + 1
        if o.uf:
            por_uf[o.uf] = por_uf.get(o.uf, 0) + 1
    if por_mun:
        nomes = {m.codigo_ibge: m.nome for m in db.scalars(select(Municipio).where(
            Municipio.codigo_ibge.in_([k for k in por_mun if k and k.isdigit()])))}
        for m in por_mun.values():
            m["municipio"] = m["municipio"] or nomes.get(m["codigo_ibge"])
    return {"desde": corte, "por_uf": por_uf,
            "por_tipo": dict(sorted(por_tipo.items(), key=lambda x: -x[1])),
            "municipios": sorted(por_mun.values(), key=lambda m: -m["ocorrencias"])[:500],
            "fonte": "Defesa Civil Nacional (S2ID / Atlas Digital de Desastres)"}


# ---------- composição partidária ----------

def _eleitos_por_partido(db, cargos):
    # quem está no cargo: a eleição mais recente cujo mandato já começou (os eleitos em outubro tomam posse
    # no ano seguinte); sem ela, a mais recente que houver
    filtro = [ResultadoEleicao.cargo.in_(cargos), ResultadoEleicao.eleito]
    ano = (db.scalar(select(func.max(ResultadoEleicao.ano)).where(*filtro, ResultadoEleicao.ano < date.today().year))
           or db.scalar(select(func.max(ResultadoEleicao.ano)).where(*filtro)))
    if not ano:
        return None
    linhas = db.execute(select(ResultadoEleicao.uf, ResultadoEleicao.partido, func.count(distinct(ResultadoEleicao.sq_candidato)))
                        .where(ResultadoEleicao.ano == ano, ResultadoEleicao.cargo.in_(cargos), ResultadoEleicao.eleito)
                        .group_by(ResultadoEleicao.uf, ResultadoEleicao.partido)).all()
    tot, por_uf = {}, {}
    for uf, p, n in linhas:
        tot[p or "?"] = tot.get(p or "?", 0) + n
        por_uf.setdefault(uf, {})[p or "?"] = n
    return {"ano": ano, "partidos": dict(sorted(tot.items(), key=lambda x: -x[1])), "por_uf": por_uf,
            "ufs_com_dados": sorted(por_uf), "fonte": "TSE — candidatos eleitos"}


@router.get("/partidos/composicao", tags=["Partidos"])
def composicao(db: Session = Depends(get_db)):
    """Cadeiras por partido: Câmara e Senado (mandatos em exercício), Assembleias, governadores e prefeitos (TSE)."""
    def casa(c):
        linhas = db.execute(select(Parlamentar.uf, Parlamentar.partido, func.count())
                            .where(Parlamentar.casa == c, Parlamentar.em_exercicio)
                            .group_by(Parlamentar.uf, Parlamentar.partido)).all()
        if not linhas:
            return None
        tot, por_uf = {}, {}
        for uf, p, n in linhas:
            tot[p or "S/PARTIDO"] = tot.get(p or "S/PARTIDO", 0) + n
            por_uf.setdefault(uf, {})[p or "S/PARTIDO"] = n
        return {"partidos": dict(sorted(tot.items(), key=lambda x: -x[1])), "por_uf": por_uf,
                "fonte": "Câmara dos Deputados" if c == "camara" else "Senado Federal"}
    return {"camara": casa("camara"), "senado": casa("senado"),
            "assembleia": _eleitos_por_partido(db, ["DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL"]),
            "governador": _eleitos_por_partido(db, ["GOVERNADOR"]),
            "prefeito": _eleitos_por_partido(db, ["PREFEITO"]),
            "presidente": _eleitos_por_partido(db, ["PRESIDENTE"])}


SETORES_ECO = {"industria": "Indústria", "construcao": "Construção", "comercio": "Comércio", "servicos": "Serviços"}


@router.get("/economia-empresas", tags=["Empresas"])
def empresas_economia(db: Session = Depends(get_db)):
    return memo(("econ",), lambda: _empresas_economia(db=db))


def _setor_financeiro(d: dict) -> dict | None:
    """Setor financeiro (IF.data do Banco Central): mesmas contas do quadro dos outros setores, por instituição, mais os grandes números do crédito."""
    t, n = d.get("totais") or {}, d.get("instituicoes") or 0
    rec = t.get("receita") or 0
    if not n or rec <= 0:
        return None
    lucro, cap, per, pes, adm = (t.get(k) or 0 for k in ("lucro", "captacao", "perdas", "pessoal", "administracao"))
    outras = rec - lucro - cap - per - pes - adm  # o que sobra da receita depois das despesas listadas (inclui outras despesas)
    pc = lambda v: round(v / rec * 100, 1)  # noqa: E731
    fatias = [("Juros pagos a quem deposita e empresta", pc(cap)), ("Calotes e provisões (perdas com crédito)", pc(per)), ("Pessoal", pc(pes)),
              ("Administração e impostos", pc(adm)), ("Outras despesas", pc(outras)), ("Sobra (lucro)", pc(lucro))]
    return {"chave": "financeiro", "nome": "Financeiro (bancos e crédito)", "empresas": n, "pessoal": None, "receita": rec,
            "receita_media": rec / n, "pessoal_medio": None, "gasto_medio": (rec - lucro) / n, "custo_por_pessoa": None,
            "partes": {"insumos": pc(cap + per + adm + outras), "pessoal": pc(pes), "sobra": pc(lucro)}, "margem": pc(lucro), "fatias": fatias,
            "referencia": d.get("referencia"), "totais": t, "maiores": d.get("maiores") or [], "series": d.get("series") or {},
            "fonte": "Banco Central do Brasil — IF.data (balanços e resultados) e SGS (crédito)",
            "nota": ("Soma dos conglomerados prudenciais e instituições independentes (bancos, cooperativas de crédito, financeiras e outras). A receita junta o que "
                     "ganham com crédito, títulos, serviços, tarifas e pagamentos; \"juros pagos\" é o custo do dinheiro captado de clientes e investidores. "
                     "Resultado do ano somando os dois semestres; valores em reais.")}


def _empresas_economia(db: Session):
    """Como é a economia das empresas: faturamento médio, para onde vai a receita e quanto sobra, por setor (IBGE)."""
    r = db.scalar(select(Registro).where(Registro.fonte == "ibge", Registro.tipo == "empresas_economia")
                  .order_by(Registro.ano.desc()))
    if not r:
        raise HTTPException(404, "Sem dados. Rode a coleta ibge-empresas-economia.")
    bruto = (r.dados or {}).get("setores") or {}

    def derivar(d):
        emp, rec, pes = d.get("empresas") or 0, d.get("receita") or 0, d.get("pessoal") or 0
        gp, va = d.get("gastos_pessoal") or 0, d.get("valor_adicionado") or 0
        if not emp or not rec:
            return None
        insumos = max(rec - va, 0)
        sobra = va - gp
        return {"empresas": emp, "pessoal": pes, "receita": rec, "valor_adicionado": va, "gastos_pessoal": gp,
                "receita_media": rec / emp, "pessoal_medio": pes / emp, "gasto_medio": (insumos + gp) / emp,
                "pessoal_medio_gasto": gp / emp, "custo_por_pessoa": gp / pes if pes else None,
                "partes": {"insumos": round(insumos / rec * 100, 1), "pessoal": round(gp / rec * 100, 1),
                           "sobra": round(sobra / rec * 100, 1)},
                "margem": round(sobra / rec * 100, 1), "taxa_margem_comercializacao": d.get("taxa_margem")}

    setores = {k: x for k, v in bruto.items() if (x := derivar(v))}
    soma = {c: sum(x[c] for x in setores.values()) for c in ("empresas", "pessoal", "receita", "valor_adicionado", "gastos_pessoal")}
    total = derivar({"empresas": soma["empresas"], "pessoal": soma["pessoal"], "receita": soma["receita"],
                     "valor_adicionado": soma["valor_adicionado"], "gastos_pessoal": soma["gastos_pessoal"]}) if setores else None
    fin = db.scalar(select(Registro).where(Registro.fonte == "bcb", Registro.tipo == "financeiro", Registro.chave == "sistema"))
    return {"ano": (r.dados or {}).get("ano"), "setores": [{"chave": k, "nome": SETORES_ECO.get(k, k), **v} for k, v in setores.items()],
            "financeiro": _setor_financeiro(fin.dados) if fin and fin.dados else None,
            "total": total, "fonte": "IBGE — Pesquisa Industrial Anual, Pesquisa Anual da Indústria da Construção, Pesquisa Anual de Comércio e Pesquisa Anual de Serviços",
            "nota": ("Totais do país por setor, não por empresa (o faturamento de cada empresa não é público). Cobre indústria, construção, comércio e serviços "
                     "não financeiros; fora fica a agropecuária; o setor financeiro (bancos e crédito) vem do Banco Central e aparece em linha separada. \"Sobra\" = valor adicionado menos gastos com pessoal, em % da receita: é a margem "
                     "operacional bruta, antes de impostos sobre o lucro, juros e depreciação; não é o lucro líquido. \"Gasto\" = compras de insumos e "
                     "mercadorias mais gastos com pessoal. No comércio a conta de pessoal considera só salários e retiradas.")}


@router.get("/resumo-contratos", tags=["Contratos"])
def contratos_resumo(db: Session = Depends(get_db)):
    return memo(("ctres",), lambda: _contratos_resumo(db=db))


def _contratos_resumo(db: Session):
    """Quanto o poder público gasta em contratos: total, média, mediana, por esfera e por faixa de valor."""
    valores = sorted(v for (v,) in db.execute(select(Contrato.valor).where(Contrato.valor.isnot(None), Contrato.valor > 0)))
    if not valores:
        raise HTTPException(404, "Sem contratos coletados.")
    n = len(valores)
    esf = {"F": "Federal", "E": "Estadual", "M": "Municipal"}
    por_esfera = [{"esfera": k, "nome": esf.get(k or "", "Não informada"), "contratos": q, "valor": round(v or 0, 2),
                   "media": round((v or 0) / q, 2)} for k, q, v in db.execute(
        select(Contrato.esfera, func.count(), func.sum(Contrato.valor)).where(Contrato.valor > 0).group_by(Contrato.esfera))]
    faixas = [("Até R$ 10 mil", 0, 1e4), ("R$ 10 mil a 100 mil", 1e4, 1e5), ("R$ 100 mil a 1 milhão", 1e5, 1e6),
              ("R$ 1 a 10 milhões", 1e6, 1e7), ("Acima de R$ 10 milhões", 1e7, float("inf"))]
    por_faixa = []
    for nome, lo, hi in faixas:
        sel = [v for v in valores if lo <= v < hi]
        por_faixa.append({"faixa": nome, "contratos": len(sel), "valor": round(sum(sel), 2)})
    return {"contratos": n, "valor_total": round(sum(valores), 2), "media": round(sum(valores) / n, 2),
            "mediana": round(valores[n // 2], 2), "maior": round(valores[-1], 2), "por_esfera": por_esfera, "por_faixa": por_faixa,
            "nota": "Contratos já coletados do PNCP e do Portal da Transparência: é uma amostra, não o total dos contratos do país."}


@router.get("/dividas/empresas", tags=["Dívidas", "Empresas"])
def dividas_empresas(db: Session = Depends(get_db)):
    """Empresas ativas do país por porte (MEI, ME, EPP, demais) e quantas têm dívida com a União, estão em recuperação
    judicial ou falidas; as 300 que mais devem à União e as 300 de maior capital social (com o que devem)."""
    r = db.scalars(select(Registro).where(Registro.fonte == "receita", Registro.tipo == "empresas_porte")
                   .order_by(Registro.chave.desc())).first()
    if not r:
        raise HTTPException(404, "Sem dados. Rode a coleta receita-empresas-porte.")
    d = dict(r.dados or {})
    p = d.get("por_porte") or {}
    tot = {k: sum((v or {}).get(k, 0) for v in p.values()) for k in ("total", "com_divida", "recuperacao_judicial", "falidas", "divida_total")}
    return {**d, "todas": tot,
            "fonte": "Receita Federal (cadastro do CNPJ, mês " + str(d.get("mes_cnpj")) + ") e PGFN (dívida ativa da União, "
                     + str(d.get("pgfn_referencia")) + ")",
            "nota": "Só empresas ativas (matriz). Dívida = inscrição na dívida ativa da União (tributos federais, previdência e "
                    "FGTS) como devedora principal, de qualquer valor; dívidas com bancos, fornecedores, estados e prefeituras "
                    "não entram. A Receita não separa média de grande empresa: as duas estão em \"Demais\". MEI conta à parte "
                    "(optantes do SIMEI). Recuperação judicial e falência pela situação especial do CNPJ.",
            "aviso": "Estar na dívida ativa não é crime nem irregularidade: é dívida cobrada pela União, que pode estar "
                     "parcelada, garantida ou sendo contestada na Justiça."}
