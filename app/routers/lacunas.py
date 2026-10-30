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


@router.get("/acidentes-rodovias", tags=["Segurança"])
def acidentes_rodovias(db: Session = Depends(get_db)):
    """Acidentes nas rodovias federais (PRF): por ano, estado, mês, causa, tipo e rodovia."""
    return _ou_404(memo(("acidentes",), lambda: lacunas.acidentes_rodovias(db)), "prf-acidentes")


@router.get("/servidores", tags=["Dinheiro público"])
def servidores(db: Session = Depends(get_db)):
    """Servidores civis federais por órgão e estado: quantidade, remuneração bruta, abate-teto e líquida (só somas)."""
    return _ou_404(memo(("servidores",), lambda: lacunas.servidores(db)), "transparencia-servidores")


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


@router.get("/aeroportos", tags=["Infraestrutura"])
def aeroportos(db: Session = Depends(get_db)):
    """Aeródromos públicos (ANAC): total, por estado, situação e operação noturna."""
    return _ou_404(memo(("aeroportos",), lambda: lacunas.aeroportos(db)), "anac-aerodromos")


@router.get("/multas-ambientais", tags=["Meio ambiente"])
def multas_ambientais(db: Session = Depends(get_db)):
    """Autos de infração do IBAMA por estado e ano (quantidade e valor aplicado), sem nomes."""
    return _ou_404(memo(("multas-amb",), lambda: lacunas.multas_ambientais(db)), "ibama-multas")


@router.get("/lista-suja", tags=["Trabalho"])
def lista_suja(db: Session = Depends(get_db)):
    """Cadastro de Empregadores (trabalho análogo ao de escravo): totais por estado e ano, sem nomes."""
    return _ou_404(memo(("lista-suja",), lambda: lacunas.lista_suja(db)), "mte-lista-suja")


@router.get("/renuncia-fiscal", tags=["Dinheiro"])
def renuncia_fiscal(db: Session = Depends(get_db)):
    """Gastos tributários (renúncia fiscal) por função orçamentária e região, ano-base mais novo."""
    return _ou_404(memo(("renuncia",), lambda: lacunas.renuncia_fiscal(db)), "receita-renuncia-fiscal")


@router.get("/tcu-irregulares", tags=["Empresas punidas"])
def tcu_irregulares(db: Session = Depends(get_db)):
    """Totais de responsáveis com contas julgadas irregulares pelo TCU (por estado, ano e tipo). Sem nomes nem documentos."""
    return _ou_404(memo(("tcu-irreg",), lambda: lacunas.tcu_irregulares(db)), "tcu-contas-irregulares")
