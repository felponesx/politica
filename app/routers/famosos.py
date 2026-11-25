"""Rotas da aba Artistas e famosos (app/famosos.py). Sem o arquivo gerado, respondem 404 com o comando para gerá-lo."""
from fastapi import APIRouter, HTTPException

from app import famosos

router = APIRouter(tags=["Artistas e famosos"])
_SEM = "Sem dados. Rode: python -m scripts.famosos"


def _ok(r):
    if r is None:
        raise HTTPException(404, _SEM)
    return r


@router.get("/famosos/base")
def famosos_base():
    """Todas as pessoas (a tela filtra e ordena no navegador)."""
    return _ok(famosos.base())


@router.get("/famosos/resumo")
def famosos_resumo():
    return _ok(famosos.resumo())


@router.get("/famosos/pessoa/{q}")
def famosos_pessoa(q: str):
    _ok(famosos.base())
    r = famosos.pessoa(q)
    if r is None:
        raise HTTPException(404, "Pessoa não encontrada")
    return r
