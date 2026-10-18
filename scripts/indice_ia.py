"""Acrescenta o índice da IA (/ia/indice) a uma cópia estática já pronta, sem refazer a exportação.

    python -m scripts.indice_ia [site/dados]

O robô monta o índice sozinho (scripts/exportar_snapshot.py); este script serve para atualizar uma cópia antiga.
"""
import json
import sys
from pathlib import Path

from app.ia_indice import montar
from scripts.exportar_snapshot import _json, fnv1a

CHAVE = "/ia/indice"


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    manifest = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    n = manifest["shards"]
    dados = {}
    for i in range(n):
        dados.update(json.loads((pasta / f"s{i}.json").read_text(encoding="utf-8")))
    novo = CHAVE not in dados
    dados.pop(CHAVE, None)
    indice = montar(dados)
    alvo = pasta / f"s{fnv1a(CHAVE) % n}.json"
    shard = json.loads(alvo.read_text(encoding="utf-8"))
    antes = len(alvo.read_bytes())
    shard[CHAVE] = indice
    texto = json.dumps(shard, ensure_ascii=False, separators=(",", ":"), default=_json)
    alvo.write_text(texto, encoding="utf-8")
    manifest["bytes"] = manifest.get("bytes", 0) - antes + len(texto.encode())
    manifest["consultas"] = manifest.get("consultas", 0) + (1 if novo else 0)
    (pasta / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    m = indice["mandatos"]["itens"]
    print(f"{alvo.name}: gastos {len(indice['gastos']['itens'])}, pessoas {len(m)}, "
          f"cargos com mais votados {len(indice['mais_votados']['por_cargo'])}, "
          f"{len(json.dumps(indice, ensure_ascii=False)) / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
