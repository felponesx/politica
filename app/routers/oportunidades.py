"""Cursos, eventos e concursos. Leitura pública só do que foi aprovado; cadastro e aprovação exigem o X-Admin-Token
(mesmo critério das fontes cadastradas). Quem cadastra não aprova: a aprovação é um passo separado."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Oportunidade
from app.routers.fontes_cadastro import _exige_admin, _sessao_escrita

router = APIRouter(tags=["Cursos, eventos e concursos"])
TIPOS = ("curso", "evento", "concurso")
STATUS = ("pendente", "aprovado", "rejeitado")


class OportunidadeIn(BaseModel):
    tipo: str = Field(max_length=12)
    titulo: str = Field(min_length=3, max_length=300)
    orgao: str | None = Field(default=None, max_length=200)
    uf: str | None = Field(default=None, min_length=2, max_length=2)
    cidade: str | None = Field(default=None, max_length=120)
    data_inicio: date | None = None
    data_fim: date | None = None
    inscricoes_ate: date | None = None
    link: str = Field(min_length=10, max_length=500)
    fonte: str | None = Field(default=None, max_length=200)


def _ver(o: Oportunidade) -> dict:
    return {"id": o.id, "tipo": o.tipo, "titulo": o.titulo, "orgao": o.orgao, "uf": o.uf, "cidade": o.cidade,
            "data_inicio": o.data_inicio.isoformat() if o.data_inicio else None,
            "data_fim": o.data_fim.isoformat() if o.data_fim else None,
            "inscricoes_ate": o.inscricoes_ate.isoformat() if o.inscricoes_ate else None,
            "link": o.link, "fonte": o.fonte, "status": o.status,
            "aprovada_em": o.aprovada_em.isoformat() if o.aprovada_em else None}


@router.get("/oportunidades", tags=["Cursos, eventos e concursos"])
def listar(tipo: str | None = None, uf: str | None = None, status: str = "aprovado", db: Session = Depends(get_db)):
    if status not in STATUS:
        raise HTTPException(422, "status inválido")
    q = select(Oportunidade).where(Oportunidade.status == status).order_by(Oportunidade.inscricoes_ate.is_(None),
                                                                            Oportunidade.inscricoes_ate, Oportunidade.id.desc())
    if tipo:
        q = q.where(Oportunidade.tipo == tipo)
    if uf:
        q = q.where(Oportunidade.uf == uf.upper())
    return [_ver(o) for o in db.scalars(q.limit(500)).all()]


@router.post("/oportunidades", status_code=201, tags=["Cursos, eventos e concursos"])
def cadastrar(corpo: OportunidadeIn, request: Request, x_admin_token: str = Header(...)):
    _exige_admin(request, x_admin_token)
    corpo.uf = corpo.uf.upper() if corpo.uf else None   # UF sempre em maiúsculas, para o filtro achar
    if corpo.tipo not in TIPOS:
        raise HTTPException(422, "tipo deve ser curso, evento ou concurso")
    if not corpo.link.startswith("https://"):
        raise HTTPException(422, "o link precisa começar com https://")
    if corpo.data_inicio and corpo.data_fim and corpo.data_fim < corpo.data_inicio:
        raise HTTPException(422, "a data final é antes da inicial")
    db = _sessao_escrita()
    try:
        existente = db.scalar(select(Oportunidade).where(Oportunidade.tipo == corpo.tipo, Oportunidade.link == corpo.link))
        if existente:   # o mesmo link atualiza a ficha, sem duplicar; a aprovação anterior não muda sozinha
            for campo, valor in corpo.model_dump().items():
                setattr(existente, campo, valor)
            db.commit()
            return {**_ver(existente), "atualizada": True}
        o = Oportunidade(**corpo.model_dump(), status="pendente")
        db.add(o); db.commit(); db.refresh(o)
        return _ver(o)
    finally:
        db.close()


def _decidir(oid: int, status: str, request: Request, token: str) -> dict:
    _exige_admin(request, token)
    db = _sessao_escrita()
    try:
        o = db.get(Oportunidade, oid)
        if not o:
            raise HTTPException(404, "Não encontrado")
        o.status = status
        o.aprovada_em = datetime.now(timezone.utc).replace(tzinfo=None) if status == "aprovado" else None
        db.commit()
        return _ver(o)
    finally:
        db.close()


@router.post("/oportunidades/{oid}/aprovar", tags=["Cursos, eventos e concursos"])
def aprovar(oid: int, request: Request, x_admin_token: str = Header(...)):
    return _decidir(oid, "aprovado", request, x_admin_token)


@router.post("/oportunidades/{oid}/rejeitar", tags=["Cursos, eventos e concursos"])
def rejeitar(oid: int, request: Request, x_admin_token: str = Header(...)):
    return _decidir(oid, "rejeitado", request, x_admin_token)
