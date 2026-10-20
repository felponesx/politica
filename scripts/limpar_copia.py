"""Padroniza textos e siglas de partido de uma cópia estática já pronta (site/dados), sem refazer a exportação.

    python -m scripts.limpar_copia [site/dados]

O robô já grava a cópia limpa (scripts/exportar_snapshot.py); este script serve para atualizar uma cópia antiga.
"""
import json
import sys
from pathlib import Path

from app.limpeza import limpar


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    n = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))["shards"]
    mudou = 0
    for i in range(n):
        arq = pasta / f"s{i}.json"
        antes = arq.read_text(encoding="utf-8")
        depois = json.dumps(limpar(json.loads(antes)), ensure_ascii=False, separators=(",", ":"))
        if depois != antes:
            arq.write_text(depois, encoding="utf-8")
            mudou += 1
    print(f"{mudou} de {n} arquivos padronizados em {pasta}")


if __name__ == "__main__":
    main(sys.argv[1:])
