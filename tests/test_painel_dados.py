"""Dados das abas Correção (coletor) e Instagram: leitura pelo painel, decisões (aprovar/rejeitar) só com permissão, e a conta do
Instagram lida sem nunca devolver o token."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app import coletor_ponte, contas, instagram
from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Conta, Sessao

SENHA = "senha-forte-1"
EMAILS = ["zzt-pd-leitor@exemplo.com", "zzt-pd-editor@exemplo.com", "zzt-pd-admin@exemplo.com"]


@pytest.fixture(autouse=True)
def _contas(monkeypatch):
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


def _entra(email, papel):
    with SessionLocal() as db:
        db.add(Conta(email=email, nome=email.split("@")[0], senha_hash=contas.hash_senha(SENHA), papel=papel,
                     cpf_codigo=hashlib.sha256(email.encode()).hexdigest()))
        db.commit()
    c = TestClient(app)
    assert c.post("/contas/entrar", json={"email": email, "senha": SENHA}).status_code == 200
    return c


@pytest.fixture
def coletor_temp(tmp_path, monkeypatch):
    """O coletor apontando para uma pasta temporária, com um vínculo e um dado retido para revisão."""
    c = coletor_ponte.modulo()
    raiz = tmp_path / "coletor"
    (raiz / "vinculos").mkdir(parents=True)
    (raiz / "vinculos" / "teste.toml").write_text('nome = "BRASIL+"\n[[fonte]]\nnome = "zzt-fonte"\nurl = "https://exemplo.gov.br/x.json"\n', encoding="utf-8")
    monkeypatch.setattr(c, "RAIZ", raiz)
    monkeypatch.setattr(c, "DADOS", raiz / "dados")
    monkeypatch.setattr(c, "RAW", raiz / "dados" / "raw")
    monkeypatch.setattr(c, "DB", raiz / "dados" / "manifesto.db")
    monkeypatch.setattr(c, "_do_cadastro", lambda: [])
    db = c.abrir_db()
    db.execute("INSERT INTO verificacao (fonte, sha256, veredito, liberado, decisao, motivos, em, por, ia) VALUES (?,?,?,?,?,?,?,?,?)",
               ("zzt-fonte", "ab" * 32, "suspeito", 0, "pendente", json.dumps(["valor muito acima do normal"]), "2026-11-13T10:00:00+00:00", "local", "ok"))
    db.commit()
    db.close()
    return c


def test_status_do_coletor_mostra_o_dado_retido(coletor_temp):
    cli = _entra(EMAILS[0], "leitor")
    j = cli.get("/coletor/status").json()
    assert "zzt-fonte" in j["bots"] and j["bots"]["zzt-fonte"]["verificacao"]["veredito"] == "suspeito"
    assert j["correcao"]["resumo"]["retidos"] == 1 and j["correcao"]["ia"]["ativa"] in (True, False)
    assert TestClient(app).get("/coletor/status").status_code == 401                              # sem login


def test_so_quem_tem_permissao_aprova_ou_rejeita(coletor_temp):
    leitor = _entra(EMAILS[0], "leitor")
    assert leitor.post("/coletor/decidir", json={"fonte": "zzt-fonte", "acao": "aprovar"}).status_code == 403
    editor = _entra(EMAILS[1], "editor")
    assert editor.post("/coletor/decidir", json={"fonte": "zzt-fonte", "acao": "apagar"}).status_code == 422
    r = editor.post("/coletor/decidir", json={"fonte": "zzt-fonte", "acao": "aprovar"})
    assert r.status_code == 200
    v = editor.get("/coletor/status").json()["bots"]["zzt-fonte"]["verificacao"]
    assert v["liberado"] is True and v["decisao"] == "aprovado"
    assert editor.post("/coletor/decidir", json={"fonte": "../etc", "acao": "aprovar"}).status_code == 422   # nome inválido
    assert editor.post("/coletor/decidir", json={"fonte": "nao-existe", "acao": "aprovar"}).status_code == 409
    assert editor.post("/coletor/desfazer", json={"fonte": "zzt-fonte"}).status_code == 409                  # não há correção ativa


def test_instagram_sem_token_mostra_passos(monkeypatch):
    monkeypatch.delenv("INSTAGRAM_TOKEN", raising=False)
    j = _entra(EMAILS[0], "leitor").get("/instagram/status").json()
    assert j["configurada"] is False and [p["estado"] for p in j["passos"]] == ["pendente"] * 4
    assert TestClient(app).get("/instagram/status").status_code == 401


def test_instagram_com_token_le_a_conta_e_nao_devolve_o_token(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_TOKEN", "token-secreto-de-teste")
    instagram._cache.update(em=0.0, dados=None)
    visto = []

    class R:
        status_code = 200
        text = ""

        def __init__(self, dados):
            self.dados = dados

        def raise_for_status(self):
            return None

        def json(self):
            return self.dados

    def falso(url, params=None, timeout=None):
        visto.append((url, dict(params)))
        if url.endswith("/me"):
            return R({"username": "brasilmais", "account_type": "BUSINESS", "media_count": 2})
        return R({"data": [{"id": "1", "caption": "Primeiro post", "media_type": "IMAGE", "permalink": "https://instagram.com/p/x", "timestamp": "2026-11-12T10:00:00+0000", "like_count": 3, "comments_count": 1}]})
    monkeypatch.setattr(instagram.httpx, "get", falso)
    j = _entra(EMAILS[0], "leitor").get("/instagram/status").json()
    assert j["conta"]["usuario"] == "brasilmais" and j["publicacoes"][0]["curtidas"] == 3
    assert [p["estado"] for p in j["passos"]] == ["feito", "feito", "feito", "pendente"]
    assert "token-secreto-de-teste" not in json.dumps(j)


def test_instagram_com_token_vencido_diz_o_que_fazer(monkeypatch):
    monkeypatch.setenv("INSTAGRAM_TOKEN", "token-secreto-de-teste")
    instagram._cache.update(em=0.0, dados=None)

    def vencido(url, params=None, timeout=None):
        raise PermissionError("o Instagram recusou o token (venceu ou foi revogado)")
    monkeypatch.setattr(instagram, "_chamar", lambda *a, **k: vencido("x"))
    j = _entra(EMAILS[0], "leitor").get("/instagram/status").json()
    assert "recusou o token" in j["erro"] and "token-secreto-de-teste" not in json.dumps(j)
