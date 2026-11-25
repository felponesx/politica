"""Grava na cópia estática a aba Pesquisas num pacote só dela: p/pesquisas.json.

Uso: python -m scripts.pesquisas_copia [site/dados]
Chaves: /pesquisas/base (todos os projetos, listas compactas; a tela filtra no navegador) e /pesquisas/resumo.
Precisa de app/dados/pesquisas.json (python -m scripts.pesquisas). Não mexe nas partes s<N>: a tela lê só o pacote (telas pesquisas, pesquisa e instituto).
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")
os.environ.setdefault("LIMITE_PESADO_POR_MINUTO", "0")

from app import pesquisas  # noqa: E402

ARQ = "p/pesquisas.json"
TELAS = ["pesquisas", "pesquisa", "instituto"]


def gravar(pasta: Path) -> None:
    base, resumo = pesquisas.base(), pesquisas.resumo()
    if base is None:
        raise SystemExit("Sem app/dados/pesquisas.json. Rode: python -m scripts.pesquisas")
    # A cópia estática guarda a base comprimida (gzip em base64): o Artifact tem limite de tamanho total e a base crua passava de 5 MB.
    # O site descomprime no navegador (DecompressionStream). O servidor (GET /pesquisas/base) continua devolvendo o JSON puro.
    # Em colunas (um array por campo) o gzip acha muito mais repetição que em linhas: o pacote cai de 3,3 para ~2,6 MB. O site refaz as linhas (pqBase).
    colunar = {k: v for k, v in base.items() if k != "p"}
    colunar["cols"] = [list(c) for c in zip(*base["p"])]
    bruto = json.dumps(colunar, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    d = {"/pesquisas/base": {"__gz": base64.b64encode(gzip.compress(bruto, 9)).decode("ascii")}, "/pesquisas/resumo": resumo}
    (pasta / ARQ).parent.mkdir(exist_ok=True)
    (pasta / ARQ).write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    man.setdefault("pacotes", {})[ARQ] = {"chaves": sorted(d), "telas": TELAS}
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ARQ}: {len(d)} chaves, {(pasta / ARQ).stat().st_size // 1024} KB")


if __name__ == "__main__":
    gravar(Path(sys.argv[1] if len(sys.argv) > 1 else "site/dados"))
