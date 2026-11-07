"""Comando para criar ou promover o administrador (sem senha no código)."""
import pytest

from app import contas
from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.models import Conta
from scripts.criar_admin import criar_ou_promover

CPF = "529.982.247-25"


@pytest.fixture(autouse=True)
def _pepper(monkeypatch):
    monkeypatch.setattr(settings, "cpf_pepper", "x" * 40)
    criar_tabelas()
    yield


def _limpa():
    db = SessionLocal()
    try:
        db.query(Conta).filter(Conta.email.like("%@admin-teste.example")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _limpo():
    _limpa()
    yield
    _limpa()


def test_cria_admin_novo_com_senha_e_papel():
    db = SessionLocal()
    try:
        assert criar_ou_promover(db, "Dono@admin-teste.example", "Dono Teste", CPF, "senha-forte-1") == "criada"
        c = db.query(Conta).filter(Conta.email == "dono@admin-teste.example").one()
        assert c.papel == "admin" and c.senha_hash and contas.confere_senha("senha-forte-1", c.senha_hash)
        assert c.cpf_codigo != CPF
    finally:
        db.close()


def test_promove_conta_existente_sem_mudar_senha():
    db = SessionLocal()
    try:
        db.add(Conta(email="pessoa@admin-teste.example", senha_hash=contas.hash_senha("outra-senha-1"), cpf_codigo="c" * 64, nome="Pessoa"))
        db.commit()
        assert criar_ou_promover(db, "pessoa@admin-teste.example", "", None, None) == "promovida"
        c = db.query(Conta).filter(Conta.email == "pessoa@admin-teste.example").one()
        assert c.papel == "admin" and contas.confere_senha("outra-senha-1", c.senha_hash)
    finally:
        db.close()


def test_recusa_senha_curta_e_cpf_invalido():
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            criar_ou_promover(db, "x@admin-teste.example", "X", CPF, "curta")
        with pytest.raises(ValueError):
            criar_ou_promover(db, "y@admin-teste.example", "Y", "123", "senha-forte-1")
    finally:
        db.close()
