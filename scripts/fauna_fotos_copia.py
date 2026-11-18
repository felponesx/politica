"""Grava as fotos dos animais ameaçados na cópia estática, no pacote do Meio ambiente (p/ambiente.json), sem mexer nas partes s<N>.

    python -m scripts.fauna_fotos_copia [site/dados]

(O Artifact tem limite de 512 arquivos: por isso as fotos não ganham arquivo próprio.)

Antes, rode python -m scripts.fauna_fotos (gera app/dados/fauna_fotos*). As fotos vão em data URI (WebP de 200 px),
então o pacote só é baixado quando a aba Animais é aberta.
"""
import json
import sys
from pathlib import Path

from app import lacunas

CHAVE = "/ambiente/animais/fotos"


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    dado = lacunas.animais_fotos()
    if not dado:
        raise SystemExit("sem fotos: rode primeiro python -m scripts.fauna_fotos")
    pac = pasta / "p" / "ambiente.json"
    P = json.loads(pac.read_text(encoding="utf-8")) if pac.exists() else {}
    P[CHAVE] = dado
    pac.write_text(json.dumps(P, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    ch = man.setdefault("pacotes", {}).setdefault("p/ambiente.json", {"chaves": []})["chaves"]
    if CHAVE not in ch:
        ch.append(CHAVE)
        ch.sort()
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(dado)} fotos gravadas em {pac} ({pac.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1:])
