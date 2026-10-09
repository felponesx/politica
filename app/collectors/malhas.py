"""Contorno dos municípios de cada estado — API de malhas do IBGE (GeoJSON), convertido para caminhos SVG.
Docs: https://servicodados.ibge.gov.br/api/docs/malhas?versao=3
Guardamos o desenho já projetado (x, y em um quadro de 600 de largura) para o site só precisar desenhar.
"""
import math

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, upsert

URL = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf}"
LARGURA = 600


def _aneis(geom):
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon":
        return [c]
    if t == "MultiPolygon":
        return list(c)
    return []


def projetar(geojson: dict) -> dict:
    """{'largura', 'altura', 'municipios': [{'codigo', 'd'}]} a partir de um FeatureCollection."""
    feats = geojson.get("features") or []
    pts = [p for f in feats for pol in _aneis(f.get("geometry")) for anel in pol for p in anel]
    if not pts:
        return {"largura": LARGURA, "altura": 0, "municipios": []}
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    fx = math.cos(math.radians((min(lats) + max(lats)) / 2))
    w = (max(lons) - min(lons)) * fx or 1
    h = max(lats) - min(lats) or 1
    k = LARGURA / w
    altura = round(h * k, 1)
    xy = lambda p: f"{(p[0] - min(lons)) * fx * k:.1f} {(max(lats) - p[1]) * k:.1f}"
    out = []
    for f in feats:
        props = f.get("properties") or {}
        cod = str(props.get("codarea") or props.get("CD_MUN") or f.get("id") or "")
        partes = []
        for pol in _aneis(f.get("geometry")):
            for anel in pol:
                if len(anel) >= 3:
                    partes.append("M" + "L".join(xy(p) for p in anel) + "Z")
        if cod and partes:
            out.append({"codigo": cod, "d": "".join(partes)})
    return {"largura": LARGURA, "altura": altura, "municipios": out}


def coletar_malhas(ufs: list[str] | None = None, qualidade: str = "minima"):
    with registrar_coleta("ibge", "malhas", qualidade=qualidade) as (db, n):
        for uf in ufs or UFS:
            gj = http.get_json(URL.format(uf=uf), params={"formato": "application/vnd.geo+json", "qualidade": qualidade,
                                                           "intrarregiao": "municipio"},
                               headers={"Accept": "application/vnd.geo+json, application/json"}) or {}
            desenho = projetar(gj)
            upsert(db, Registro, {"fonte": "ibge", "tipo": "malha", "chave": uf},
                   {"uf": uf, "titulo": f"Municípios de {uf}", "valor": len(desenho["municipios"]), "dados": desenho})
            db.commit()
            n += 1
    return n.itens
