"""Bioma de cada município, por sobreposição de área entre a malha municipal e os biomas do IBGE.

Uso:
    python -m scripts.bioma_municipios <BR_Municipios_2025.shp> <lm_bioma_250.shp> [saida.json]

Fontes (IBGE, sem chave):
  - malha municipal: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil/BR_Municipios_2025.zip
  - biomas 1:250.000: https://geoftp.ibge.gov.br/informacoes_ambientais/estudos_ambientais/biomas/vetores/Biomas_250mil.zip

Para cada município calcula quanto da área cai em cada bioma e guarda o bioma dominante e a sua parte (%). Município que
cruza dois biomas guarda também o segundo (a tela diz que a cor é a do bioma que cobre mais área). A área é a do desenho
em graus: dentro de um município a escala não muda, então a proporção entre biomas é a mesma da área real.
O resultado fica em app/dados/bioma_municipio.json (lido por GET /ambiente/bioma-municipios).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import shapefile
from shapely import make_valid
from shapely.geometry import shape
from shapely.strtree import STRtree

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "bioma_municipio.json"
TOLERANCIA_BIOMA = 0.002      # ≈ 220 m: acelera a conta sem mudar a divisa que se vê no mapa
TOLERANCIA_MUN = 0.0008


def _geom(sh, tol: float):
    g = shape(sh.__geo_interface__)
    if not g.is_valid:
        g = make_valid(g)
    return g.simplify(tol, preserve_topology=True)


def calcular(shp_mun: str, shp_bioma: str) -> dict:
    rb = shapefile.Reader(shp_bioma, encoding="utf-8")
    nomes = []
    geoms = []
    for sr in rb.iterShapeRecords():
        nomes.append(str(sr.record[0]))
        geoms.append(_geom(sr.shape, TOLERANCIA_BIOMA))
    idx = {n: i for i, n in enumerate(nomes)}
    arvore = STRtree(geoms)

    rm = shapefile.Reader(shp_mun, encoding="utf-8")
    campos = [f[0] for f in rm.fields[1:]]
    ic = campos.index("CD_MUN")
    out: dict[str, list] = {}
    sem_bioma = []
    for sr in rm.iterShapeRecords():
        cod = str(sr.record[ic])
        g = _geom(sr.shape, TOLERANCIA_MUN)
        if g.is_empty:
            sem_bioma.append(cod)
            continue
        areas = {}
        for j in arvore.query(g):
            a = g.intersection(geoms[int(j)]).area
            if a > 0:
                areas[int(j)] = a
        tot = sum(areas.values())
        if tot <= 0:
            sem_bioma.append(cod)
            continue
        ordem = sorted(areas.items(), key=lambda kv: -kv[1])
        item = [ordem[0][0], round(ordem[0][1] / tot * 100, 1)]
        if len(ordem) > 1 and ordem[1][1] / tot >= 0.05:      # só guarda o segundo bioma quando passa de 5% do município
            item += [ordem[1][0], round(ordem[1][1] / tot * 100, 1)]
        out[cod] = item
    return {
        "fonte": "IBGE: Biomas do Brasil 1:250.000 e Malha municipal 2025 (geoftp.ibge.gov.br)",
        "metodo": "Bioma que cobre a maior área do município (sobreposição dos polígonos). Município em divisa guarda também o segundo bioma.",
        "gerado_em": date.today().isoformat(),
        "biomas": nomes,
        "formato": "municipios[codigo_ibge] = [bioma_dominante, % da área, (segundo_bioma, % da área)]; os números são posições em 'biomas'",
        "municipios": out,
        "sem_bioma": sem_bioma,
        "_idx": idx,
    }


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    r = calcular(argv[0], argv[1])
    r.pop("_idx")
    destino = Path(argv[2]) if len(argv) > 2 else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(r['municipios'])} municípios, {len(r['sem_bioma'])} sem bioma → {destino}")


if __name__ == "__main__":
    main(sys.argv[1:])
