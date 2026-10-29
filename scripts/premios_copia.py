"""Acrescenta /premios a uma cópia estática pronta.

    python -m scripts.premios_copia [site/dados]
"""
import json
import sys
from pathlib import Path

from app import premios
from scripts.exportar_snapshot import fnv1a


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    n = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))["shards"]
    arq = pasta / f"s{fnv1a('/premios') % n}.json"
    shard = json.loads(arq.read_text(encoding="utf-8"))
    shard["/premios"] = premios.dados()
    arq.write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("premios gravado em", arq)


if __name__ == "__main__":
    main(sys.argv[1:])
