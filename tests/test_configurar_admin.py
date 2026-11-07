"""Página para tornar administrador uma conta já criada (sem terminal): desligada sem chave forte."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Conta, Sessao, VotoLei

CHAVE = "k" * 40
JSON = {"content-type": "application/json"}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(settings, "cpf_pepper", "x" * 40)
    criar_tabelas()
    yield TestClient(app)


@pytest.fixture(autouse=True)
def _limpa():
    def limpar():
        db = SessionLocal()
        try:
            db.query(VotoLei).delete()
            db.query(Sessao).delete()
            db.query(Conta).filter(Conta.email.like("%@setup-teste.example")).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
    limpar()
    yield
    limpar()


def test_desligada_sem_chave(cli, monkeypatch):
    monkeypatch.setattr(settings, "setup_admin_token", "")
    assert cli.get("/admin/configurar").status_code == 404
    assert cli.post("/admin/configurar", json={"chave": "x", "email": "a@setup-teste.example"}, headers=JSON).status_code == 404


def test_chave_errada_nao_promove(cli, monkeypatch):
    monkeypatch.setattr(settings, "setup_admin_token", CHAVE)
    r = cli.post("/admin/configurar", json={"chave": "errada", "email": "a@setup-teste.example"}, headers=JSON)
    assert r.status_code == 403


def test_promove_conta_criada_e_pede_criar_se_nao_existe(cli, monkeypatch):
    monkeypatch.setattr(settings, "setup_admin_token", CHAVE)
    assert cli.post("/admin/configurar", json={"chave": CHAVE, "email": "novo@setup-teste.example"}, headers=JSON).status_code == 404
    cli.post("/contas", json={"email": "dona@setup-teste.example", "senha": "senha-forte-1", "nome": "Dona", "cpf": "529.982.247-25", "aceito_termos": True}, headers=JSON)
    r = cli.post("/admin/configurar", json={"chave": CHAVE, "email": "dona@setup-teste.example"}, headers=JSON)
    assert r.status_code == 200 and r.json()["ok"] is True
    db = SessionLocal()
    try:
        assert db.query(Conta).filter(Conta.email == "dona@setup-teste.example").one().papel == "admin"
    finally:
        db.close()


def test_pagina_aparece_so_com_chave_forte(cli, monkeypatch):
    monkeypatch.setattr(settings, "setup_admin_token", CHAVE)
    r = cli.get("/admin/configurar")
    assert r.status_code == 200 and "Tornar administrador" in r.text
