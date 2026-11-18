"""Desmatamento por município: o cálculo (scripts/desmatamento_municipios.py) com shapefiles pequenos e a rota que serve o arquivo gerado."""
import shapefile
from fastapi.testclient import TestClient

from app.main import app
from scripts import desmatamento_municipios as dm


def _quadrado(w, x0, y0, x1, y1):
    w.poly([[[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]])


def _montar(tmp_path):
    # dois municípios lado a lado: A (x 0–1) e B (x 1–2)
    mun = str(tmp_path / "mun")
    w = shapefile.Writer(mun, shapeType=shapefile.POLYGON)
    w.field("CD_MUN", "C", 7)
    _quadrado(w, 0, 0, 1, 1); w.record("1111111")
    _quadrado(w, 1, 0, 2, 1); w.record("2222222")
    w.close()
    pasta = tmp_path / "biomas" / "cerrado"
    pasta.mkdir(parents=True)
    b = shapefile.Writer(str(pasta / "yearly_deforestation_biome_cerrado_v1"), shapeType=shapefile.POLYGON)
    b.field("year", "N", 6)
    b.field("area_km", "N", 18, 6)
    b.field("main_class", "C", 20)
    def f(x0, y0, x1, y1, ano, area, classe="DESMATAMENTO"):
        _quadrado(b, x0, y0, x1, y1); b.record(ano, area, classe)
    f(0.1, 0.1, 0.2, 0.2, 2024, 0.5)            # só em A
    f(1.1, 0.1, 1.2, 0.2, 2024, 0.25)           # só em B
    f(1.3, 0.3, 1.4, 0.4, 2025, 0.75)           # só em B, outro ano
    f(0.5, 0.5, 1.5, 0.9, 2025, 4.0)            # grande (≥ 2 km²): metade em cada município
    f(0.3, 0.3, 0.4, 0.4, 2025, 9.0, "RESERVATORIO")   # não é desmatamento: fica de fora
    f(5, 5, 5.1, 5.1, 2025, 0.2)                # fora de qualquer município
    b.close()
    return mun + ".shp", str(tmp_path / "biomas")


def test_soma_por_municipio_e_ano(tmp_path):
    shp, pasta = _montar(tmp_path)
    r = dm.calcular(shp, pasta)
    a, b = r["municipios"]["1111111"], r["municipios"]["2222222"]
    assert a["2024"] == 0.5 and "2025" in a
    assert b["2024"] == 0.25
    assert round(a["2025"], 2) == 2.0               # metade do polígono grande
    assert round(b["2025"], 2) == 0.75 + 2.0        # o ponto pequeno + a outra metade
    assert r["anos"] == ["2024", "2025"]


def test_confere_com_o_arquivo_e_ignora_o_que_nao_e_desmatamento(tmp_path):
    shp, pasta = _montar(tmp_path)
    info = dm.calcular(shp, pasta)["biomas"]["Cerrado"]
    assert info["feicoes_desmatamento"] == 5          # a reservatório não entra
    assert round(info["km2_arquivo"], 2) == 0.5 + 0.25 + 0.75 + 4.0 + 0.2
    assert round(info["km2_sem_municipio"], 2) == 0.2  # o ponto fora do mapa aparece como "sem município"


def test_rota_sem_arquivo_ou_com_arquivo_valido():
    r = TestClient(app).get("/ambiente/desmatamento-municipios")
    if r.status_code == 404:
        return
    d = r.json()
    assert "INPE" in d["fonte"] and d["unidade"] == "km²" and d["municipios"]
    for cod, por in list(d["municipios"].items())[:300]:
        assert len(cod) == 7 and cod.isdigit()
        assert all(a in d["anos"] and v > 0 for a, v in por.items())
