"""Mini-mapas dos biomas (silhueta do país em cinza + o bioma em destaque), para o seletor de bioma do site.

Uso: python -m scripts.bioma_mini            # grava app/dados/bioma_mini.json
Usa a malha municipal do IBGE e o bioma dominante de cada município (app/dados/bioma_municipio.json). É só um desenho
pequeno (município em divisa vai inteiro para o bioma dominante): não serve para medir área.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import httpx
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

RAIZ = Path(__file__).resolve().parent.parent
BIO = RAIZ / "app" / "dados" / "bioma_municipio.json"
SAIDA = RAIZ / "app" / "dados" / "bioma_mini.json"
IBGE = ("https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR?formato=application/vnd.geo+json"
        "&intrarregiao=municipio&qualidade=minima")
ALTURA = 100.0          # altura do desenho; a largura segue a proporção do país
TOLERANCIA = 0.12       # graus: simplificação forte (é um ícone)


def _baixar() -> dict:
    cli = httpx.Client(headers={"User-Agent": "BRASILMais/1.0 (site de dados abertos)"}, timeout=300, follow_redirects=True)
    for t in range(6):
        try:
            r = cli.get(IBGE)
            if r.status_code == 200:
                return r.json()
        except Exception:  # noqa: BLE001
            pass
        import time
        time.sleep(3 * (t + 1))
    raise SystemExit("malha do IBGE indisponível")


def _poligonos(g):
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for x in getattr(g, "geoms", []) for p in _poligonos(x)]


def main() -> None:
    bio = json.loads(BIO.read_text(encoding="utf-8"))
    nomes = bio["biomas"]
    por_bioma: dict[str, list] = {n: [] for n in nomes}
    todos = []
    for f in _baixar()["features"]:
        g = shape(f["geometry"])
        todos.append(g)
        m = bio["municipios"].get(str(f["properties"]["codarea"]))
        if m:
            por_bioma[nomes[m[0]]].append(g)
    pais = unary_union(todos).simplify(TOLERANCIA, preserve_topology=True)
    x0, y0, x1, y1 = pais.bounds
    k = math.cos(math.radians(-14))          # longitude encolhe com a latitude
    esc = ALTURA / (y1 - y0)
    larg = (x1 - x0) * k * esc

    def caminho(geom) -> str:
        partes = []
        for p in _poligonos(geom):
            if p.area < TOLERANCIA ** 2 * 1.5:
                continue                       # ilhotas minúsculas somem no ícone
            pts = list(p.exterior.coords)
            partes.append("M" + "L".join(f"{(x - x0) * k * esc:.1f} {(y1 - y) * esc:.1f}" for x, y in pts) + "Z")
        return "".join(partes)

    saida = {"w": round(larg, 1), "h": ALTURA, "pais": caminho(pais)}
    for n, gs in por_bioma.items():
        if gs:
            saida[n] = caminho(unary_union(gs).simplify(TOLERANCIA, preserve_topology=True))
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print({k_: (len(v) if isinstance(v, str) else v) for k_, v in saida.items()}, "→", SAIDA.name)


if __name__ == "__main__":
    main()
