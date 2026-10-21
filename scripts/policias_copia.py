"""Acrescenta as fichas das polícias (app/dados/policias) a uma cópia estática já pronta, sem refazer a exportação.

    python -m scripts.policias_copia [site/dados] [arquivo_isp.csv]

Para a PM do Rio, soma a base do ISP-RJ por área de batalhão (baixa da internet se o arquivo não for informado).
O robô grava as fichas junto da cópia (FIXAS em scripts/exportar_snapshot.py).
"""
import json
import sys
from pathlib import Path

from app import policias
from app.collectors import isp_rj
from scripts.exportar_snapshot import fnv1a


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    bruto = Path(argv[1]).read_bytes() if len(argv) > 1 else isp_rj.baixar()
    por = isp_rj.agregar(isp_rj.ler(bruto))
    n = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))["shards"]
    novos = {"/policias": policias.listar()} | {f"/policias/{s}": policias.ficha(s, por if s == "pm-RJ" else None) for s in policias.fichas()}
    por_shard = {}
    for k, v in novos.items():
        por_shard.setdefault(fnv1a(k) % n, {})[k] = v
    for i in range(n):
        arq = pasta / f"s{i}.json"
        shard = json.loads(arq.read_text(encoding="utf-8"))
        velhas = [k for k in shard if k.startswith("/policias/") and k not in novos]
        if not velhas and i not in por_shard:
            continue
        for k in velhas:
            del shard[k]
        shard.update(por_shard.get(i, {}))
        arq.write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(novos) - 1} fichas de polícia gravadas em {pasta}")


if __name__ == "__main__":
    main(sys.argv[1:])
