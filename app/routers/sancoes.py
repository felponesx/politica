import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import sancoes
from app.db import get_db
from app.utils import memo

AVISO_TCU = ("Inabilitação é uma sanção do TCU que impede a pessoa de ocupar cargo em comissão ou função de confiança por um prazo (em geral de 5 a 8 anos). "
             "Os números são totais da lista pública do TCU; nomes não são exibidos aqui. 'Ainda no prazo' conta quem tem data final no futuro.")

AVISO_CNJ = ("Dados informados pelos próprios tribunais ao CNJ. Taxa de congestionamento = processos que sobraram sem solução em relação ao total que poderia ser resolvido no ano; "
             "quanto maior, mais devagar o tribunal esvazia a fila. Tribunais de portes e áreas diferentes não são diretamente comparáveis.")

router = APIRouter()


@router.get("/sancoes", tags=["Empresas punidas"])
def sancoes_resumo(db: Session = Depends(get_db)):
    """Resumo do CEIS, CNEP e dos acordos de leniência: quantas empresas, por categoria, maiores multas, acordos."""
    d = memo(("sancoes",), lambda: sancoes.resumo(db))
    if not d:
        raise HTTPException(404, "Sem dados de sanções. Rode a coleta cgu-sancoes.")
    return d


@router.get("/tcu-inabilitados", tags=["Empresas punidas"])
def tcu_inabilitados(db: Session = Depends(get_db)):
    """Totais de pessoas inabilitadas pelo TCU para função pública (por estado e por ano). Sem nomes nem CPF."""
    from sqlalchemy import select

    from app.models import Registro
    d = memo(("tcu-inabilitados",), lambda: (lambda r: {**r.dados, "aviso": AVISO_TCU, "fonte": "Tribunal de Contas da União — lista de inabilitados"} if r else None)(
        db.scalar(select(Registro).where(Registro.fonte == "tcu", Registro.tipo == "tcu_inabilitados", Registro.chave == "BR"))))
    if not d:
        raise HTTPException(404, "Sem dados do TCU. Rode a coleta tcu-inabilitados.")
    return d


@router.get("/justica", tags=["Justiça"])
def justica(db: Session = Depends(get_db)):
    """Justiça em Números (CNJ): por tribunal, casos novos, pendentes, baixados, congestionamento e magistrados, por ano."""
    from sqlalchemy import select

    from app.models import Registro
    d = memo(("justica",), lambda: (lambda r: {**r.dados, "aviso": AVISO_CNJ, "fonte": "Conselho Nacional de Justiça — Justiça em Números"} if r else None)(
        db.scalar(select(Registro).where(Registro.fonte == "cnj", Registro.tipo == "justica_em_numeros", Registro.chave == "BR"))))
    if not d:
        raise HTTPException(404, "Sem dados do CNJ. Rode a coleta cnj-justica.")
    return d


@router.get("/sancoes/contratos", tags=["Empresas punidas"])
def sancoes_contratos(limit: int = Query(40, ge=1, le=200), db: Session = Depends(get_db)):
    """Empresas punidas que têm contratos públicos coletados (maior valor primeiro) e quantos foram assinados durante uma sanção."""
    d = memo(("sancoes-contratos", limit), lambda: sancoes.contratos(db, limit))
    if not d:
        raise HTTPException(404, "Sem dados de sanções. Rode a coleta cgu-sancoes.")
    return d


@router.get("/sancoes/busca", tags=["Empresas punidas"])
def sancoes_busca(q: str = Query(..., min_length=3, max_length=80), db: Session = Depends(get_db)):
    """Procura empresas punidas por nome ou começo do CNPJ."""
    return {"itens": sancoes.buscar(db, q)}


@router.get("/sancoes/{cnpj:path}", tags=["Empresas punidas"])
def sancoes_empresa(cnpj: str, db: Session = Depends(get_db)):
    """Sanções de uma empresa (CNPJ com ou sem pontuação)."""
    c = re.sub(r"\D", "", cnpj)
    e = sancoes.empresa(db, c)
    if not e:
        raise HTTPException(404, "Essa empresa não aparece no CEIS nem no CNEP.")
    return {**e, "aviso": sancoes.AVISO}
