from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import catastrofes
from app.db import get_db

router = APIRouter()


@router.get("/catastrofes", tags=["Catástrofes"])
def catastrofes_lista(tipo: str | None = Query(None, max_length=40), db: Session = Depends(get_db)):
    """Tragédias marcantes do país (acidentes, barragens, enchentes, incêndios), cada uma com a fonte do número de mortos."""
    return catastrofes.tragedias(tipo)


@router.get("/catastrofes/rodovias", tags=["Catástrofes"])
def catastrofes_rodovias(ano: int | None = Query(None, ge=2000, le=2100), db: Session = Depends(get_db)):
    """Acidentes nas rodovias federais por estado e tipo de envolvido (pedestre, motociclista, carro, caminhão, ônibus, bicicleta)."""
    d = catastrofes.rodovias(db, ano)
    if not d:
        raise HTTPException(404, "Sem dados. Rode a coleta prf-pessoas.")
    return d
