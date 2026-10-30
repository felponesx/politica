from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import ensino
from app.db import get_db
from app.utils import memo

router = APIRouter()


@router.get("/igc", tags=["Ensino"])
def igc(db: Session = Depends(get_db)):
    """IGC (nota de qualidade) das instituições de ensino superior, por edição (INEP)."""
    from app.models import Registro
    from app.collectors.inep_igc import AVISO
    regs = {r.chave: r.dados for r in db.query(Registro).filter_by(fonte="inep", tipo="igc_edicao")}
    if not regs:
        raise HTTPException(404, "Sem dados de IGC. Rode a coleta inep-igc.")
    ano = max(regs)
    return {"edicao": regs[ano], "edicoes": sorted(regs, reverse=True), "aviso": AVISO, "fonte": "INEP — Indicadores de Qualidade da Educação Superior"}


@router.get("/ensino", tags=["Ensino"])
def ensino_painel(db: Session = Depends(get_db)):
    """IDEB do Brasil e dos estados (anos iniciais, finais e ensino médio), melhores escolas e, quando coletado, o IGC das faculdades."""
    d = memo(("ensino",), lambda: ensino.montar(db))
    if not any(d.get(k) for k in ("ideb", "superior", "escolas")):
        raise HTTPException(404, "Sem dados de ensino. Rode a coleta ensino-ideb.")
    return d
