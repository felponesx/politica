"""Painel de coletas em /painel: página própria do BRASIL+ (lê /fontes/status e /coletas), sem nada carregado de fora."""
from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)


def test_painel_abre_e_tem_politica_de_seguranca():
    r = cliente.get("/painel")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Content-Security-Policy" in r.headers and "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "Coletas do BRASIL+" in r.text


def test_painel_nao_carrega_nada_de_fora():
    corpo = cliente.get("/painel").text
    assert "http://" not in corpo.replace("http://www.w3.org", "")
    assert 'src="http' not in corpo and "src='http" not in corpo
    assert "/fontes/status" in corpo and "/coletas?limit=30" in corpo
