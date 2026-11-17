"""Acrescenta à cópia estática o bioma de cada município (/ambiente/bioma-municipios), sem refazer a exportação.

    python -m scripts.bioma_copia [site/dados]

Grava a chave na parte s<N> e no pacote p/ambiente.json (e no manifest). Depois de gerar o arquivo com
python -m scripts.bioma_municipios, rode este script e publique os arquivos alterados.
"""
import json
import sys
from pathlib import Path

from app import lacunas
from scripts.exportar_snapshot import fnv1a

CHAVE = "/ambiente/bioma-municipios"


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    dado = lacunas.bioma_municipios()
    if not dado:
        raise SystemExit("rode primeiro: python -m scripts.bioma_municipios <malha.shp> <biomas.shp>")
    arq = pasta / f"s{fnv1a(CHAVE) % man['shards']}.json"
    shard = json.loads(arq.read_text(encoding="utf-8"))
    shard[CHAVE] = dado
    arq.write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pac = pasta / "p" / "ambiente.json"
    P = json.loads(pac.read_text(encoding="utf-8")) if pac.exists() else {}
    P[CHAVE] = dado
    pac.write_text(json.dumps(P, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ch = man.setdefault("pacotes", {}).setdefault("p/ambiente.json", {"chaves": []})["chaves"]
    if CHAVE not in ch:
        ch.append(CHAVE)
        ch.sort()
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(dado['municipios'])} municípios gravados em {arq.name}, p/ambiente.json e manifest.json")


if __name__ == "__main__":
    main(sys.argv[1:])
