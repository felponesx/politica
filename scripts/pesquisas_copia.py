"""Grava na cópia estática a aba Pesquisas num pacote só dela: p/pesquisas.json.

Uso: python -m scripts.pesquisas_copia [site/dados]
Chaves: /pesquisas/base (todos os projetos, listas compactas; a tela filtra no navegador) e /pesquisas/resumo.
Precisa de app/dados/pesquisas.json (python -m scripts.pesquisas). Não mexe nas partes s<N>: a tela lê só o pacote (telas pesquisas, pesquisa e instituto).
"""
from __future__ import annotations

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
    d = {"/pesquisas/base": base, "/pesquisas/resumo": resumo}
    (pasta / ARQ).parent.mkdir(exist_ok=True)
    (pasta / ARQ).write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    man.setdefault("pacotes", {})[ARQ] = {"chaves": sorted(d), "telas": TELAS}
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ARQ}: {len(d)} chaves, {(pasta / ARQ).stat().st_size // 1024} KB")


if __name__ == "__main__":
    gravar(Path(sys.argv[1] if len(sys.argv) > 1 else "site/dados"))
