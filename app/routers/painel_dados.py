"""Dados das abas do painel que não vêm das tabelas do BRASIL+: o coletor (verificação e correção), e o Instagram. Só por sessão de conta
com permissão na aba correspondente (app/painel_acesso.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import contas, coletor_ponte, instagram, painel_acesso
from app.db import get_db

router = APIRouter(tags=["Painel"])


def _conta(request: Request, db: Session, secao: str, nivel: str):
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    if conta is None:
        raise HTTPException(401, "Entre no painel.")
    if not painel_acesso.pode(conta, secao, nivel):
        raise HTTPException(403, "Sem permissão para esta área.")
    return conta


def _json(request: Request) -> None:
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Envie os dados em JSON.")


class DecisaoIn(BaseModel):
    fonte: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    acao: str = Field(pattern="^(aprovar|rejeitar)$")


class FonteIn(BaseModel):
    fonte: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")


@router.get("/coletor/status")
def coletor_status(request: Request, db: Session = Depends(get_db)):
    """Estado de cada fonte do coletor, verificação (regras + Gemini), correções de formato e envios. Qualquer conta do painel."""
    conta = contas.conta_da_sessao(db, request.cookies.get(contas.COOKIE))
    if conta is None:
        raise HTTPException(401, "Entre no painel.")
    if painel_acesso.permissoes_de(conta) is None:
        raise HTTPException(403, "Sem permissão para esta área.")
    try:
        return coletor_ponte.status()
    except coletor_ponte.ColetorIndisponivel as e:
        raise HTTPException(503, str(e))


@router.post("/coletor/decidir")
def coletor_decidir(corpo: DecisaoIn, request: Request, db: Session = Depends(get_db)):
    _json(request)
    _conta(request, db, "correcao", "alterar")
    try:
        return {"resultado": coletor_ponte.decidir(corpo.fonte, corpo.acao)}
    except ValueError as e:
        raise HTTPException(409, str(e))
    except coletor_ponte.ColetorIndisponivel as e:
        raise HTTPException(503, str(e))


@router.post("/coletor/desfazer")
def coletor_desfazer(corpo: FonteIn, request: Request, db: Session = Depends(get_db)):
    _json(request)
    _conta(request, db, "correcao", "alterar")
    try:
        return {"resultado": coletor_ponte.desfazer(corpo.fonte)}
    except ValueError as e:
        raise HTTPException(409, str(e))
    except coletor_ponte.ColetorIndisponivel as e:
        raise HTTPException(503, str(e))


@router.get("/instagram/status")
def instagram_status(request: Request, atualizar: bool = False, db: Session = Depends(get_db)):
    _conta(request, db, "instagram", "ver")
    return instagram.status(forcar=atualizar)
