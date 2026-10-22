"""Logos dos batalhões enviados à mão: tira o fundo branco e grava em site/midia/logos.json.

Coloque as imagens em site/midia/batalhoes/ com o nome UF-SIGLA (ex.: SP-ROTA.png, RJ-BOPE.jpg, BR-COT.png) e rode:
  python -m scripts.logos_batalhoes
O fundo branco é removido só a partir das bordas (o branco dentro do brasão continua), a imagem é recortada no
desenho e reduzida para até 256 px de altura. A chave no site é u:UF:SIGLA (a mesma dos cartões das unidades).
Nome começando com "_" vira a chave direta, trocando "_" por ":" (ex.: _pm_SP.png → pm:SP, brasão da corporação;
_g_pc.png → g:pc, distintivo geral da Polícia Civil, usado quando o estado não tem logo próprio e na linha do país).
"""
import base64
import io
import os
import sys
from collections import deque

from PIL import Image

PASTA = "site/midia/batalhoes"
LOGOS = "site/midia/logos.json"
ALTURA = 256
TITULOS = {"g:pm": "Polícia Militar", "g:pc": "Polícia Civil", "g:pp": "Polícia Penal", "g:gcm": "Guarda Municipal",
           "g:cbm": "Corpo de Bombeiros Militar", "g:cbm-distintivo": "Bombeiro Militar", "g:pericia": "Polícia Científica",
           "g:leg": "Polícia Legislativa", "pm:SP": "Polícia Militar do Estado de São Paulo"}


def sem_fundo(im: Image.Image, tol: int = 38) -> Image.Image:
    """Fundo claro ligado às bordas vira transparente (preenchimento a partir das bordas)."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    claro = lambda p: p[3] < 20 or (p[0] > 255 - tol and p[1] > 255 - tol and p[2] > 255 - tol)
    visto = bytearray(w * h)
    fila = deque()
    for x in range(w):
        fila.extend(((x, 0), (x, h - 1)))
    for y in range(h):
        fila.extend(((0, y), (w - 1, y)))
    while fila:
        x, y = fila.popleft()
        i = y * w + x
        if visto[i]:
            continue
        visto[i] = 1
        p = px[x, y]
        if not claro(p):
            continue
        px[x, y] = (p[0], p[1], p[2], 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not visto[ny * w + nx]:
                fila.append((nx, ny))
    caixa = im.getbbox()
    return im.crop(caixa) if caixa else im


def data_uri(im: Image.Image) -> str:
    if im.height > ALTURA:
        im = im.resize((max(1, round(im.width * ALTURA / im.height)), ALTURA), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def main(pasta=PASTA, logos=LOGOS):
    from scripts.logos_arquivo import gravar, ler
    L = ler(logos)
    feitos = []
    for nome in sorted(os.listdir(pasta)):
        base, ext = os.path.splitext(nome)
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            continue
        if base.startswith("_"):
            chave = base[1:].replace("_", ":")
        elif "-" in base:
            uf, sigla = base.split("-", 1)
            chave = f"u:{uf.upper()}:{sigla}"
        else:
            continue
        titulo = TITULOS.get(chave, chave.split(":")[-1])
        try:
            im = sem_fundo(Image.open(os.path.join(pasta, nome)))
        except Exception as e:
            print(f"pulei {nome}: {e}")
            continue
        L.setdefault("policias", {})[chave] = {
            "img": data_uri(im), "titulo": titulo, "arquivo": f"enviado pelo BRASIL+ ({nome})", "pagina": ""}
        feitos.append(chave)
    gravar(logos, L)
    print(f"{len(feitos)} logos: {', '.join(feitos)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
