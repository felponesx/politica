from fastapi.testclient import TestClient

from app import organizador
from app.config import settings
from app.main import app

TOKEN = "t" * 30


def test_extrai_links_limpos():
    t = "veja https://dados.gov.br/a.csv, e http://x.org/b. de novo https://dados.gov.br/a.csv e ftp://x e https://u:p@x.com/z"
    assert organizador.extrair_links(t) == ["https://dados.gov.br/a.csv", "http://x.org/b"]


def test_regra_local_categoria_e_formato():
    r = organizador.regra_local("https://www.inpe.br/queimadas/dados.csv")
    assert r["categoria"] == "ambiente" and r["formato"] == "csv"


def test_validacao_rejeita_categoria_invalida():
    assert organizador._valida({"categoria": "x", "formato": "csv"}, "u") is None
    ok = organizador._valida({"categoria": "saude", "formato": "JSON", "intervalo_min": 1}, "u")
    assert ok["intervalo_min"] == 15 and ok["formato"] == "json"


def test_gemini_ruim_cai_na_regra_local(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "x")
    monkeypatch.setattr(organizador, "_gemini", lambda u: [{"url": u[0], "categoria": "inventada", "formato": "csv"}])
    r = organizador.organizar("https://saude.gov.br/x.csv")
    assert r["propostas"][0]["origem"] == "local" and r["propostas"][0]["categoria"] == "saude"


def test_rota_exige_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    c = TestClient(app)
    assert c.post("/organizar", json={"texto": "https://a.gov.br/x"}).status_code == 401
    ok = c.post("/organizar", json={"texto": "https://a.gov.br/x.csv"}, headers={"X-Admin-Token": TOKEN})
    assert ok.status_code == 200 and len(ok.json()["propostas"]) == 1
