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


ATOS_OK = ("abertura", "processo_seletivo", "convocacao", "nomeacao", "homologacao", "retificacao", "prorrogacao")


@router.get("/concursos", tags=["Concursos e cursos"])
def concursos(ato: str | None = Query(None, description="convocacao, nomeacao, homologacao, retificacao, prorrogacao; vazio = aberturas"),
              db: Session = Depends(get_db)):
    """Concursos e processos seletivos: DOU (federal), diários estaduais (onde há coletor) e diários das prefeituras (Querido Diário),
    com a situação de cada fonte em `cobertura`."""
    if ato and ato not in ATOS_OK:
        raise HTTPException(422, "Tipo de ato inválido.")
    return _ou_404(memo(("concursos", ato), lambda: op.concursos(db, ato=ato)), "concursos")


@router.get("/concursos/cobertura", tags=["Concursos e cursos"])
def concursos_cobertura(db: Session = Depends(get_db)):
    """Situação de cada fonte de concursos: os 27 diários estaduais (coletor, última coleta bem-sucedida, erro) e o Querido Diário."""
    return op.cobertura_concursos(db)


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
