from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.busca import ENTIDADES, buscar
from app.db import get_db
from app.models import Candidato, Contrato, Indicador, Obra

router = APIRouter()


def _linha(obj, *excluir):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in ("registro_id", "normalizado_em", *excluir)}


def _pagina(db, stmt, limit, offset):
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {"total": total, "itens": [_linha(o) for o in db.scalars(stmt.limit(limit).offset(offset))]}


@router.get("/busca", tags=["Busca"])
def busca(q: str = Query(..., min_length=2), tipos: str | None = None, limite: int = Query(8, le=50),
          db: Session = Depends(get_db)):
    """Busca única do site (caixa de pesquisa). `tipos`: lista separada por vírgula entre
    parlamentares, candidatos, proposicoes, normas, votacoes, contratos, obras, municipios."""
    lista = [t for t in (tipos.split(",") if tipos else ENTIDADES) if t in ENTIDADES]
    return {"q": q, "resultados": buscar(db, q, lista, limite)}


@router.get("/contratos", tags=["Contratos"])
def contratos(uf: str | None = None, ano: int | None = None, esfera: str | None = None,
              cnpj_fornecedor: str | None = None, cnpj_orgao: str | None = None, municipio: str | None = None,
              valor_min: float | None = None, ordenar: str = Query("valor", pattern="^(valor|data)$"),
              limit: int = Query(50, le=500), offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(Contrato)
    for col, val in ((Contrato.ano, ano), (Contrato.esfera, esfera and esfera.upper()),
                     (Contrato.cnpj_fornecedor, cnpj_fornecedor), (Contrato.cnpj_orgao, cnpj_orgao)):
        if val is not None:
            stmt = stmt.where(col == val)
    if uf:
        stmt = stmt.where(Contrato.uf == uf.upper())
    if municipio:
        stmt = stmt.where(Contrato.municipio.ilike(municipio))
    if valor_min is not None:
        stmt = stmt.where(Contrato.valor >= valor_min)
    ordem = Contrato.valor.desc().nullslast() if ordenar == "valor" else Contrato.data_assinatura.desc().nullslast()
    return _pagina(db, stmt.order_by(ordem), limit, offset)


@router.get("/contratos/{cid}", tags=["Contratos"])
def contrato(cid: int, db: Session = Depends(get_db)):
    """Popout de contrato, com outros contratos do mesmo fornecedor."""
    c = db.get(Contrato, cid)
    if not c:
        raise HTTPException(404, "Contrato não encontrado")
    outros = []
    if c.cnpj_fornecedor:
        outros = db.scalars(select(Contrato).where(Contrato.cnpj_fornecedor == c.cnpj_fornecedor, Contrato.id != c.id)
                            .order_by(Contrato.valor.desc().nullslast()).limit(10)).all()
    total_fornecedor = db.scalar(select(func.sum(Contrato.valor)).where(Contrato.cnpj_fornecedor == c.cnpj_fornecedor)) \
        if c.cnpj_fornecedor else None
    from app.routers.ligacoes import AVISO, resumo_fornecedor
    cota = resumo_fornecedor(db, c.cnpj_fornecedor)["cota_parlamentar"] if c.cnpj_fornecedor else None
    return {"contrato": _linha(c), "fornecedor": {"cnpj": c.cnpj_fornecedor, "nome": c.fornecedor,
                                                  "total_contratado": total_fornecedor,
                                                  "outros_contratos": [_linha(o) for o in outros],
                                                  "tambem_na_cota_parlamentar": cota if cota and cota["quantidade"] else None},
            "aviso": AVISO if cota and cota["quantidade"] else None}


@router.get("/obras", tags=["Obras"])
def obras(uf: str | None = None, situacao: str | None = None, tipo: str | None = None,
          limit: int = Query(50, le=500), offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(Obra).order_by(Obra.valor_previsto.desc().nullslast())
    if uf:
        stmt = stmt.where(Obra.uf == uf.upper())
    if situacao:
        stmt = stmt.where(Obra.situacao.ilike(situacao))
    if tipo:
        stmt = stmt.where(Obra.tipo.ilike(f"%{tipo}%"))
    return _pagina(db, stmt, limit, offset)


@router.get("/obras/{oid}", tags=["Obras"])
def obra(oid: int, db: Session = Depends(get_db)):
    o = db.get(Obra, oid)
    if not o:
        raise HTTPException(404, "Obra não encontrada")
    return _linha(o)


@router.get("/obras-resumo/{uf}", tags=["Obras"])
def obras_resumo(uf: str, db: Session = Depends(get_db)):
    linhas = db.execute(select(Obra.situacao, func.count(), func.sum(Obra.valor_previsto))
                        .where(Obra.uf == uf.upper()).group_by(Obra.situacao)).all()
    return [{"situacao": s, "quantidade": q, "valor_previsto": v} for s, q, v in linhas]


@router.get("/candidatos", tags=["Eleições"])
def candidatos(ano: int | None = None, uf: str | None = None, cargo: str | None = None, partido: str | None = None,
               q: str | None = None, eleitos: bool = False, limit: int = Query(50, le=500), offset: int = 0,
               db: Session = Depends(get_db)):
    """`cargo` aceita vários separados por vírgula. Com `eleitos=true` e sem `ano`, usa a eleição mais recente
    daquele cargo (ex.: deputados estaduais eleitos em 2022, prefeitos eleitos em 2024)."""
    stmt = select(Candidato).order_by(Candidato.uf, Candidato.nome_urna)
    cargos = [c.strip().upper() for c in cargo.split(",") if c.strip()] if cargo else []
    if cargos:
        stmt = stmt.where(Candidato.cargo.in_(cargos))
    if eleitos:
        stmt = stmt.where(Candidato.resultado.ilike("ELEITO%"))
        if not ano:
            ano = db.scalar(select(func.max(Candidato.ano)).where(
                Candidato.resultado.ilike("ELEITO%"), *([Candidato.cargo.in_(cargos)] if cargos else [])))
    if ano:
        stmt = stmt.where(Candidato.ano == ano)
    if uf:
        stmt = stmt.where(Candidato.uf == uf.upper())
    if partido:
        stmt = stmt.where(Candidato.partido == partido.upper())
    if q:
        stmt = stmt.where(or_(Candidato.nome.ilike(f"%{q}%"), Candidato.nome_urna.ilike(f"%{q}%")))
    return _pagina(db, stmt, limit, offset)


@router.get("/indicadores", tags=["Estados"])
def indicadores(uf: str | None = None, nome: str | None = None, db: Session = Depends(get_db)):
    """Séries por estado (população, PIB, PIB per capita...). Sem `uf`: todos os estados (para mapas/rankings)."""
    stmt = select(Indicador).order_by(Indicador.nome, Indicador.uf, Indicador.periodo)
    if uf:
        stmt = stmt.where(Indicador.uf == uf.upper())
    if nome:
        stmt = stmt.where(Indicador.nome == nome)
    return [_linha(i) for i in db.scalars(stmt)]
