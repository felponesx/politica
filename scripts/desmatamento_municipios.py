"""Desmatamento do PRODES por município e por ano, a partir dos shapefiles de cada bioma (INPE/TerraBrasil) e da malha municipal do IBGE.

Uso:
    python -m scripts.desmatamento_municipios <BR_Municipios_2025.shp> <pasta_com_os_shapefiles_dos_biomas> [saida.json]

A pasta tem uma subpasta por bioma (amazonia, cerrado, caatinga, mata, pantanal, pampa), cada uma com o .shp/.dbf do arquivo
`yearly_deforestation_biome_<bioma>_v<data>.zip` já extraído (https://terrabrasilis.dpi.inpe.br/downloads/).

Método: só feições com main_class = DESMATAMENTO. Cada polígono vai para o município que contém o seu ponto central; polígonos grandes
(≥ 2 km²) são repartidos pela área que cai em cada município. A soma de cada bioma é conferida contra a soma do próprio arquivo
(o que não cai em nenhum município sai em `sem_municipio`). A área é a `area_km` do INPE.
Resultado em app/dados/desmatamento_municipio.json (lido por GET /ambiente/desmatamento-municipios).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import shapefile
import shapely
from shapely import make_valid
from shapely.geometry import shape
from shapely.strtree import STRtree

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "desmatamento_municipio.json"
BIOMAS = {"amazonia": "Amazônia", "cerrado": "Cerrado", "caatinga": "Caatinga", "mata": "Mata Atlântica", "pantanal": "Pantanal", "pampa": "Pampa"}
TOLERANCIA_MUN = 0.0003
GRANDE_KM2 = 2.0
ANO_MIN = 2008            # a Amazônia só tem mapa anual completo desde 2008; antes disso o arquivo ficaria grande sem servir ao mapa
LOTE = 200_000


def _municipios(shp: str):
    rm = shapefile.Reader(shp, encoding="utf-8")
    campos = [f[0] for f in rm.fields[1:]]
    ic = campos.index("CD_MUN")
    cods, geoms = [], []
    for sr in rm.iterShapeRecords():
        g = shape(sr.shape.__geo_interface__)
        if not g.is_valid:
            g = make_valid(g)
        cods.append(str(sr.record[ic]))
        geoms.append(g.simplify(TOLERANCIA_MUN, preserve_topology=True))
    return cods, geoms


def _centro(sh) -> tuple[float, float]:
    """Média dos vértices do polígono (rápida; o erro é pequeno perto do tamanho de um município)."""
    p = np.asarray(sh.points)
    return float(p[:, 0].mean()), float(p[:, 1].mean())


def _arquivo(pasta: Path) -> Path:
    shp = sorted(pasta.glob("*.shp"))
    if not shp:
        raise SystemExit(f"sem .shp em {pasta}")
    return shp[0]


def _atribuir(xs, ys, arvore, geoms, n_mun):
    """Índice do município de cada ponto (-1 = nenhum)."""
    pontos = shapely.points(np.asarray(xs), np.asarray(ys))
    pares = arvore.query(pontos, predicate="within")
    out = np.full(len(pontos), -1, dtype=np.int64)
    out[pares[0]] = pares[1]
    return out


def processar_bioma(arq: Path, arvore, geoms, cods) -> dict:
    r = shapefile.Reader(str(arq), encoding="latin-1")
    campos = [f[0] for f in r.fields[1:]]
    iy, ia, ic = campos.index("year"), campos.index("area_km"), campos.index("main_class")
    soma_arquivo: dict[int, float] = defaultdict(float)
    mun: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    sem: dict[int, float] = defaultdict(float)
    xs, ys, anos, areas = [], [], [], []
    grandes = []

    def descarrega():
        if not xs:
            return
        idx = _atribuir(xs, ys, arvore, geoms, len(cods))
        for k, j in enumerate(idx):
            if j >= 0:
                mun[cods[j]][anos[k]] += areas[k]
            else:
                sem[anos[k]] += areas[k]
        xs.clear(); ys.clear(); anos.clear(); areas.clear()

    n = 0
    for sr in r.iterShapeRecords():
        rec = sr.record
        if str(rec[ic]).upper() != "DESMATAMENTO":
            continue
        try:
            ano, area = int(rec[iy]), float(rec[ia] or 0)
        except (TypeError, ValueError):
            continue
        if area <= 0:
            continue
        n += 1
        soma_arquivo[ano] += area
        if area >= GRANDE_KM2:
            grandes.append((ano, area, sr.shape))
            continue
        x, y = _centro(sr.shape)
        xs.append(x); ys.append(y); anos.append(ano); areas.append(area)
        if len(xs) >= LOTE:
            descarrega()
    descarrega()
    # polígonos grandes: repartidos pela área em cada município
    for ano, area, sh in grandes:
        g = shape(sh.__geo_interface__)
        if not g.is_valid:
            g = make_valid(g)
        partes = {}
        for j in arvore.query(g):
            a = g.intersection(geoms[int(j)]).area
            if a > 0:
                partes[int(j)] = a
        tot = sum(partes.values())
        if tot <= 0:
            sem[ano] += area
            continue
        g_area = g.area
        for j, a in partes.items():
            mun[cods[j]][ano] += area * a / g_area
        resto = max(0.0, 1 - tot / g_area)
        if resto > 0.001:
            sem[ano] += area * resto
    return {"feicoes": n, "soma_arquivo": dict(soma_arquivo), "mun": mun, "sem": dict(sem)}


def calcular(shp_mun: str, pasta: str) -> dict:
    cods, geoms = _municipios(shp_mun)
    arvore = STRtree(geoms)
    saida_mun: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    biomas_info = {}
    for chave, nome in BIOMAS.items():
        d = Path(pasta) / chave
        if not d.exists():
            continue
        arq = _arquivo(d)
        print(f"{nome}: lendo {arq.name}", flush=True)
        res = processar_bioma(arq, arvore, geoms, cods)
        for cod, por_ano in res["mun"].items():
            for a, v in por_ano.items():
                saida_mun[cod][a] += v
        total = sum(res["soma_arquivo"].values())
        sem = sum(res["sem"].values())
        biomas_info[nome] = {"arquivo": arq.name, "feicoes_desmatamento": res["feicoes"], "km2_arquivo": round(total, 1),
                             "km2_sem_municipio": round(sem, 1), "anos": sorted(res["soma_arquivo"])}
        print(f"  {res['feicoes']} feições, {total:,.0f} km² no arquivo, {sem:,.1f} km² sem município", flush=True)
    anos = sorted({a for v in saida_mun.values() for a in v if a >= ANO_MIN})
    municipios = {c: {str(a): round(v, 2) for a, v in sorted(por.items()) if a >= ANO_MIN and v >= 0.005} for c, por in sorted(saida_mun.items())}
    municipios = {c: v for c, v in municipios.items() if v}
    return {
        "fonte": "INPE/TerraBrasilis PRODES (desmatamento anual por bioma, shapefiles) + IBGE Malha Municipal 2025",
        "metodo": "Área de desmatamento (main_class = DESMATAMENTO) de cada polígono atribuída ao município que contém o seu ponto central; polígonos de 2 km² ou mais "
                  "são repartidos pela área em cada município. Vale para os anos que cada bioma publica (nem todos fecham o mesmo ano e alguns anos antigos não têm mapa).",
        "gerado_em": date.today().isoformat(),
        "unidade": "km²",
        "anos": [str(a) for a in anos],
        "biomas": biomas_info,
        "formato": "municipios[codigo_ibge][ano] = km² desmatados no município naquele ano (só o que passa de 0)",
        "municipios": municipios,
    }


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(__doc__)
    r = calcular(argv[0], argv[1])
    destino = Path(argv[2]) if len(argv) > 2 else SAIDA
    destino.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(r['municipios'])} municípios com desmatamento, anos {r['anos'][0]}–{r['anos'][-1]} → {destino} ({destino.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main(sys.argv[1:])
