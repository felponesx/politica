"""Auditoria de 01/11/2026: acesso direto às rotas administrativas, segredos em mensagens de erro, CORS e cabeçalhos."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.limpeza import mascarar
from app.main import app

c = TestClient(app, raise_server_exceptions=False)


def test_post_coletas_sem_token_e_recusado():
    assert c.post("/coletas/camara").status_code in (401, 403, 422)


def test_post_coletas_token_errado_e_recusado(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "x" * 40)
    r = c.post("/coletas/camara", headers={"x-admin-token": "errado-errado-errado-errado-errado"})
    assert r.status_code in (401, 403, 429)


def test_token_fraco_nao_libera(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "troque-este-token")
    r = c.post("/coletas/camara", headers={"x-admin-token": "troque-este-token"})
    assert r.status_code == 403


def test_nenhuma_rota_de_escrita_alem_das_conhecidas():
    def rotas(lista):
        # FastAPI 0.16x guarda cada include_router num invólucro (_IncludedRouter) com o roteador original dentro
        for r in lista:
            dentro = getattr(r, "original_router", None)
            if dentro is not None:
                yield from rotas(dentro.routes)
            else:
                yield r
    escrita = {(m, r.path) for r in rotas(app.routes) for m in (getattr(r, "methods", None) or ()) if m not in ("GET", "HEAD", "OPTIONS")}
    assert len(list(rotas(app.routes))) > 100  # a lista precisa ver as rotas de verdade, não só as do topo
    # escritas da API: coleta (token de admin), IA e busca (limites), e contas (login por senha, sessão por cookie, voto por lei com limite)
    assert escrita == {("POST", "/coletas/{tarefa}"), ("POST", "/ia/web"), ("POST", "/busca/web"),
                       ("POST", "/contas"), ("POST", "/contas/entrar"), ("POST", "/contas/google"), ("POST", "/contas/perfil"), ("POST", "/contas/sair"),
                       ("POST", "/admin/publicacoes"), ("POST", "/admin/publicacoes/{pid}"), ("POST", "/admin/publicacoes/{pid}/apagar"), ("POST", "/admin/midia"), ("POST", "/admin/configurar"), ("POST", "/proposicoes/{pid}/voto-lei"),
                       # cadastros e aprovações: todos exigem o token de administrador (X-Admin-Token)
                       ("POST", "/fontes-cadastradas"), ("POST", "/fontes-cadastradas/{fonte_id}"), ("POST", "/oportunidades"),
                       ("POST", "/oportunidades/{oid}/aprovar"), ("POST", "/oportunidades/{oid}/rejeitar"), ("POST", "/organizar"),
                       # acesso ao painel: só por sessão de administrador (tests/test_painel_contas.py)
                       ("POST", "/painel/contas/{conta_id}")}


def test_cors_nao_aceita_escrita_de_outra_origem():
    r = c.options("/coletas/x", headers={"Origin": "https://mau.example", "Access-Control-Request-Method": "POST"})
    assert "POST" not in r.headers.get("access-control-allow-methods", "")
    assert "access-control-allow-credentials" not in r.headers


def test_cabecalhos_de_seguranca_no_site_e_na_api():
    r = c.get("/")
    for h in ("content-security-policy", "x-content-type-options", "referrer-policy", "permissions-policy"):
        assert h in r.headers
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


@pytest.mark.parametrize("texto,nao_pode", [
    ("falhou com api_key=ABCDEF123456 na chamada", "ABCDEF123456"),
    ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
    ("GET https://api.exemplo.gov.br/x?chave=SEGREDO123&ano=2024 deu 500", "SEGREDO123"),
    ("FileNotFoundError: /home/user/politica/.env.local", "/home/user"),
    ("token 0123456789abcdef0123456789abcdef0123", "0123456789abcdef0123456789abcdef0123"),
])
def test_mascarar_esconde_segredos_e_caminhos(texto, nao_pode):
    assert nao_pode not in mascarar(texto)


def test_mascarar_mantem_mensagem_util():
    assert "500" in mascarar("HTTP 500 em https://api.exemplo.gov.br/x") and mascarar(None) is None


def test_arquivo_local_fora_da_pasta_permitida_e_recusado(monkeypatch):
    from app.routers.dados import _arquivo_permitido
    assert not _arquivo_permitido("/etc/passwd")
    assert not _arquivo_permitido("../../etc/passwd")
