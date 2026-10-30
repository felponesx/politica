from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import lacunas
from app.db import get_db
from app.utils import memo, para_uf

router = APIRouter()


def _ou_404(d, tarefa: str):
    if not d:
        raise HTTPException(404, f"Sem dados. Rode a coleta {tarefa}.")
    return d


@router.get("/social", tags=["Social"])
def social(db: Session = Depends(get_db)):
    """Bolsa Família e BPC por estado (beneficiários, valor, por 100 habitantes)."""
    return _ou_404(memo(("social",), lambda: lacunas.social(db)), "transparencia-social")


@router.get("/social/municipios", tags=["Social"])
def social_municipios(uf: str = Query(..., min_length=2, max_length=2), limit: int = Query(60, ge=1, le=500), db: Session = Depends(get_db)):
    """Municípios de um estado (os maiores primeiro) com Bolsa Família e BPC por 100 habitantes."""
    sigla = para_uf(uf)
    if not sigla:
        raise HTTPException(422, "UF inválida.")
    return {"uf": sigla, "itens": lacunas.social_municipios(db, sigla, limit)}


@router.get("/trabalho", tags=["Social"])
def trabalho(db: Session = Depends(get_db)):
    """Desocupação e rendimento do trabalho por estado (PNAD Contínua)."""
    return _ou_404(memo(("trabalho",), lambda: lacunas.trabalho(db)), "ibge-trabalho")


@router.get("/ambiente", tags=["Meio ambiente"])
def ambiente(db: Session = Depends(get_db)):
    """Desmatamento por estado (PRODES, por bioma) e alertas recentes (DETER)."""
    return _ou_404(memo(("ambiente",), lambda: lacunas.ambiente(db)), "inpe-desmatamento")


@router.get("/viagens", tags=["Dinheiro público"])
def viagens(db: Session = Depends(get_db)):
    """Viagens a serviço do governo federal: diárias e passagens por órgão e ano."""
    return _ou_404(memo(("viagens",), lambda: lacunas.viagens(db)), "transparencia-viagens")


@router.get("/fundos", tags=["Dinheiro público"])
def fundos(db: Session = Depends(get_db)):
    """Fundo eleitoral (FEFC) por partido e eleição."""
    return _ou_404(memo(("fundos",), lambda: lacunas.fundos(db)), "tse-fundos")


@router.get("/energia-tarifas", tags=["Indicadores"])
def energia_tarifas(db: Session = Depends(get_db)):
    """Tarifa residencial de energia por distribuidora (ANEEL)."""
    return _ou_404(memo(("energia",), lambda: lacunas.energia(db)), "aneel-tarifas")


@router.get("/cpis", tags=["Congresso"])
def cpis(db: Session = Depends(get_db)):
    """CPIs e CPMIs da Câmara e do Senado (nome, datas, situação)."""
    return _ou_404(memo(("cpis",), lambda: lacunas.cpis(db)), "congresso-cpis")
