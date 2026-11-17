"""Fauna ameaçada (MMA 2026) e superfície de água (MapBiomas): arquivos gerados por scripts e rotas que os servem."""
from fastapi.testclient import TestClient

from app.main import app

C = TestClient(app)


def test_animais_totais_fecham():
    r = C.get("/ambiente/animais")
    assert r.status_code == 200
    d = r.json()
    t = d["totais"]
    assert t["especies"] == len(d["especies"]) >= 1200
    assert sum(t["por_categoria"].values()) == t["especies"]
    assert sum(t["por_grupo"].values()) == t["especies"]
    assert set(t["por_categoria"]) <= set(d["categorias"])
    assert "MMA" in d["fonte"] and "2020" in d["metodo"]


def test_animais_campos_e_biomas_validos():
    d = C.get("/ambiente/animais").json()
    n = len(d["campos"])
    for e in d["especies"]:
        assert len(e) == n and e[0] and e[4] in d["categorias"]
        assert all(0 <= b < len(d["biomas"]) for b in e[6])
        if e[10] == 0:                      # sem dados de 2020: não inventa bioma nem estados
            assert e[6] == [] and e[7] == []
        assert e[11] in ("mma", "gbif", "") and bool(e[1]) == bool(e[11])     # nome popular sempre com a origem


def test_animais_conhecidos():
    d = C.get("/ambiente/animais").json()
    por = {e[0]: e for e in d["especies"]}
    onca = por["Panthera onca"]
    assert onca[1] == "Onça-pintada" and onca[2] == "Mamíferos" and onca[4] in ("VU", "EN", "CR")
    assert "Amazônia" in [d["biomas"][b] for b in onca[6]]


def test_agua_series_e_somas():
    r = C.get("/ambiente/agua")
    assert r.status_code == 200
    d = r.json()
    assert d["anos"][0] == "1985" and d["anos"][-1] == "2025" and d["unidade"] == "ha"
    assert len(d["biomas"]) == 6 and len(d["estados"]) == 27 and len(d["regioes_hidrograficas"]) == 12
    u = d["anos"][-1]
    assert d["biomas"]["Amazônia"][u] > d["biomas"]["Caatinga"][u]
    assert abs(sum(v[u] for v in d["biomas"].values()) - d["brasil"][u]) <= 6      # arredondamento por bioma
    assert "comprimento" in d["metodo"]


def test_nomes_populares_completados_pelo_gbif():
    d = C.get("/ambiente/animais").json()
    por = {e[0]: e for e in d["especies"]}
    arara = por["Anodorhynchus hyacinthinus"]                    # arara-azul-grande: fora da base de 2020, nome vem do GBIF
    assert arara[1].lower().startswith("arara-azul") and arara[11] == "gbif" and arara[10] == 0
    t = d["totais"]
    assert t["com_nome_comum"] >= 900 and t["nome_comum_gbif"] > 0
