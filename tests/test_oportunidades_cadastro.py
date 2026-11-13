"""Cursos, eventos e concursos: cadastro com token, pendente até aprovar, sem duplicar, só aprovado é público."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Oportunidade

TOKEN = "tok-de-teste-com-mais-de-24-caracteres-xyz"
CORPO = {"tipo": "curso", "titulo": "Curso de contas públicas", "orgao": "Escola exemplo", "uf": "df",
         "link": "https://escola.exemplo.gov.br/contas-publicas", "inscricoes_ate": "2026-12-20"}


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    criar_tabelas()
    with SessionLocal() as db:
        db.query(Oportunidade).filter(Oportunidade.link.like("%exemplo.gov.br%")).delete(synchronize_session=False)
        db.commit()
    yield


def test_cadastro_sem_token_e_recusado():
    cliente = TestClient(app)
    assert cliente.post("/oportunidades", json=CORPO).status_code == 422   # sem o cabeçalho X-Admin-Token
    assert cliente.post("/oportunidades", json=CORPO, headers={"X-Admin-Token": "errado-errado-errado-errado-errado"}).status_code == 401


def test_cadastra_pendente_e_so_aprovado_aparece_no_publico():
    cliente = TestClient(app)
    h = {"X-Admin-Token": TOKEN}
    criado = cliente.post("/oportunidades", json=CORPO, headers=h)
    assert criado.status_code == 201 and criado.json()["status"] == "pendente"
    oid = criado.json()["id"]
    publico = [x["id"] for x in cliente.get("/oportunidades", params={"tipo": "curso"}).json()]
    assert oid not in publico
    aprovado = cliente.post(f"/oportunidades/{oid}/aprovar", headers=h).json()
    assert aprovado["status"] == "aprovado" and aprovado["aprovada_em"]
    publico = [x["id"] for x in cliente.get("/oportunidades", params={"tipo": "curso", "uf": "DF"}).json()]
    assert oid in publico


def test_mesmo_link_atualiza_a_ficha_sem_duplicar():
    cliente = TestClient(app)
    h = {"X-Admin-Token": TOKEN}
    primeiro = cliente.post("/oportunidades", json=CORPO, headers=h).json()
    segundo = cliente.post("/oportunidades", json={**CORPO, "titulo": "Curso de contas públicas (turma 2)"}, headers=h).json()
    assert segundo["id"] == primeiro["id"] and segundo["atualizada"] is True
    assert segundo["titulo"].endswith("(turma 2)")


def test_rejeitar_tira_do_publico_e_tipo_invalido_e_recusado():
    cliente = TestClient(app)
    h = {"X-Admin-Token": TOKEN}
    oid = cliente.post("/oportunidades", json={**CORPO, "link": "https://escola.exemplo.gov.br/outro-curso"}, headers=h).json()["id"]
    cliente.post(f"/oportunidades/{oid}/aprovar", headers=h)
    assert cliente.post(f"/oportunidades/{oid}/rejeitar", headers=h).json()["status"] == "rejeitado"
    assert oid not in [x["id"] for x in cliente.get("/oportunidades").json()]
    ruim = cliente.post("/oportunidades", json={**CORPO, "tipo": "palestra", "link": "https://escola.exemplo.gov.br/x-y-z"}, headers=h)
    assert ruim.status_code == 422


def test_pendente_e_rejeitado_so_aparecem_com_o_token():
    cliente = TestClient(app)
    h = {"X-Admin-Token": TOKEN}
    cliente.post("/oportunidades", json={**CORPO, "link": "https://escola.exemplo.gov.br/so-pendente"}, headers=h)
    assert cliente.get("/oportunidades", params={"status": "pendente"}).status_code == 401   # sem token: nada de lista de pendentes
    assert cliente.get("/oportunidades", params={"status": "pendente"}, headers={"X-Admin-Token": "errado-errado-errado-errado-errado"}).status_code == 401
    ok = cliente.get("/oportunidades", params={"status": "pendente"}, headers=h)
    assert ok.status_code == 200 and any(x["link"].endswith("so-pendente") for x in ok.json())
