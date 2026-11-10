"""Reduz as fotos já gravadas nos blocos de site/midia (fotos_<N>.json) para no máximo ALTURA px de altura.

A foto maior aparece com 92 px no celular (cartão do perfil) e as listas usam 42–52 px: 200 px dá nitidez em tela
de densidade 2x até no cartão maior. Os blocos e as chaves não mudam (o site acha a foto pelo mesmo hash); foto que
já está abaixo do limite fica como está. Nunca amplia.

Uso: python -m scripts.reduzir_fotos [site/midia] [altura]
"""
import base64
import glob
import io
import json
import os
import sys

ALTURA = 200
QUALIDADE = 80


def reduzir(uri: str, altura: int = ALTURA) -> str:
    if not isinstance(uri, str) or not uri.startswith("data:image/"):
        return uri
    try:
        from PIL import Image
        bruto = base64.b64decode(uri.split(",", 1)[1])
        im = Image.open(io.BytesIO(bruto))
        if im.height <= altura:
            return uri
        im = im.convert("RGB").resize((max(1, round(im.width * altura / im.height)), altura), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "WEBP", quality=QUALIDADE, method=6)
        return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode() if out.tell() < len(bruto) else uri
    except Exception:
        return uri


def main(argv):
    pasta = argv[0] if argv else "site/midia"
    altura = int(argv[1]) if len(argv) > 1 else ALTURA
    antes = depois = mudou = 0
    for arq in sorted(glob.glob(os.path.join(pasta, "fotos_*.json"))):
        antes += os.path.getsize(arq)
        with open(arq, encoding="utf-8") as f:
            bloco = json.load(f)
        novo = {k: reduzir(v, altura) for k, v in bloco.items()}
        mudou += sum(1 for k in bloco if novo[k] is not bloco[k])
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(novo, f, ensure_ascii=False, separators=(",", ":"))
        depois += os.path.getsize(arq)
    print(f"{mudou} fotos reduzidas para {altura} px; blocos: {antes / 1e6:.1f} MB -> {depois / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
