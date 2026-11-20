"""Grava a interiorização, depressão e trabalho por aplicativo (GET /populacao/extra) na cópia estática, na parte s<N>.

    python -m scripts.habitantes_copia [site/dados]

Antes, rode python -m scripts.habitantes_extra.
"""
import json
import sys
from pathlib import Path

from app import habitantes
from scripts.exportar_snapshot import fnv1a

CHAVE = "/populacao/extra"


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    dado = habitantes.extra()
    if not dado:
        raise SystemExit("rode primeiro: python -m scripts.habitantes_extra")
    arq = pasta / f"s{fnv1a(CHAVE) % man['shards']}.json"
    shard = json.loads(arq.read_text(encoding="utf-8"))
    shard[CHAVE] = dado
    arq.write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{CHAVE} gravada em {arq.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
