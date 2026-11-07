"""Conta de teste admin/admin: só em desenvolvimento, some quando existe outro administrador ou com ADMIN_PADRAO=false."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Conta, Sessao, VotoLei

JSON = {"content-type": "application/json"}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(settings, "cpf_pepper", "x" * 40)
    monkeypatch.setattr(settings, "admin_padrao", True)
    monkeypatch.setattr(settings, "admin_emails", "")
    criar_tabelas()
    c = TestClient(app)
    yield c
    c.cookies.clear()


@pytest.fixture(autouse=True)
def _limpa():
    def limpar():
        db = SessionLocal()
        try:
            db.query(VotoLei).delete()
            db.query(Sessao).delete()
            db.query(Conta).delete()
            db.commit()
        finally:
            db.close()
    limpar()
    yield
    limpar()


def _entrar(cli, email="admin", senha="admin"):
    return cli.post("/contas/entrar", json={"email": email, "senha": senha}, headers=JSON)


def test_admin_admin_entra_e_e_administrador(cli):
    assert _entrar(cli).status_code == 200
    eu = cli.get("/contas/eu").json()
    assert eu["admin"] is True and eu["conta"]["conta_teste"] is True
    assert cli.get("/admin/resumo").status_code == 200


def test_senha_errada_nao_entra(cli):
    assert _entrar(cli, senha="outra").status_code == 401


def test_desligada_com_admin_padrao_falso(cli, monkeypatch):
    monkeypatch.setattr(settings, "admin_padrao", False)
    assert _entrar(cli).status_code == 401


def test_deixa_de_valer_quando_existe_outro_administrador(cli, monkeypatch):
    assert _entrar(cli).status_code == 200  # entra e fica com sessão
    monkeypatch.setattr(settings, "admin_emails", "dono@exemplo.com")
    cli.post("/contas", json={"email": "dono@exemplo.com", "senha": "senha-forte-1", "nome": "Dono", "cpf": "529.982.247-25", "aceito_termos": True}, headers=JSON)
    cli.cookies.clear()
    assert _entrar(cli).status_code == 401  # login de teste fechado
    assert cli.get("/admin/resumo").status_code == 401
