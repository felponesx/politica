from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Norma, Proposicao, Votacao

router = APIRouter(tags=["Legislação"])


def _norma(n: Norma) -> dict:
    return {"id": n.id, "tipo": n.tipo, "numero": n.numero, "ano": n.ano,
            "data": n.data, "ementa": n.ementa, "url_texto": n.url_texto, "urn": n.urn,
            "proposicao_id": n.proposicao_id, "esfera": n.esfera, "uf": n.uf}


@router.get("/legislacao")
def listar_normas(q: str | None = None, tipo: str | None = None, ano: int | None = None,
                  esfera: str | None = None, uf: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=1_000_000), db: Session = Depends(get_db)):
    stmt = select(Norma).order_by(Norma.data.desc().nullslast(), Norma.id.desc())
    if tipo:
        stmt = stmt.where(Norma.tipo == tipo.upper())
    if ano:
        stmt = stmt.where(Norma.ano == ano)
    if esfera:
        stmt = stmt.where(Norma.esfera == esfera.lower())
    if uf:
        stmt = stmt.where(Norma.uf == uf.upper())
    if q:
        termo = f"%{q}%"
        stmt = stmt.where(or_(Norma.ementa.ilike(termo), Norma.numero == q))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {"total": total, "itens": [_norma(n) for n in db.scalars(stmt.limit(limit).offset(offset))]}


@router.get("/legislacao/{nid}")
def detalhe_norma(nid: int, db: Session = Depends(get_db)):
    """Popout de norma: dados, projeto de origem e votações desse projeto."""
    n = db.get(Norma, nid)
    if not n:
        raise HTTPException(404, "Norma não encontrada")
    origem, votacoes = None, []
    if n.proposicao_id:
        p = db.get(Proposicao, n.proposicao_id)
        origem = {"id": p.id, "casa": p.casa, "sigla_tipo": p.sigla_tipo, "numero": p.numero,
                  "ano": p.ano, "ementa": p.ementa, "situacao": p.situacao}
        rotulo = f"{p.sigla_tipo} {p.numero}/{p.ano}"
        votacoes = [{"id": v.id, "casa": v.casa, "data": v.data, "descricao": v.descricao, "resultado": v.resultado}
                    for v in db.scalars(select(Votacao).where(or_(Votacao.materia.ilike(f"%{rotulo}%"),
                                                                    Votacao.descricao.ilike(f"%{rotulo}%")))
                                        .order_by(Votacao.data))]
    return {"norma": _norma(n), "proposicao_origem": origem, "votacoes": votacoes}


@router.get("/legislacao-resumo")
def resumo_legislacao(db: Session = Depends(get_db)):
    """Quantidade de normas por ano e tipo (gráfico da tela de legislação)."""
    linhas = db.execute(select(Norma.ano, Norma.tipo, func.count()).group_by(Norma.ano, Norma.tipo)
                        .order_by(Norma.ano.desc())).all()
    return [{"ano": a, "tipo": t, "quantidade": q} for a, t, q in linhas]


@router.get("/legislacao-estados")
def legislacao_por_estado(db: Session = Depends(get_db)):
    """Quantidade de normas estaduais coletadas por UF e o ano mais recente."""
    linhas = db.execute(select(Norma.uf, func.count(), func.max(Norma.ano)).where(Norma.esfera == "estadual")
                        .group_by(Norma.uf)).all()
    return {u: {"normas": c, "ano_mais_recente": a} for u, c, a in linhas if u}
