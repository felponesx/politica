"""Painel de coletas em /painel: página própria do BRASIL+ (lê /fontes/status e /coletas), sem nada carregado de fora.
O visual novo fica em /painel; o anterior (cadastro de fontes, cursos e eventos) em /painel/antigo."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

cliente = TestClient(app)
PAGINAS = ["/painel", "/painel/antigo"]


@pytest.mark.parametrize("caminho", PAGINAS)
def test_painel_abre_e_tem_politica_de_seguranca(caminho):
    r = cliente.get(caminho)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    csp = r.headers["Content-Security-Policy"]   # política própria do painel: nada de fora, só o próprio endereço
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "Coletas do BRASIL+" in r.text


@pytest.mark.parametrize("caminho", PAGINAS)
def test_painel_nao_carrega_nada_de_fora(caminho):
    corpo = cliente.get(caminho).text
    assert "http://" not in corpo.replace("http://www.w3.org", "")
    assert 'src="http' not in corpo and "src='http" not in corpo
    assert "/fontes/status" in corpo


def test_painel_novo_usa_dados_reais_e_nao_leva_dado_de_exemplo():
    corpo = cliente.get("/painel").text
    assert "/coletas?limit=200" in corpo and "/ia/pergunta" in corpo and "/organizar" in corpo
    assert "AMOSTRA" not in corpo and "dados simulados" not in corpo     # nada de dado inventado na página real
    assert "felipe@exemplo.com" not in corpo                              # sem usuário e login de mentira
    assert 'href="/painel/antigo"' in corpo
    assert "/contas/entrar" in corpo and "/painel/contas" in corpo           # login e acessos de verdade (contas do site)
    assert "X-Admin-Token" not in corpo and "bToken" not in corpo            # a página não pede nem guarda a chave: vale a sessão


def test_painel_antigo_continua_com_o_cadastro():
    corpo = cliente.get("/painel/antigo").text
    assert "/coletas?limit=30" in corpo and "/fontes-cadastradas" in corpo
