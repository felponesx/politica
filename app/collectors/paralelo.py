"""Executor de um grupo de tarefas em paralelo, por FONTE.

- Tarefas de fontes DIFERENTES rodam ao mesmo tempo (até `workers`), então o grupo termina mais cedo.
- Tarefas da MESMA fonte rodam em fila, uma depois da outra, com uma pausa entre elas: é assim que se respeita o limite
  do órgão (ele não recebe duas rajadas juntas). Não há atalho de "mais rápido com risco" aqui.
- Uma falha não derruba as outras: cada resultado volta com o erro, e quem chama decide (alerta, contador de falhas).
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("brasilplus.paralelo")
PAUSA_PADRAO = 2.0  # segundos entre duas tarefas da mesma fonte
WORKERS_PADRAO = 4


def fonte_de(tarefa: str, registro: dict[str, tuple[str, str]]) -> str:
    """Fonte que a tarefa grava em `coletas` (ou o próprio nome da tarefa, se não der para saber)."""
    return registro.get(tarefa, (tarefa, ""))[0] or tarefa


def agrupar_por_fonte(tarefas: list[tuple[str, dict]], registro: dict[str, tuple[str, str]]) -> dict[str, list[tuple[str, dict]]]:
    """Mantém a ordem original dentro de cada fonte."""
    grupos: dict[str, list[tuple[str, dict]]] = {}
    for item in tarefas:
        grupos.setdefault(fonte_de(item[0], registro), []).append(item)
    return grupos


def executar_grupo(tarefas: list[tuple[str, dict]], executar, registro: dict[str, tuple[str, str]], workers: int = WORKERS_PADRAO,
                   pausa: float = PAUSA_PADRAO) -> list[tuple[str, Exception | None]]:
    """Roda `executar(nome, params)` para cada tarefa. Devolve [(nome, erro ou None)] na ordem da lista original."""
    resultados: dict[str, Exception | None] = {}
    ordem = [nome for nome, _ in tarefas]

    def fila(itens):
        for i, (nome, params) in enumerate(itens):
            if i:
                time.sleep(pausa)  # a fonte recebe uma tarefa por vez, com folga
            try:
                log.info("%s %s", nome, params)
                executar(nome, params)
                resultados[nome] = None
            except Exception as e:  # noqa: BLE001 — a falha de uma tarefa não pode parar o grupo
                log.error("%s falhou: %s", nome, e)
                resultados[nome] = e

    grupos = agrupar_por_fonte(tarefas, registro)
    if workers <= 1 or len(grupos) <= 1:
        for itens in grupos.values():
            fila(itens)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for futuro in [pool.submit(fila, itens) for itens in grupos.values()]:
                futuro.result()
    return [(nome, resultados.get(nome)) for nome in ordem]
