import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import sancoes
from app.db import get_db
from app.utils import memo

router = APIRouter()


@router.get("/sancoes", tags=["Empresas punidas"])
def sancoes_resumo(db: Session = Depends(get_db)):
    """Resumo do CEIS, CNEP e dos acordos de leniência: quantas empresas, por categoria, maiores multas, acordos."""
    d = memo(("sancoes",), lambda: sancoes.resumo(db))
    if not d:
        raise HTTPException(404, "Sem dados de sanções. Rode a coleta cgu-sancoes.")
    return d


@router.get("/sancoes/contratos", tags=["Empresas punidas"])
def sancoes_contratos(limit: int = Query(40, ge=1, le=200), db: Session = Depends(get_db)):
    """Empresas punidas que têm contratos públicos coletados (maior valor primeiro) e quantos foram assinados durante uma sanção."""
    d = memo(("sancoes-contratos", limit), lambda: sancoes.contratos(db, limit))
    if not d:
        raise HTTPException(404, "Sem dados de sanções. Rode a coleta cgu-sancoes.")
    return d


@router.get("/sancoes/busca", tags=["Empresas punidas"])
def sancoes_busca(q: str = Query(..., min_length=3, max_length=80), db: Session = Depends(get_db)):
    """Procura empresas punidas por nome ou começo do CNPJ."""
    return {"itens": sancoes.buscar(db, q)}


@router.get("/sancoes/{cnpj:path}", tags=["Empresas punidas"])
def sancoes_empresa(cnpj: str, db: Session = Depends(get_db)):
    """Sanções de uma empresa (CNPJ com ou sem pontuação)."""
    c = re.sub(r"\D", "", cnpj)
    e = sancoes.empresa(db, c)
    if not e:
        raise HTTPException(404, "Essa empresa não aparece no CEIS nem no CNEP.")
    return {**e, "aviso": sancoes.AVISO}
