import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DoacaoEmpresa as D
from app.utils import memo

AVISO = ("Doações de campanha feitas por quem tem CNPJ (empresas, partidos e comitês), somadas por candidatura e origem do recurso, segundo a prestação de contas ao TSE. "
         "Empresas foram proibidas de doar em 2015: de 2002 a 2014 são doações eleitorais históricas; de 2018 em diante os CNPJ são partidos, comitês e fundos. "
         "Em 2002 o arquivo não diz a origem (tipo 'cnpj_sem_tipo'). CPFs de pessoas físicas não são guardados. Aparecer como doador não indica irregularidade. "
         "O mesmo dinheiro pode aparecer duas vezes se passou por um comitê antes de chegar ao candidato; por isso o total de 'empresa' é o mais confiável.")
router = APIRouter()


@router.get("/doadores", tags=["Eleições"])
def resumo(db: Session = Depends(get_db)):
    """Por eleição: quantas empresas doaram, para quantas candidaturas e quanto, separando empresa de partido/comitê."""
    def monta():
        q = (select(D.ano, D.tipo_doador, func.count(func.distinct(D.cnpj)), func.count(func.distinct(D.sq_candidato)), func.sum(D.valor), func.sum(D.n_doacoes), func.max(D.coletado_em))
             .group_by(D.ano, D.tipo_doador).order_by(D.ano.desc()))
        return [{"ano": a, "tipo_doador": t, "doadores": c, "candidaturas": k, "valor": round(v or 0, 2), "doacoes": n, "coletado_em": e} for a, t, c, k, v, n, e in db.execute(q)]
    linhas = memo(("doadores",), monta)
    if not linhas:
        raise HTTPException(404, "Sem dados de doadores. Rode a coleta tse-doadores.")
    return {"eleicoes": linhas, "aviso": AVISO, "fonte": "TSE — prestação de contas de candidatos"}


@router.get("/doadores/empresas", tags=["Eleições"])
def maiores(ano: int, tipo: str = "empresa", q: str | None = None, limit: int = Query(30, le=200), db: Session = Depends(get_db)):
    """Maiores doadores com CNPJ de uma eleição (ou busca por razão social/CNPJ)."""
    stmt = (select(D.cnpj, func.max(D.doador), func.count(func.distinct(D.sq_candidato)), func.count(func.distinct(D.partido)), func.sum(D.valor))
            .where(D.ano == ano, D.tipo_doador == tipo).group_by(D.cnpj).order_by(func.sum(D.valor).desc()).limit(limit))
    if q:
        dig = re.sub(r"\D", "", q)
        stmt = stmt.where(D.cnpj.like(f"{dig}%") if len(dig) >= 6 else D.doador.ilike(f"%{q}%"))
    return {"ano": ano, "tipo_doador": tipo, "aviso": AVISO,
            "doadores": [{"cnpj": c, "nome": n, "candidaturas": k, "partidos": p, "valor": round(v or 0, 2)} for c, n, k, p, v in db.execute(stmt)]}


@router.get("/doadores/empresas/{cnpj}", tags=["Eleições"])
def empresa(cnpj: str, db: Session = Depends(get_db)):
    """Quanto o CNPJ doou em cada eleição, por partido e para quais candidaturas."""
    c = re.sub(r"\D", "", cnpj)
    linhas = db.scalars(select(D).where(D.cnpj == c).order_by(D.ano.desc(), D.valor.desc())).all()
    if not linhas:
        raise HTTPException(404, "Esse CNPJ não consta como doador nas eleições coletadas.")
    por_ano: dict[int, dict] = {}
    for x in linhas:
        a = por_ano.setdefault(x.ano, {"ano": x.ano, "valor": 0.0, "por_partido": {}, "candidaturas": []})
        a["valor"] = round(a["valor"] + x.valor, 2)
        a["por_partido"][x.partido or "?"] = round(a["por_partido"].get(x.partido or "?", 0) + x.valor, 2)
        if len(a["candidaturas"]) < 30:
            a["candidaturas"].append({"sq_candidato": x.sq_candidato, "candidato": x.candidato, "cargo": x.cargo, "uf": x.uf, "partido": x.partido, "origem": x.origem,
                                      "valor": x.valor, "doacoes": x.n_doacoes, "primeira": x.primeira_data, "ultima": x.ultima_data})
    return {"cnpj": c, "nome": linhas[0].doador, "eleicoes": list(por_ano.values()), "aviso": AVISO}
