"""Grava as fotos dos animais ameaçados na cópia estática, num pacote próprio (p/fauna.json), sem mexer nas partes s<N>.

    python -m scripts.fauna_fotos_copia [site/dados]

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
    pac = pasta / "p" / "fauna.json"
    pac.parent.mkdir(parents=True, exist_ok=True)
    pac.write_text(json.dumps({CHAVE: dado}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pk = man.setdefault("pacotes", {})
    entrada = pk.setdefault("p/fauna.json", {"chaves": []})
    if CHAVE not in entrada["chaves"]:
        entrada["chaves"].append(CHAVE)
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(dado)} fotos gravadas em {pac} ({pac.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1:])
