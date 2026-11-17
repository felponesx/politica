"""Bioma de cada município (IBGE): arquivo gerado por scripts/bioma_municipios.py e a rota que o serve."""
from fastapi.testclient import TestClient

from app.main import app


def _dado():
    r = TestClient(app).get("/ambiente/bioma-municipios")
    assert r.status_code == 200
    return r.json()


def test_rota_devolve_biomas_e_fonte():
    d = _dado()
    assert d["biomas"] == ["Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"]
    assert "IBGE" in d["fonte"] and d["metodo"]
    assert len(d["municipios"]) >= 5500            # 5.573 municípios na malha de 2025
    assert d["sem_bioma"] == []


def test_codigos_com_sete_digitos_e_porcentagens_validas():
    d = _dado()
    n = len(d["biomas"])
    for cod, v in d["municipios"].items():
        assert len(cod) == 7 and cod.isdigit()
        assert 0 <= v[0] < n and 0 < v[1] <= 100
        if len(v) > 2:                              # município em divisa: segundo bioma, diferente do primeiro
            assert v[2] != v[0] and 0 < v[3] <= 50 and v[1] + v[3] <= 100.2


def test_cidades_conhecidas_no_bioma_certo():
    d = _dado()
    nome = lambda cod: d["biomas"][d["municipios"][cod][0]]
    assert nome("1302603") == "Amazônia"           # Manaus
    assert nome("1721000") == "Cerrado"            # Palmas
    assert nome("3550308") == "Mata Atlântica"     # São Paulo
    assert nome("2312908") == "Caatinga"           # Sobral
    assert nome("4314407") == "Pampa"              # Pelotas
    assert nome("5003207") == "Pantanal"           # Corumbá
