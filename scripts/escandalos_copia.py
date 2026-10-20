"""Acrescenta os escândalos (app/dados/escandalos) a uma cópia estática já pronta, sem refazer a exportação.

    python -m scripts.escandalos_copia [site/dados]

O robô grava os escândalos junto da cópia (FIXAS em scripts/exportar_snapshot.py); este script serve para
atualizar a cópia quando um caso for corrigido ou acrescentado.
"""
import json
import sys
from pathlib import Path

from app import escandalos
from scripts.exportar_snapshot import fnv1a


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    n = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))["shards"]
    novos = {"/escandalos": escandalos.listar()} | {f"/escandalos/{s}": c for s, c in escandalos.casos().items()}
    por_shard = {}
    for k, v in novos.items():
        por_shard.setdefault(fnv1a(k) % n, {})[k] = v
    for i, itens in por_shard.items():
        arq = pasta / f"s{i}.json"
        shard = json.loads(arq.read_text(encoding="utf-8"))
        for k in [k for k in shard if k.startswith("/escandalos/") and k not in novos]:
            del shard[k]  # caso que saiu
        shard.update(itens)
        arq.write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(novos) - 1} escândalos gravados em {len(por_shard)} arquivo(s) de {pasta}")


if __name__ == "__main__":
    main(sys.argv[1:])
