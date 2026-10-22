"""Redistribui uma cópia estática já pronta no formato atual (SHARDS grupos + respostas grandes em g/), sem refazer a
exportação. Uso: python -m scripts.reorganizar_copia [site/dados]"""
import json
import sys
from pathlib import Path

from scripts.exportar_snapshot import GRANDE, SHARDS, gravar_partes


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    manifest = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    dados = {}
    for arq in sorted(pasta.glob("s*.json")):
        for k, v in json.loads(arq.read_text(encoding="utf-8")).items():
            if isinstance(v, dict) and set(v) == {"__arquivo"}:
                v = json.loads((pasta / v["__arquivo"]).read_text(encoding="utf-8"))
            dados[k] = v
    for arq in list(pasta.glob("s*.json")) + list((pasta / "g").glob("*.json")):
        arq.unlink()
    manifest["bytes"] = gravar_partes(pasta, dados)
    manifest["shards"] = SHARDS
    (pasta / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    grandes = len(list((pasta / "g").glob("*.json")))
    print(f"{len(dados)} consultas em {SHARDS} arquivos + {grandes} respostas grandes (> {GRANDE // 1000} KB) em g/")


if __name__ == "__main__":
    main(sys.argv[1:])
