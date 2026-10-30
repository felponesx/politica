from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import saude
from app.db import get_db
from app.utils import memo, para_uf

router = APIRouter()


@router.get("/saude/painel", tags=["Saúde"])
def painel_saude(db: Session = Depends(get_db)):
    """Atenção básica (UBS e Mais Médicos) e gasto em saúde por estado, com a conta por habitante e as limitações."""
    d = memo(("saude",), lambda: saude.painel(db))
    if not d:
        raise HTTPException(404, "Sem dados de saúde. Rode as coletas saude-ubs, saude-mais-medicos e siconfi-despesas-funcao.")
    return d


@router.get("/saude/municipios", tags=["Saúde"])
def saude_municipios(uf: str = Query(..., min_length=2, max_length=2), limit: int = Query(60, ge=1, le=500), db: Session = Depends(get_db)):
    """Municípios de um estado (os maiores primeiro): população, UBS, UBS por 10 mil habitantes e vagas do Mais Médicos."""
    sigla = para_uf(uf)
    if not sigla:
        raise HTTPException(422, "UF inválida.")
    return {"uf": sigla, "itens": saude.municipios(db, sigla, limit)}
