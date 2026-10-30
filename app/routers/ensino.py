from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import ensino
from app.db import get_db
from app.utils import memo

router = APIRouter()


@router.get("/ensino", tags=["Ensino"])
def ensino_painel(db: Session = Depends(get_db)):
    """IDEB do Brasil e dos estados (anos iniciais, finais e ensino médio), melhores escolas e, quando coletado, o IGC das faculdades."""
    d = memo(("ensino",), lambda: ensino.montar(db))
    if not any(d.get(k) for k in ("ideb", "superior", "escolas")):
        raise HTTPException(404, "Sem dados de ensino. Rode a coleta ensino-ideb.")
    return d
