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
        p = Proposicao(casa="camara", id_externo=f"teste-lei-{uuid.uuid4().hex}", sigla_tipo="PL", numero="1", ano=2026, ementa="Lei de teste.")
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
    r = cli.post("/contas", json={"email": "Ana@Exemplo.com", "senha": "senha-forte-1", "nome": "Ana Silva", "cpf": CPF_OK})
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
    assert cli.post("/contas", json={"email": "a@x.com", "senha": "senha-forte-1", "nome": "Ana", "cpf": CPF_OK}).status_code == 201
    r = cli.post("/contas", json={"email": "outro@x.com", "senha": "senha-forte-1", "nome": "Ana", "cpf": CPF_OK})
    assert r.status_code == 409
    assert "entre na conta" in r.json()["detail"]  # mensagem genérica
    r2 = cli.post("/contas", json={"email": "a@x.com", "senha": "senha-forte-1", "nome": "Ana", "cpf": CPF_OK2})
    assert r2.status_code == 409


def test_sem_cpf_pepper_nao_cadastra(cli, monkeypatch):
    monkeypatch.setattr(settings, "cpf_pepper", "")
    r = cli.post("/contas", json={"email": "b@x.com", "senha": "senha-forte-1", "nome": "Bia", "cpf": CPF_OK})
    assert r.status_code == 503


def test_formulario_sem_json_e_recusado(cli):
    r = cli.post("/contas", data={"email": "c@x.com", "senha": "senha-forte-1", "nome": "Cá", "cpf": CPF_OK})
    assert r.status_code in (415, 422)  # recusado antes de criar qualquer conta
    db = SessionLocal()
    try:
        assert db.query(Conta).count() == 0
    finally:
        db.close()


def test_login_senha_errada_e_generica(cli):
    cli.post("/contas", json={"email": "d@x.com", "senha": "senha-forte-1", "nome": "Dani", "cpf": CPF_OK})
    cli.cookies.clear()
    errado = cli.post("/contas/entrar", json={"email": "d@x.com", "senha": "nao-e"})
    inexistente = cli.post("/contas/entrar", json={"email": "ninguem@x.com", "senha": "nao-e"})
    assert errado.status_code == inexistente.status_code == 401
    assert errado.json() == inexistente.json()


def test_sessao_expirada_nao_vale(cli):
    cli.post("/contas", json={"email": "e@x.com", "senha": "senha-forte-1", "nome": "Edu", "cpf": CPF_OK})
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
    cli.post("/contas", json={"email": "f@x.com", "senha": "senha-forte-1", "nome": "Fe", "cpf": CPF_OK})
    assert cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "aprovo"}).status_code == 200
    assert cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "indeferido"}).status_code == 200
    r = cli.get(f"/votos-leis?ids={pid}").json()["leis"][str(pid)]
    assert r["total"] == 1 and r["contagem"]["indeferido"] == 1 and r["meu_voto"] == "indeferido"


def test_contagem_dupla_nao_existe_com_duas_contas(cli):
    pid = _lei()
    cli.post("/contas", json={"email": "g@x.com", "senha": "senha-forte-1", "nome": "Gi", "cpf": CPF_OK})
    cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "aprovo"})
    cli.post("/contas/sair", json={})
    cli.cookies.clear()
    cli.post("/contas", json={"email": "h@x.com", "senha": "senha-forte-1", "nome": "Ha", "cpf": CPF_OK2})
    cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "nao_aprovo"})
    r = cli.get(f"/votos-leis?ids={pid}").json()["leis"][str(pid)]
    assert r["total"] == 2 and r["contagem"] == {"aprovo": 1, "nao_aprovo": 1, "indeferido": 0}


def test_votar_sem_login_e_negado(cli):
    pid = _lei()
    r = cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "aprovo"})
    assert r.status_code == 401


def test_opcao_fora_da_lista_e_recusada(cli):
    pid = _lei()
    cli.post("/contas", json={"email": "i@x.com", "senha": "senha-forte-1", "nome": "Ivo", "cpf": CPF_OK})
    assert cli.post(f"/proposicoes/{pid}/voto-lei", json={"opcao": "talvez"}).status_code == 422


def test_lei_inexistente_nao_recebe_voto(cli):
    cli.post("/contas", json={"email": "j@x.com", "senha": "senha-forte-1", "nome": "Jo", "cpf": CPF_OK})
    assert cli.post("/proposicoes/999999/voto-lei", json={"opcao": "aprovo"}).status_code == 404


def test_cookie_httponly_e_samesite(cli):
    r = cli.post("/contas", json={"email": "k@x.com", "senha": "senha-forte-1", "nome": "Ka", "cpf": CPF_OK})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_login_apaga_sessoes_vencidas(cli):
    cli.post("/contas", json={"email": "l@x.com", "senha": "senha-forte-1", "nome": "Lu", "cpf": CPF_OK})
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
