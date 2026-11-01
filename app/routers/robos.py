"""Robôs (status de cada coleta por categoria) e auditoria do verificador Gemini. Só leitura."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import robos
from app.db import get_db

router = APIRouter()


@router.get("/robos", tags=["Robôs"])
def resumo(db: Session = Depends(get_db)):
    """Quantos robôs há em cada categoria e quantos estão captando, ok, atrasados, com falha ou aguardando."""
    return robos.resumo(db)


@router.get("/robos/auditoria", tags=["Robôs"])
def auditoria(db: Session = Depends(get_db)):
    """Erros encontrados pelo Gemini e relatos manuais, com o status de cada um."""
    return robos.auditoria(db)


@router.get("/robos/{slug}", tags=["Robôs"])
def categoria(slug: str, db: Session = Depends(get_db)):
    """Todos os robôs de uma categoria, com a situação de cada um (e os veículos, em Notícias)."""
    d = robos.categoria(db, slug)
    if d is None:
        raise HTTPException(404, "Categoria não encontrada.")
    return d
