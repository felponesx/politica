"""Sugestões do verificador Gemini (só leitura). Quem aprova ou descarta é uma pessoa, direto no banco."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Registro

router = APIRouter()


@router.get("/sugestoes", tags=["Revisão"])
def sugestoes(status: str = Query("pendente", pattern="^(pendente|aprovada|descartada|todas)$"), limit: int = Query(100, ge=1, le=500),
              db: Session = Depends(get_db)):
    """Suspeitas apontadas pelo Gemini na cópia dos dados. Não são correções: cada uma precisa de conferência na fonte oficial."""
    q = select(Registro).where(Registro.fonte == "gemini", Registro.tipo == "sugestao").order_by(Registro.id).limit(limit)
    itens = []
    for r in db.execute(q).scalars():
        d = r.dados or {}
        if status != "todas" and d.get("status") != status:
            continue
        itens.append({"id": r.id, **d})
    return {"aviso": "Sugestões de um modelo de linguagem. Nenhum dado foi alterado; confira na fonte oficial.", "itens": itens}
