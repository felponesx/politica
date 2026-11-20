from fastapi import APIRouter, HTTPException, Query

from app import habitantes, populacao, religiao, sobrenomes
from app.utils import memo

router = APIRouter()


@router.get("/populacao", tags=["População"])
def populacao_censo():
    """População por estado e Brasil (Censo 2022): cor ou raça e sexo, em porcentagem."""
    d = memo(("populacao-censo",), lambda: populacao.censo())
    if not d:
        raise HTTPException(404, "Sem dados. Rode python -m scripts.populacao_censo.")
    return d


@router.get("/religiao", tags=["População"])
def religiao_censo():
    """Religião por estado e Brasil (Censo 2022, pessoas de 10 anos ou mais) e organizações religiosas registradas por ano."""
    d = memo(("religiao",), lambda: religiao.religiao())
    if not d:
        raise HTTPException(404, "Sem dados. Rode python -m scripts.religiao.")
    return d


@router.get("/populacao/extra", tags=["População"])
def populacao_extra():
    """Crescimento por tamanho de município (Censo 2010→2022), depressão (PNS 2013) e trabalho por aplicativo (PNAD 2025)."""
    d = memo(("populacao-extra",), lambda: habitantes.extra())
    if not d:
        raise HTTPException(404, "Sem dados. Rode python -m scripts.habitantes_extra.")
    return d


@router.get("/sobrenomes", tags=["População"])
def origem_sobrenome(nome: str = Query(..., min_length=2, max_length=40)):
    """Origem de um sobrenome segundo a Wikipédia em português (resumo, link e licença)."""
    try:
        return memo(("sobrenome", nome.strip().lower()), lambda: sobrenomes.origem(nome))
    except ValueError:
        raise HTTPException(422, "Digite só o sobrenome (letras, até 3 palavras).")
    except sobrenomes.SemOrigem:
        raise HTTPException(404, "A Wikipédia não tem uma origem registrada para este sobrenome.")
    except sobrenomes.Indisponivel:
        raise HTTPException(503, "A Wikipédia não respondeu agora. Tente de novo daqui a pouco.")
