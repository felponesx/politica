"""Rotas da aba Pesquisas (app/pesquisas.py). Sem o arquivo gerado, respondem 404 com o comando para gerá-lo."""
from fastapi import APIRouter, HTTPException, Query

from app import pesquisas

router = APIRouter(tags=["Pesquisas"])
_SEM = "Sem dados. Rode: python -m scripts.pesquisas"


def _ok(r):
    if r is None:
        raise HTTPException(404, _SEM)
    return r


@router.get("/pesquisas/base")
def pesquisas_base():
    """Todos os projetos em listas compactas (a tela filtra e ordena no navegador)."""
    return _ok(pesquisas.base())


@router.get("/pesquisas/resumo")
def pesquisas_resumo():
    return _ok(pesquisas.resumo())


@router.get("/pesquisas/instituicoes")
def pesquisas_instituicoes(uf: str = "", q: str = ""):
    return _ok(pesquisas.instituicoes(uf=uf, q=q))


@router.get("/pesquisas/instituicao/{inst_id}")
def pesquisas_instituicao(inst_id: int):
    r = pesquisas.instituicao(inst_id)
    if r is None:
        raise HTTPException(404, "Instituição não encontrada")
    return r


@router.get("/pesquisas/projeto/{proj_id}")
def pesquisas_projeto(proj_id: int):
    r = pesquisas.projeto(proj_id)
    if r is None:
        raise HTTPException(404, "Projeto não encontrado")
    return r


@router.get("/pesquisas")
def pesquisas_lista(q: str = "", instituicao: int | None = None, uf: str = "", area: str = "", ano: int | None = None, fonte: str = "",
                    institucional: bool | None = False, empresa: bool = False, ordem: str = Query("valor", pattern="^(valor|ano)$"),
                    limite: int = Query(50, ge=1, le=200), pagina: int = Query(1, ge=1)):
    return _ok(pesquisas.listar(q=q, instituicao=instituicao, uf=uf, area=area, ano=ano, fonte=fonte, institucional=institucional, empresa=empresa,
                                ordem=ordem, limite=limite, pagina=pagina))
