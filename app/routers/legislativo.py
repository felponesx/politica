from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.busca import _sem_curinga
from app.db import get_db
from app.models import Despesa, Parlamentar, Proposicao, Votacao, Voto
from app.schemas import DespesaOut, Pagina, ParlamentarOut, ProposicaoOut, VotacaoOut

router = APIRouter(tags=["Legislativo"])


def _paginar(db, stmt, schema, limit, offset):
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return {"total": total, "itens": [schema.model_validate(r) for r in rows]}


@router.get("/parlamentares", response_model=Pagina)
def listar_parlamentares(casa: str | None = None, uf: str | None = None, partido: str | None = None,
                         q: str | None = None, limit: int = Query(50, ge=1, le=600), offset: int = Query(0, ge=0, le=1_000_000),
                         db: Session = Depends(get_db)):
    stmt = select(Parlamentar).order_by(Parlamentar.nome)
    if casa:
        stmt = stmt.where(Parlamentar.casa == casa)
    if uf:
        stmt = stmt.where(Parlamentar.uf == uf.upper())
    if partido:
        stmt = stmt.where(Parlamentar.partido == partido.upper())
    if q:
        stmt = stmt.where(Parlamentar.nome.ilike(f"%{q}%"))
    return _paginar(db, stmt, ParlamentarOut, limit, offset)


@router.get("/parlamentares/{pid}")
def detalhe_parlamentar(pid: int, db: Session = Depends(get_db)):
    """Dados para o popout de pessoa: perfil, últimos votos e resumo de gastos."""
    p = db.get(Parlamentar, pid)
    if not p:
        raise HTTPException(404, "Parlamentar não encontrado")
    votos = db.execute(
        select(Voto.voto, Votacao).join(Votacao).where(Voto.parlamentar_id == pid)
        .order_by(Votacao.data.desc()).limit(20)).all()
    gastos = db.execute(
        select(Despesa.ano, Despesa.tipo, func.sum(Despesa.valor))
        .where(Despesa.parlamentar_id == pid).group_by(Despesa.ano, Despesa.tipo)
        .order_by(Despesa.ano.desc(), func.sum(Despesa.valor).desc())).all()
    return {
        "perfil": ParlamentarOut.model_validate(p),
        "ultimos_votos": [{"voto": v, "votacao": VotacaoOut.model_validate(vt)} for v, vt in votos],
        "gastos_por_tipo": [{"ano": a, "tipo": t, "total": round(s or 0, 2)} for a, t, s in gastos],
        "total_gasto": round(sum(s or 0 for _, _, s in gastos), 2),
    }


@router.get("/votacoes", response_model=Pagina)
def listar_votacoes(casa: str | None = None, desde: date | None = None, ate: date | None = None,
                    q: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=1_000_000),
                    db: Session = Depends(get_db)):
    stmt = select(Votacao).order_by(Votacao.data.desc())
    if casa:
        stmt = stmt.where(Votacao.casa == casa)
    if desde:
        stmt = stmt.where(Votacao.data >= desde)
    if ate:
        stmt = stmt.where(Votacao.data <= ate)
    if q:
        stmt = stmt.where(or_(Votacao.descricao.ilike(f"%{q}%"), Votacao.materia.ilike(f"%{q}%")))
    return _paginar(db, stmt, VotacaoOut, limit, offset)


@router.get("/votacoes/{vid}")
def detalhe_votacao(vid: int, db: Session = Depends(get_db)):
    """Popout de votação: placar geral, placar por partido e por UF, e lista nominal."""
    v = db.get(Votacao, vid)
    if not v:
        raise HTTPException(404, "Votação não encontrada")
    linhas = db.execute(select(Voto.voto, Voto.partido_na_data, Parlamentar)
                        .join(Parlamentar).where(Voto.votacao_id == vid)).all()
    placar, por_partido, por_uf = {}, {}, {}
    for voto, partido, p in linhas:
        placar[voto] = placar.get(voto, 0) + 1
        por_partido.setdefault(partido or "?", {}).setdefault(voto, 0)
        por_partido[partido or "?"][voto] += 1
        por_uf.setdefault(p.uf or "?", {}).setdefault(voto, 0)
        por_uf[p.uf or "?"][voto] += 1
    return {
        "votacao": VotacaoOut.model_validate(v),
        "placar": v.placar_oficial if v.secreta and v.placar_oficial else placar,
        "aviso": "Votação secreta: o Senado informa só quem votou, não o voto de cada senador." if v.secreta else None,
        "por_partido": por_partido,
        "por_uf": por_uf,
        "votos": [{"parlamentar": ParlamentarOut.model_validate(p), "voto": voto, "partido_na_data": partido}
                  for voto, partido, p in sorted(linhas, key=lambda x: x[2].nome)],
    }


@router.get("/proposicoes", response_model=Pagina)
def listar_proposicoes(casa: str | None = None, ano: int | None = None, tipo: str | None = None,
                       q: str | None = Query(None, max_length=120), fase: str | None = Query(None, pattern="^(a_votar|em_votacao|votado)$"),
                       limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=1_000_000),
                       db: Session = Depends(get_db)):
    """Projetos com autor, relator, placar da última votação e fase (a_votar = pronto para ir a voto; em_votacao = na pauta de uma sessão em
    andamento hoje; votado = tem votação registrada). Só o que foi coletado: o que falta vem vazio."""
    from app import projetos
    stmt = select(Proposicao).order_by(Proposicao.ano.desc(), Proposicao.id.desc())
    if casa:
        stmt = stmt.where(Proposicao.casa == casa)
    if ano:
        stmt = stmt.where(Proposicao.ano == ano)
    if tipo:
        stmt = stmt.where(Proposicao.sigla_tipo == tipo.upper())
    else:  # representações por quebra de decoro não são projetos de lei: aparecem na aba Processos do parlamentar
        stmt = stmt.where(or_(Proposicao.sigla_tipo.is_(None), Proposicao.sigla_tipo != "REP"))
    if q:
        stmt = stmt.where(or_(Proposicao.ementa.ilike(f"%{_sem_curinga(q)}%", escape="\\"), Proposicao.numero == q.strip().lstrip("0")))
    stmt = projetos.filtrar_por_fase(db, stmt, fase)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return {"total": total, "itens": projetos.enriquecer(db, rows)}


@router.get("/parlamentares/{pid}/despesas", response_model=Pagina)
def despesas_parlamentar(pid: int, ano: int | None = None, limit: int = Query(100, ge=1, le=1000),
                         offset: int = Query(0, ge=0, le=1_000_000), db: Session = Depends(get_db)):
    stmt = select(Despesa).where(Despesa.parlamentar_id == pid).order_by(Despesa.ano.desc(), Despesa.mes.desc())
    if ano:
        stmt = stmt.where(Despesa.ano == ano)
    return _paginar(db, stmt, DespesaOut, limit, offset)
