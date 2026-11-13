"""Contas e voto nas leis: CPF, senha, sessão, uma conta = um voto por lei, cookie e falha fechada sem CPF_PEPPER."""
from datetime import timedelta
import uuid

import pytest
from fastapi.testclient import TestClient

from app import contas
from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Conta, Proposicao, Sessao, VotoLei

PEPPER = "x" * 40
CPF_OK = "529.982.247-25"  # dígitos verificadores válidos (exemplo de teste)
CPF_OK2 = "111.444.777-35"


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setattr(settings, "cpf_pepper", PEPPER)
    yield


@pytest.fixture
def cli():
    criar_tabelas()
    c = TestClient(app)
    yield c
    c.cookies.clear()


def _limpa_contas():
    db = SessionLocal()
    try:
        db.query(VotoLei).delete()
        db.query(Sessao).delete()
        db.query(Conta).delete()
        db.query(Proposicao).filter(Proposicao.id_externo.like("teste-lei-%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _contas_limpas():
    _limpa_contas()
    yield
    _limpa_contas()


def _lei():
    db = SessionLocal()
    try:
        p = Proposicao(casa="camara", id_externo=f"tl-{uuid.uuid4().hex[:16]}", sigla_tipo="PL", numero="1", ano=2026, ementa="Lei de teste.")
        db.add(p)
        db.commit()
        return p.id
    finally:
        db.close()


def test_cpf_digitos_verificadores():
    assert contas.cpf_valido(CPF_OK) and contas.cpf_valido(CPF_OK2)
    assert not contas.cpf_valido("111.111.111-11")  # todos iguais
    assert not contas.cpf_valido("529.982.247-26")  # dígito errado
    assert not contas.cpf_valido("123")


def test_senha_guarda_hash_e_confere():
    h = contas.hash_senha("segredo-forte-123")
    assert "segredo-forte-123" not in h
    assert contas.confere_senha("segredo-forte-123", h)
    assert not contas.confere_senha("outra", h)


def test_cadastro_guarda_so_codigo_do_cpf(cli):
    r = cli.post("/contas", json={"email": "Ana@Exemplo.com", "senha": "senha-forte-1", "nome": "Ana Silva", "cpf": CPF_OK, "aceito_termos": True})
    assert r.status_code == 201
    assert "bp_sessao" in r.cookies
    db = SessionLocal()
    try:
        c = db.query(Conta).one()
        assert c.email == "ana@exemplo.com"
        assert CPF_OK.replace(".", "").replace("-", "") not in c.cpf_codigo
        assert c.cpf_codigo == contas.codigo_cpf(CPF_OK)
        assert "senha-forte-1" not in c.senha_hash
    finally:
        db.close()


def test_mesmo_cpf_ou_email_nao_cria_outra_conta(cli):
    assert cli.post("/contas", json={"email": "a@x.com", "senha": "senha-forte-1", "nome": "Ana", "cpf": CPF_OK, "aceito_termos": True}).status_code == 201
    r = cli.post("/contas", json={"email": "outro@x.com", "senha": "senha-forte-1", "nome": "Ana", "cpf": CPF_OK, "aceito_termos": True})
    assert r.status_code == 409
    assert "entre na conta" in r.json()["detail"]  # mensagem genérica
    r2 = cli.post("/contas", json={"email": "a@x.com", "senha": "senha-forte-1", "nome": "Ana", "cpf": CPF_OK2, "aceito_termos": True})
    assert r2.status_code == 409


def test_sem_cpf_pepper_nao_cadastra(cli, monkeypatch):
    monkeypatch.setattr(settings, "cpf_pepper", "")
    r = cli.post("/contas", json={"email": "b@x.com", "senha": "senha-forte-1", "nome": "Bia", "cpf": CPF_OK, "aceito_termos": True})
    assert r.status_code == 503


def test_formulario_sem_json_e_recusado(cli):
    r = cli.post("/contas", data={"email": "c@x.com", "senha": "senha-forte-1", "nome": "Cá", "cpf": CPF_OK, "aceito_termos": True})
    assert r.status_code in (415, 422)  # recusado antes de criar qualquer conta
    db = SessionLocal()
    try:
        assert db.query(Conta).count() == 0
    finally:
        db.close()


def test_login_senha_errada_e_generica(cli):
    cli.post("/contas", json={"email": "d@x.com", "senha": "senha-forte-1", "nome": "Dani", "cpf": CPF_OK, "aceito_termos": True})
    cli.cookies.clear()
    errado = cli.post("/contas/entrar", json={"email": "d@x.com", "senha": "nao-e"})
    inexistente = cli.post("/contas/entrar", json={"email": "ninguem@x.com", "senha": "nao-e"})
    assert errado.status_code == inexistente.status_code == 401
    assert errado.json() == inexistente.json()


def test_sessao_expirada_nao_vale(cli):
    cli.post("/contas", json={"email": "e@x.com", "senha": "senha-forte-1", "nome": "Edu", "cpf": CPF_OK, "aceito_termos": True})
    db = SessionLocal()
    try:
        for s in db.query(Sessao).all():
            s.expira_em = contas.agora_utc() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    assert cli.get("/contas/eu").json()["conta"] is None


def test_voto_uma_vez_por_lei_e_pode_mudar(cli):
    pid = _lei()
    cli.post("/contas", json={"email": "f@x.com", "senha": "senha-forte-1", "nome": "Fe", "cpf": CPF_OK, "aceito_termos": True})
    assert cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "aprovo"}).status_code == 200
    assert cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "indeferido"}).status_code == 200
    r = cli.get(f"/votos-leis?ids={pid}").json()["leis"][str(pid)]
    assert r["total"] == 1 and r["contagem"]["indeferido"] == 1 and r["meu_voto"] == "indeferido"


def test_contagem_dupla_nao_existe_com_duas_contas(cli):
    pid = _lei()
    cli.post("/contas", json={"email": "g@x.com", "senha": "senha-forte-1", "nome": "Gi", "cpf": CPF_OK, "aceito_termos": True})
    cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "aprovo"})
    cli.post("/contas/sair", json={})
    cli.cookies.clear()
    cli.post("/contas", json={"email": "h@x.com", "senha": "senha-forte-1", "nome": "Ha", "cpf": CPF_OK2, "aceito_termos": True})
    cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "nao_aprovo"})
    r = cli.get(f"/votos-leis?ids={pid}").json()["leis"][str(pid)]
    assert r["total"] == 2 and r["contagem"] == {"aprovo": 1, "nao_aprovo": 1, "indeferido": 0}


def test_votar_sem_login_e_negado(cli):
    pid = _lei()
    r = cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "aprovo"})
    assert r.status_code == 401


def test_opcao_fora_da_lista_e_recusada(cli):
    pid = _lei()
    cli.post("/contas", json={"email": "i@x.com", "senha": "senha-forte-1", "nome": "Ivo", "cpf": CPF_OK, "aceito_termos": True})
    assert cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "talvez"}).status_code == 422


def test_lei_inexistente_nao_recebe_voto(cli):
    cli.post("/contas", json={"email": "j@x.com", "senha": "senha-forte-1", "nome": "Jo", "cpf": CPF_OK, "aceito_termos": True})
    assert cli.post("/proposicoes/999999/voto-lei", json={"opcao": "aprovo"}).status_code == 404


def test_cookie_httponly_e_samesite(cli):
    r = cli.post("/contas", json={"email": "k@x.com", "senha": "senha-forte-1", "nome": "Ka", "cpf": CPF_OK, "aceito_termos": True})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_login_apaga_sessoes_vencidas(cli):
    cli.post("/contas", json={"email": "l@x.com", "senha": "senha-forte-1", "nome": "Lu", "cpf": CPF_OK, "aceito_termos": True})
    db = SessionLocal()
    try:
        for s in db.query(Sessao).all():
            s.expira_em = contas.agora_utc() - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    cli.cookies.clear()
    assert cli.post("/contas/entrar", json={"email": "l@x.com", "senha": "senha-forte-1"}).status_code == 200
    db = SessionLocal()
    try:
        assert db.query(Sessao).count() == 1  # só a sessão nova; as vencidas foram apagadas
    finally:
        db.close()


def test_sentry_fica_desligado_sem_dsn(monkeypatch):
    from app import observabilidade
    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert observabilidade.iniciar() is False


def test_cadastro_exige_aceite_dos_termos(cli):
    r = cli.post("/contas", json={"email": "m@x.com", "senha": "senha-forte-1", "nome": "Mi", "cpf": CPF_OK})
    assert r.status_code == 400
    r = cli.post("/contas", json={"email": "m@x.com", "senha": "senha-forte-1", "nome": "Mi", "cpf": CPF_OK, "aceito_termos": True})
    assert r.status_code == 201
    db = SessionLocal()
    try:
        c = db.query(Conta).one()
        assert c.termos_versao == contas.TERMOS_VERSAO and c.termos_aceitos_em is not None
    finally:
        db.close()


# ---------- conta Google e área do administrador ----------

GOOGLE_ID = "123.apps.googleusercontent.com"


@pytest.fixture
def google_ok(monkeypatch):
    """Simula o Google: o token 'bom|<sub>|<email>|<nome>' é aceito; qualquer outro é recusado."""
    monkeypatch.setattr(settings, "google_client_id", GOOGLE_ID)
    monkeypatch.setattr(settings, "admin_emails", "dona@exemplo.com")

    def falso(credencial):
        if not credencial.startswith("bom|"):
            raise contas.ErroConta("Login do Google recusado. Entre de novo.", 401)
        _, sub, email, nome = credencial.split("|")
        return {"sub": sub, "email": email, "nome": nome}
    monkeypatch.setattr(contas, "verificar_google", falso)
    yield


def test_google_config_e_desligado_sem_client_id(cli, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    assert cli.get("/contas/google-config").json() == {"client_id": None}


def test_google_primeiro_acesso_pede_cpf_e_depois_cria(cli, google_ok):
    cred = "bom|sub-1|ana@exemplo.com|Ana Silva"
    r = cli.post("/contas/google", json={"credential": cred}, headers={"content-type": "application/json"})
    assert r.status_code == 409 and r.json()["precisa_cadastro"] is True
    r2 = cli.post("/contas/google", json={"credential": cred, "cpf": CPF_OK, "aceito_termos": True},
                  headers={"content-type": "application/json"})
    assert r2.status_code == 201 and r2.json()["conta"]["nome"] == "Ana Silva"
    assert "bp_sessao" in r2.headers.get("set-cookie", "")
    db = SessionLocal()
    try:
        c = db.query(Conta).filter(Conta.google_sub == "sub-1").one()
        assert c.senha_hash is None and c.cpf_codigo != CPF_OK and c.papel == "usuario"
    finally:
        db.close()


def test_google_recusa_token_invalido_e_sem_aceite(cli, google_ok):
    assert cli.post("/contas/google", json={"credential": "lixo"}, headers={"content-type": "application/json"}).status_code == 401
    r = cli.post("/contas/google", json={"credential": "bom|sub-2|bia@exemplo.com|Bia", "cpf": CPF_OK, "aceito_termos": False},
                 headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_conta_so_google_nao_entra_com_senha(cli, google_ok):
    cli.post("/contas/google", json={"credential": "bom|sub-3|caio@exemplo.com|Caio", "cpf": CPF_OK, "aceito_termos": True},
             headers={"content-type": "application/json"})
    cli.cookies.clear()
    r = cli.post("/contas/entrar", json={"email": "caio@exemplo.com", "senha": "qualquer-senha"}, headers={"content-type": "application/json"})
    assert r.status_code == 401


def test_google_com_email_de_conta_existente_liga_a_mesma_conta(cli, google_ok):
    cli.post("/contas", json={"email": "dani@exemplo.com", "senha": "senha-forte-1", "nome": "Dani", "cpf": CPF_OK2, "aceito_termos": True},
             headers={"content-type": "application/json"})
    cli.cookies.clear()
    r = cli.post("/contas/google", json={"credential": "bom|sub-4|dani@exemplo.com|Dani"}, headers={"content-type": "application/json"})
    assert r.status_code == 200
    cli.cookies.clear()
    assert cli.post("/contas/entrar", json={"email": "dani@exemplo.com", "senha": "senha-forte-1"}, headers={"content-type": "application/json"}).status_code == 200


def test_admin_por_lista_e_area_so_para_admin(cli, google_ok):
    # quem não é admin não entra na área
    cli.post("/contas", json={"email": "comum@exemplo.com", "senha": "senha-forte-1", "nome": "Comum", "cpf": CPF_OK2, "aceito_termos": True},
             headers={"content-type": "application/json"})
    assert cli.get("/admin/resumo").status_code == 403
    cli.cookies.clear()
    assert cli.get("/admin/resumo").status_code == 401
    # a dona (em ADMIN_EMAILS) entra e vira administradora
    cli.post("/contas", json={"email": "dona@exemplo.com", "senha": "senha-forte-1", "nome": "Dona", "cpf": CPF_OK, "aceito_termos": True},
             headers={"content-type": "application/json"})
    eu = cli.get("/contas/eu").json()
    assert eu["admin"] is True and eu["conta"]["papel"] == "admin"
    r = cli.get("/admin/resumo")
    assert r.status_code == 200 and r.json()["administradores"] >= 1 and "ultimas_contas" in r.json()


def test_perfil_salva_e_valida(cli):
    cli.post("/contas", json={"email": "perfil@exemplo.com", "senha": "senha-forte-1", "nome": "Lia Souza", "cpf": CPF_OK, "aceito_termos": True},
             headers={"content-type": "application/json"})
    h = {"content-type": "application/json"}
    r = cli.post("/contas/perfil", json={"data_nascimento": "1990-05-10", "uf": "pr", "cidade": " Curitiba ", "interesses": ["saude", "seguranca"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["perfil"] == {"data_nascimento": "1990-05-10", "uf": "PR", "cidade": "Curitiba", "interesses": ["saude", "seguranca"]}
    eu = cli.get("/contas/eu").json()
    assert eu["perfil"]["uf"] == "PR" and eu["perfil"]["interesses"] == ["saude", "seguranca"]


def test_perfil_recusa_dados_invalidos(cli):
    cli.post("/contas", json={"email": "perfil2@exemplo.com", "senha": "senha-forte-1", "nome": "Rui Lima", "cpf": CPF_OK2, "aceito_termos": True},
             headers={"content-type": "application/json"})
    h = {"content-type": "application/json"}
    assert cli.post("/contas/perfil", json={"uf": "XX"}, headers=h).status_code == 400
    assert cli.post("/contas/perfil", json={"interesses": ["inventado"]}, headers=h).status_code == 400
    assert cli.post("/contas/perfil", json={"data_nascimento": "2020-01-01"}, headers=h).status_code == 400  # menor de 16
    cli.cookies.clear()
    assert cli.post("/contas/perfil", json={"uf": "SP"}, headers=h).status_code == 401


def test_limite_de_cadastro_devolve_429_e_nao_erro_interno(monkeypatch):
    """Passou do limite de tentativas: a resposta é 429 com Retry-After (antes dava AttributeError e 'Erro interno')."""
    from fastapi.testclient import TestClient

    from app import limites
    from app.main import app

    monkeypatch.setattr(limites, "consumir", lambda chave, limite, janela: limites.Resultado(False, limite + 1, limite, 42))
    r = TestClient(app).post("/contas", json={"email": "a@b.co", "senha": "x" * 12, "nome": "Teste", "cpf": "0", "aceito_termos": True})
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "42"
