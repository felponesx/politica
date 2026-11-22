"""Acrescenta à cópia estática a fauna ameaçada (/ambiente/animais), plantas e fungos (/ambiente/plantas) e a superfície de água (/ambiente/agua)
e o desmatamento por município (/ambiente/desmatamento-municipios).

    python -m scripts.ambiente_extra_copia [site/dados]

Grava as chaves na parte s<N>, no pacote p/ambiente.json e no manifest. Antes, gere os arquivos com
python -m scripts.fauna_ameacada, python -m scripts.agua_superficie e python -m scripts.desmatamento_municipios.
"""
import json
import sys
from pathlib import Path

from app import lacunas
from scripts.exportar_snapshot import fnv1a

CHAVES = {"/ambiente/animais": lacunas.animais_ameacados, "/ambiente/agua": lacunas.agua_superficie,
          "/ambiente/desmatamento-municipios": lacunas.desmatamento_municipios,
          "/ambiente/agua/municipios": lacunas.agua_municipios, "/ambiente/plantas": lacunas.plantas_ameacadas,
          "/ambiente/plantas/fotos": lacunas.plantas_fotos,
          "/ambiente/especies-municipios": lacunas.especies_municipios}


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    pac = pasta / "p" / "ambiente.json"
    P = json.loads(pac.read_text(encoding="utf-8")) if pac.exists() else {}
    ch = man.setdefault("pacotes", {}).setdefault("p/ambiente.json", {"chaves": []})["chaves"]
    for chave, fn in CHAVES.items():
        dado = fn()
        if not dado:
            raise SystemExit(f"sem dados para {chave}: rode os scripts de geração")
        arq = pasta / f"s{fnv1a(chave) % man['shards']}.json"
        shard = json.loads(arq.read_text(encoding="utf-8"))
        shard[chave] = dado
        arq.write_text(json.dumps(shard, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        P[chave] = dado
        if chave not in ch:
            ch.append(chave)
        print(f"{chave} gravada em {arq.name}")
    ch.sort()
    pac.write_text(json.dumps(P, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
