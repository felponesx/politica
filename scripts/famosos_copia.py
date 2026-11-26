"""Grava na cópia estática a aba Artistas e famosos num pacote só dela: p/famosos.json.

Uso: python -m scripts.famosos_copia [site/dados]
Chaves: /famosos/base (todas as pessoas; a tela filtra no navegador), /famosos/resumo e /famosos/fotos/0..4 (um pacote por arquivo de fotos: p/famosos-fotos-N.json).
Precisa de app/dados/famosos.json (python -m scripts.famosos). Não mexe nas partes s<N>: a tela lê só o pacote (telas famosos e famoso).
A base vai comprimida (gzip em base64, `{"__gz": …}`) e o site descomprime no navegador, como em Pesquisas.
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

from app import famosos  # noqa: E402

ARQ = "p/famosos.json"
TELAS = ["famosos", "famoso"]


def gravar(pasta: Path) -> None:
    base, resumo = famosos.base(), famosos.resumo()
    if base is None:
        raise SystemExit("Sem app/dados/famosos.json. Rode: python -m scripts.famosos")
    bruto = json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    d = {"/famosos/base": {"__gz": base64.b64encode(gzip.compress(bruto, 9)).decode("ascii")}, "/famosos/resumo": resumo}
    (pasta / ARQ).parent.mkdir(exist_ok=True)
    (pasta / ARQ).write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    man.setdefault("pacotes", {})[ARQ] = {"chaves": sorted(d), "telas": TELAS}
    # fotos: um arquivo por tipo de pessoa (famosos.arquivo_da_foto), baixado só quando a tela precisa dele
    for n in range(famosos.N_FOTOS):
        f = famosos.fotos(n) or {}
        arq = f"p/famosos-fotos-{n}.json"
        (pasta / arq).write_text(json.dumps({f"/famosos/fotos/{n}": f}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        man["pacotes"][arq] = {"chaves": [f"/famosos/fotos/{n}"], "telas": TELAS}
        print(f"{arq}: {len(f)} fotos, {(pasta / arq).stat().st_size // 1024} KB")
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ARQ}: {len(d)} chaves, {(pasta / ARQ).stat().st_size // 1024} KB")


if __name__ == "__main__":
    gravar(Path(sys.argv[1] if len(sys.argv) > 1 else "site/dados"))
