from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import catastrofes
from app.db import get_db

router = APIRouter()


@router.get("/catastrofes", tags=["Catástrofes"])
def catastrofes_lista(tipo: str | None = Query(None, max_length=40), db: Session = Depends(get_db)):
    """Tragédias marcantes do país (acidentes, barragens, enchentes, incêndios), cada uma com a fonte do número de mortos."""
    return catastrofes.tragedias(tipo, db)


@router.get("/catastrofes/rodovias", tags=["Catástrofes"])
def catastrofes_rodovias(ano: int | None = Query(None, ge=2000, le=2100), db: Session = Depends(get_db)):
    """Acidentes nas rodovias federais por estado e tipo de envolvido (pedestre, motociclista, carro, caminhão, ônibus, bicicleta)."""
    d = catastrofes.rodovias(db, ano)
    if not d:
        raise HTTPException(404, "Sem dados. Rode a coleta prf-pessoas.")
    return d


@router.get("/catastrofes/transferencias", tags=["Catástrofes"])
def catastrofes_transferencias(ano: int | None = Query(None, ge=2000, le=2100), db: Session = Depends(get_db)):
    """Repasses federais para defesa civil por estado e ano (não é o gasto do estado e não separa por desastre)."""
    d = catastrofes.transferencias(db, ano)
    if not d:
        raise HTTPException(404, "Sem dados. Rode a coleta defesa-civil-transferencias.")
    return d
