"""Como cada tarefa aparece na tabela `coletas`.

A tarefa se chama "camara-proposicoes-situacao" na linha de comando, mas a coleta grava fonte="camara" e tarefa="proposicoes_situacao"
(o que o coletor passa para `registrar_coleta`). Para a tela "Situação das fontes" achar a última coleta de cada tarefa, este módulo lê o
código de cada função do registro e pega o primeiro `registrar_coleta("fonte", "tarefa", ...)` dela. Função que só delega a outra (sem a
chamada dentro dela) entra em MANUAL.
"""
import ast
import inspect
import textwrap
from functools import lru_cache

MANUAL = {"transparencia-gastos-todos": ("transparencia", "gastos_orgao")}  # coletar_gastos_todos_orgaos chama coletar_gastos_por_orgao


def _registro_da_funcao(fn) -> tuple[str, str] | None:
    try:
        arvore = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return None
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and getattr(no.func, "id", getattr(no.func, "attr", None)) == "registrar_coleta" and len(no.args) >= 2 \
                and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in no.args[:2]):
            return no.args[0].value, no.args[1].value
    return None


@lru_cache(maxsize=1)
def registro_das_tarefas() -> dict[str, tuple[str, str]]:
    """{nome da tarefa: (fonte, tarefa) gravados em `coletas`}. Tarefa que não se consegue ligar fica de fora."""
    from app.collectors import _TAREFAS_BRUTAS
    out = {nome: par for nome, fn in _TAREFAS_BRUTAS.items() if (par := _registro_da_funcao(fn))}
    out.update(MANUAL)
    return out
