"""Obras / projetos de investimento federais — ObrasGov.br.
Docs: https://api.obrasgov.gestao.gov.br/obrasgov/api/swagger-ui/index.html
"""
import queue
import time
from concurrent.futures import ThreadPoolExecutor

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, primeiro, para_float, upsert

BASE = "https://api.obrasgov.gestao.gov.br/obrasgov/api"


def _valor_previsto(o: dict) -> float | None:
    """O valor vem por fonte de recurso (Federal, Estadual...): somamos todas."""
    fontes = o.get("fontesDeRecurso") or []
    valores = [para_float(f.get("valorInvestimentoPrevisto")) for f in fontes if isinstance(f, dict)]
    valores = [v for v in valores if v is not None]
    return round(sum(valores), 2) if valores else para_float(primeiro(o, "valorInvestimentoPrevisto", "valorTotal"))


def _paginas(uf: str, tamanho: int, max_paginas: int, prazo: float):
    """Todas as páginas de um estado. A API devolve `last: true` e `totalElements` = tamanho da página mesmo quando
    há mais páginas (validado em 22/10/2026), então só uma página curta ou vazia encerra."""
    for pagina in range(max_paginas):
        if time.monotonic() > prazo:
            return
        resp = http.get_json(f"{BASE}/projeto-investimento", params={"uf": uf, "pagina": pagina, "tamanhoDaPagina": tamanho})
        itens = resp if isinstance(resp, list) else (resp or {}).get("content") or (resp or {}).get("data") or []
        yield itens
        if len(itens) < tamanho:
            return


def coletar_obras(ufs: list[str] | None = None, tamanho: int = 100, max_paginas: int = 40, minutos: int = 120, paralelo: int = 4):
    """Obras federais por estado (até `max_paginas` x `tamanho` por estado). Cada página leva ~25 s: os estados são
    lidos em paralelo e gravados aqui, um de cada vez."""
    prazo = time.monotonic() + minutos * 60
    fila: queue.Queue = queue.Queue()

    def ler(uf):
        try:
            for itens in _paginas(uf, tamanho, max_paginas, prazo):
                fila.put((uf, itens))
        except Exception as e:  # noqa: BLE001 - um estado com erro não derruba os outros
            fila.put((uf, e))
        fila.put((uf, None))

    lista = ufs or UFS
    with registrar_coleta("obrasgov", "obras") as (db, n):
        with ThreadPoolExecutor(paralelo) as ex:
            for uf in lista:
                ex.submit(ler, uf)
            abertos = len(lista)
            while abertos:
                uf, itens = fila.get()
                if itens is None:
                    abertos -= 1
                    continue
                if isinstance(itens, Exception):
                    n.avisos.append(f"{uf}: {type(itens).__name__}: {itens}"[:200])
                    continue
                for o in itens:
                    chave = primeiro(o, "idUnico", "id")
                    if not chave:
                        continue
                    upsert(db, Registro, {"fonte": "obrasgov", "tipo": "obra", "chave": str(chave)}, {
                        "uf": uf, "titulo": primeiro(o, "nome", "descricao"),
                        "valor": _valor_previsto(o),
                        "dados": o,
                    })
                    n += 1
                db.commit()
    return n.itens
