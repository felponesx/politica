"""Leitura e gravação de site/midia/logos.json em partes leves.

logos.json é só o índice (`grupos` → arquivo de cada grupo, e a lista `unidades`); as imagens ficam em
logos_partidos.json, logos_policias.json, logos_estados.json, logos_veiculos.json e logos_empresas.json, para o site
baixar só o grupo que a tela mostra. Na gravação, cada logo PNG vira WebP (com transparência, qualidade 88) quando fica
menor: os brasões e logos caem para cerca de 1/5 do tamanho, com a mesma altura.
Cópias antigas (tudo dentro de logos.json) continuam sendo lidas.
"""
import base64
import io
import json
import os
from datetime import date

GRUPOS = ("partidos", "policias", "estados", "veiculos", "empresas")
QUALIDADE = 88


def webp(uri: str, qualidade: int = QUALIDADE) -> str:
    """data URI PNG ou JPEG → WebP quando fica menor; o resto volta como está."""
    if not isinstance(uri, str) or not uri.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
        return uri
    try:
        from PIL import Image
        bruto = base64.b64decode(uri.split(",", 1)[1])
        im = Image.open(io.BytesIO(bruto))
        im = im.convert("RGBA" if im.mode in ("P", "LA", "RGBA") or "transparency" in im.info else "RGB")
        out = io.BytesIO()
        im.save(out, "WEBP", quality=qualidade, method=4)
        if out.tell() < len(bruto):
            return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode()
    except Exception:
        pass
    return uri


def ler(arquivo: str) -> dict:
    """logos.json (índice novo ou arquivo único antigo) → dicionário completo, com todos os grupos."""
    with open(arquivo, encoding="utf-8") as f:
        L = json.load(f)
    pasta = os.path.dirname(arquivo)
    for g, nome in (L.pop("grupos", None) or {}).items():
        try:
            with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                L[g] = json.load(f)
        except (OSError, ValueError):
            L[g] = {}
    L.pop("versao", None)
    L.pop("gerado_em", None)
    return L


def gravar(arquivo: str, L: dict) -> dict:
    """Grava o índice e um arquivo por grupo; devolve o tamanho (bytes) de cada arquivo."""
    pasta = os.path.dirname(arquivo)
    idx = {"versao": 2, "gerado_em": date.today().isoformat(), "grupos": {}}
    tam = {}
    for g in GRUPOS:
        itens = {}
        for k, v in (L.get(g) or {}).items():
            if isinstance(v, dict) and v.get("img"):
                v = {**v, "img": webp(v["img"])}
            itens[k] = v
        nome = f"logos_{g}.json"
        with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:
            json.dump(itens, f, ensure_ascii=False, separators=(",", ":"))
        idx["grupos"][g] = nome
        tam[nome] = os.path.getsize(os.path.join(pasta, nome))
    for k, v in L.items():
        if k not in GRUPOS:
            idx[k] = v
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
    tam[os.path.basename(arquivo)] = os.path.getsize(arquivo)
    return tam


if __name__ == "__main__":
    import sys
    arq = sys.argv[1] if len(sys.argv) > 1 else "site/midia/logos.json"
    for nome, n in gravar(arq, ler(arq)).items():
        print(f"{nome}: {n / 1e6:.2f} MB")
