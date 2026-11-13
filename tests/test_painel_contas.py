"""Login e acessos do painel: papéis (comum, leitor, editor, admin), permissões por pessoa, bloqueio, e a sessão valendo como a chave
nas ações de escrita. As contas são as do site (cookie de sessão)."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from app import contas, painel_acesso
from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Conta, Sessao

SENHA = "senha-forte-1"
EMAILS = ["zzt-comum@exemplo.com", "zzt-leitor@exemplo.com", "zzt-editor@exemplo.com", "zzt-admin@exemplo.com", "zzt-admin2@exemplo.com"]


@pytest.fixture(autouse=True)
def _limpo(monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")
    monkeypatch.setattr(settings, "admin_padrao", False)
    criar_tabelas()

    def apaga():
        with SessionLocal() as db:
            ids = [c.id for c in db.query(Conta).filter(Conta.email.in_(EMAILS))]
            if ids:
                db.query(Sessao).filter(Sessao.conta_id.in_(ids)).delete(synchronize_session=False)
            db.query(Conta).filter(Conta.email.in_(EMAILS)).delete(synchronize_session=False)
            db.commit()
    apaga()
    yield
    apaga()


def _conta(email, papel="usuario", **extra):
    with SessionLocal() as db:
        c = Conta(email=email, nome=email.split("@")[0], senha_hash=contas.hash_senha(SENHA), papel=papel,
                  cpf_codigo=hashlib.sha256(email.encode()).hexdigest(), **extra)
        db.add(c)
        db.commit()
        return c.id


def _entra(email):
    c = TestClient(app)
    r = c.post("/contas/entrar", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    return c


def test_conta_comum_nao_tem_painel_nem_escreve():
    _conta(EMAILS[0])
    c = _entra(EMAILS[0])
    assert c.get("/contas/eu").json()["painel"] is None
    assert c.post("/organizar", json={"texto": "https://a.gov.br/x.csv"}).status_code == 403
    assert TestClient(app).post("/organizar", json={"texto": "https://a.gov.br/x.csv"}).status_code == 401   # sem sessão nem chave
    assert c.get("/painel/contas").status_code == 403


def test_leitor_olha_mas_nao_altera():
    _conta(EMAILS[1], "leitor")
    c = _entra(EMAILS[1])
    p = c.get("/contas/eu").json()["painel"]
    assert p["bots"] == "ver" and p["acessos"] == ""
    assert c.post("/organizar", json={"texto": "https://a.gov.br/x.csv"}).status_code == 403


def test_editor_cadastra_pela_sessao_mas_nao_mexe_em_acessos():
    ide = _conta(EMAILS[2], "editor")
    c = _entra(EMAILS[2])
    assert c.post("/organizar", json={"texto": "https://a.gov.br/x.csv"}).status_code == 200      # sessão vale como a chave
    assert c.get("/painel/contas").status_code == 403
    assert c.post(f"/painel/contas/{ide}", json={"papel": "admin"}).status_code == 403            # nem a si mesmo


def test_administrador_gerencia_acessos():
    adm, ide = _conta(EMAILS[3], "admin"), _conta(EMAILS[2], "usuario")
    c = _entra(EMAILS[3])
    lista = c.get("/painel/contas").json()
    assert [x["email"] for x in lista["contas"]] == [EMAILS[3]] and "editor" in [p["id"] for p in lista["papeis"]]
    achado = c.get("/painel/contas", params={"q": "zzt-editor"}).json()["contas"]
    assert [x["id"] for x in achado] == [ide]
    # promove a editor e tira só a seção IA
    r = c.post(f"/painel/contas/{ide}", json={"papel": "editor", "permissoes": {"ia": ""}})
    assert r.status_code == 200 and r.json()["permissoes"]["bots"] == "alterar" and r.json()["permissoes"]["ia"] == "" and r.json()["personalizada"]
    editor = _entra(EMAILS[2])
    assert editor.get("/contas/eu").json()["painel"]["ia"] == ""
    # "acessos" nunca vira "alterar" para quem não é admin, nem se gravarem isso à força
    c.post(f"/painel/contas/{ide}", json={"permissoes": {"acessos": "alterar"}})
    assert _entra(EMAILS[2]).get("/contas/eu").json()["painel"]["acessos"] == ""
    # bloqueia: perde o painel na hora; liberar volta
    assert c.post(f"/painel/contas/{ide}", json={"bloqueada": True}).json()["bloqueada"] is True
    assert editor.get("/contas/eu").json()["painel"] is None
    assert editor.post("/organizar", json={"texto": "https://a.gov.br/x.csv"}).status_code == 403
    c.post(f"/painel/contas/{ide}", json={"bloqueada": False, "redefinir": True})
    assert editor.get("/contas/eu").json()["painel"]["ia"] == "alterar"
    assert adm


def test_regras_de_seguranca_dos_acessos():
    adm = _conta(EMAILS[3], "admin")
    c = _entra(EMAILS[3])
    assert c.post(f"/painel/contas/{adm}", json={"papel": "leitor"}).status_code == 409           # não rebaixa a si mesmo
    assert c.post(f"/painel/contas/{adm}", json={"bloqueada": True}).status_code == 409
    assert c.post("/painel/contas/999999", json={"papel": "leitor"}).status_code == 404
    assert c.post(f"/painel/contas/{adm}", json={"papel": "dono"}).status_code in (409, 422)
    outro = _conta(EMAILS[4], "usuario")
    assert c.post(f"/painel/contas/{outro}", json={"papel": "dono"}).status_code == 422
    assert c.post(f"/painel/contas/{outro}", content="papel=admin", headers={"content-type": "text/plain"}).status_code in (415, 422)   # só JSON


def test_email_do_arquivo_de_configuracao_continua_admin(monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", EMAILS[4])
    outro = _conta(EMAILS[4], "usuario")
    _conta(EMAILS[3], "admin")
    c = _entra(EMAILS[3])
    assert c.post(f"/painel/contas/{outro}", json={"papel": "leitor"}).status_code == 409
    assert painel_acesso.papel_efetivo(Conta(email=EMAILS[4], papel="usuario")) == "admin"


def test_chave_do_administrador_continua_valendo(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "t" * 30)
    r = TestClient(app).post("/organizar", json={"texto": "https://a.gov.br/x.csv"}, headers={"X-Admin-Token": "t" * 30})
    assert r.status_code == 200
