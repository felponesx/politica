"""Categoria "Pessoas e recordes" da aba Prêmios: cada item tem ano, resultado, quem recebeu e fonte (https)."""
from fastapi.testclient import TestClient

from app import premios
from app.main import app


def _pessoas():
    d = premios.dados()
    return [c for c in d["categorias"] if c["slug"] == "pessoas"][0]


def test_todo_item_tem_ano_resultado_quem_e_fonte_https():
    c = _pessoas()
    assert c["total"] == 13 + 12 + 79 + 8 + 3 - 0  # grupos antigos (13) + Grammy (12) + Grammy Latino (79) + F1 (8) + Bola de Ouro da Copa (3)
    for g in c["grupos"]:
        assert g["fonte"].startswith("https://"), g["nome"]
        for e in g["brasil"]:
            assert isinstance(e["ano"], int) and 1800 < e["ano"] < 2100
            assert e["resultado"] and e["detalhe"]


def test_casos_verificados_nas_fontes():
    detalhes = [e["detalhe"] for g in _pessoas()["grupos"] for e in g["brasil"]]
    assert any(d.startswith("Peter Medawar") and "Rio de Janeiro" in d for d in detalhes)   # Nobel: base oficial
    assert any(d.startswith("Artur Ávila") for d in detalhes)                               # Medalha Fields 2014
    bola = [(e["ano"], e["detalhe"]) for g in _pessoas()["grupos"] if g["nome"].startswith("Bola de Ouro") for e in g["brasil"]]
    assert (1997, "Ronaldo") in bola and (1999, "Rivaldo") in bola and (2005, "Ronaldinho") in bola and (2007, "Kaká") in bola


def test_rota_premios_traz_a_categoria_pessoas():
    r = TestClient(app).get("/premios")
    assert r.status_code == 200
    assert any(c["slug"] == "pessoas" for c in r.json()["categorias"])


def test_grupos_novos_e_fonte_por_item():
    nomes = [g["nome"] for g in _pessoas()["grupos"]]
    for n in ["Grammy (EUA)", "Grammy Latino", "Campeões mundiais de Fórmula 1", "Bola de Ouro da Copa do Mundo"]:
        assert n in nomes, n
    for g in _pessoas()["grupos"]:
        for e in g["brasil"]:
            assert e.get("fonte", g["fonte"]).startswith("https://"), (g["nome"], e)
    f1 = [e["detalhe"] for g in _pessoas()["grupos"] if g["nome"].startswith("Campeões") for e in g["brasil"]]
    assert f1.count("Ayrton Senna") == 3 and f1.count("Nelson Piquet") == 3 and f1.count("Emerson Fittipaldi") == 2
