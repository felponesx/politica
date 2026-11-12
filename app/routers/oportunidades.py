from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import oportunidades as op
from app.db import get_db
from app.utils import memo, para_uf

router = APIRouter()


def _ou_404(d, tarefa: str):
    if not d:
        raise HTTPException(404, f"Sem dados. Rode a coleta {tarefa}.")
    return d


def _uf(uf: str | None) -> str | None:
    if not uf:
        return None
    s = para_uf(uf)
    if not s:
        raise HTTPException(422, "UF inválida.")
    return s


@router.get("/concursos", tags=["Concursos e cursos"])
def concursos(db: Session = Depends(get_db)):
    """Editais de abertura de concurso público e processo seletivo (Diário Oficial da União e diários das prefeituras)."""
    return _ou_404(memo(("concursos",), lambda: op.concursos(db)), "concursos")


@router.get("/cursos", tags=["Concursos e cursos"])
def cursos(db: Session = Depends(get_db)):
    """Cursos gratuitos: Escola Virtual.Gov (Enap) e Sebrae (só os de preço zero), mais onde procurar os demais."""
    return _ou_404(memo(("cursos",), lambda: op.cursos(db)), "cursos-gratuitos")


@router.get("/eventos", tags=["Eventos"])
def eventos(uf: str | None = Query(None, max_length=2), db: Session = Depends(get_db)):
    """Shows contratados por prefeituras, estados e União (PNCP, inexigibilidade). Sem `uf`: resumo do país; com `uf`: todos do estado."""
    s = _uf(uf)
    return _ou_404(memo(("eventos", s), lambda: op.eventos(db, s)), "eventos-shows")


@router.get("/eventos-patrocinios", tags=["Eventos"])
def patrocinios(uf: str | None = Query(None, max_length=2), db: Session = Depends(get_db)):
    """Lei Rouanet: festivais, festas, feiras e shows com valor captado e as empresas patrocinadoras."""
    s = _uf(uf)
    return _ou_404(memo(("patrocinios", s), lambda: op.patrocinios(db, s)), "eventos-patrocinios")
